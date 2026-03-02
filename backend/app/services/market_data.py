"""Market data service using akshare for fund info and eastmoney API for stock quotes."""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any

# China Standard Time (UTC+8)
_CST = timezone(timedelta(hours=8))

import akshare as ak
import requests

logger = logging.getLogger(__name__)

# Module-level cache: fund_code -> (timestamp, {date_str: nav})
_nav_history_cache: dict[str, tuple[float, dict[str, float]]] = {}
_NAV_HISTORY_CACHE_TTL = 3600  # 1 hour

# Cache for is_market_trading_today(): (timestamp, result)
_trading_today_cache: tuple[float, bool] | None = None
_TRADING_TODAY_CACHE_TTL = 300  # 5 minutes

# Browser-like headers to avoid anti-bot blocking on eastmoney APIs
_EM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.eastmoney.com/",
}


def _stock_exchange_prefix(code: str) -> str:
    """Return 'sh' for Shanghai stocks, 'sz' for Shenzhen, 'bj' for Beijing."""
    code = str(code).zfill(6)
    if code.startswith("6"):
        return "sh"
    if code.startswith(("4", "8")):
        return "bj"
    return "sz"


class MarketDataService:
    """Fetches market data from akshare and direct finance APIs."""

    def get_fund_basic_info(self, fund_code: str) -> dict[str, str] | None:
        """Get fund name and type from akshare.

        Returns {fund_name, fund_type} or None.
        """
        try:
            df = ak.fund_name_em()
            row = df[df["基金代码"] == fund_code]
            if row.empty:
                return None
            first = row.iloc[0]
            return {
                "fund_name": str(first["基金简称"]),
                "fund_type": str(first["基金类型"]),
            }
        except Exception as e:
            logger.error(f"Failed to fetch fund basic info for {fund_code}: {e}")
            return None

    def is_market_trading_today(self) -> bool:
        """Return True if the A-share market has trading data for today.

        Uses the CSI 300 intraday trends endpoint (push2his.eastmoney.com) as the
        source of truth.  On weekends and public holidays the endpoint returns the
        last trading day's data, whose date will not match today.

        Result is cached for 5 minutes to avoid a live HTTP call on every
        /estimate request.
        """
        global _trading_today_cache

        now_cst = datetime.now(_CST)
        today_str = now_cst.strftime("%Y-%m-%d")
        if now_cst.weekday() >= 5:  # Saturday or Sunday
            return False

        # Return cached result if still fresh
        now_ts = time.time()
        if _trading_today_cache is not None:
            cached_ts, cached_result = _trading_today_cache
            if now_ts - cached_ts < _TRADING_TODAY_CACHE_TTL:
                return cached_result

        try:
            # Use push2his.eastmoney.com — same host that serves the intraday index
            # endpoint and is accessible from this server.
            resp = requests.get(
                "https://push2his.eastmoney.com/api/qt/stock/trends2/get",
                params={
                    "secid": "1.000300",
                    "fields1": "f2",
                    "fields2": "f51",
                    "iscr": "0",
                    "ndays": "1",
                },
                timeout=5,
                headers=_EM_HEADERS,
            )
            data = resp.json()
            trends = (data.get("data") or {}).get("trends", [])
            if not trends:
                result = False
            else:
                # Entry format: "2026-02-13 09:30,..."
                first_date = trends[0].split(",")[0].split(" ")[0]
                result = first_date == today_str
            _trading_today_cache = (now_ts, result)
            return result
        except Exception:
            return True  # If check fails, assume market is open

    def _get_stock_quotes_via_sina(
        self, stock_codes: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Fetch real-time quotes from Sina Finance API (hq.sinajs.cn).

        Single batched request for all codes.
        Response format per line:
            var hq_str_sh600519="name,prev_close,open,price,high,low,...,date,time,...";
        Relevant fields: [0]=name, [1]=prev_close, [3]=current_price
        """
        normalized = [str(c).zfill(6) for c in stock_codes]
        symbols = [f"{_stock_exchange_prefix(c)}{c}" for c in normalized]
        resp = requests.get(
            f"https://hq.sinajs.cn/rn={int(time.time())}&list={','.join(symbols)}",
            headers={
                "Referer": "https://finance.sina.com.cn/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            timeout=10,
        )
        resp.raise_for_status()
        result: dict[str, dict[str, Any]] = {}
        for line in resp.text.strip().splitlines():
            # Format: var hq_str_sh600519="name,prev_close,open,price,...";
            if not line.startswith("var hq_str_"):
                continue
            try:
                symbol_part = line.split("=")[0].split("hq_str_")[1]
                code = symbol_part[2:].zfill(6)  # strip sh/sz/bj prefix
                data_str = line.split('"')[1]
                if not data_str:
                    continue
                parts = data_str.split(",")
                if len(parts) < 4:
                    continue
                name = parts[0]
                prev_close = float(parts[1])
                price = float(parts[3])
                if prev_close == 0 or price == 0:
                    continue
                change_pct = (price - prev_close) / prev_close * 100
                result[code] = {
                    "price": price,
                    "change_pct": round(change_pct, 4),
                    "name": name,
                }
            except (IndexError, ValueError, TypeError):
                continue
        return result

    def _get_stock_quotes_via_tencent(
        self, stock_codes: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Fetch real-time quotes from Tencent Finance API (qt.gtimg.cn).

        Used as fallback when Sina Finance is unavailable.
        Response format per stock:
            v_sh600519="1~name~code~price~prev_close~open~...~change_pct~..."
        Relevant indices: [1]=name, [3]=price, [32]=change_pct
        """
        normalized = [str(c).zfill(6) for c in stock_codes]
        query = ",".join(f"{_stock_exchange_prefix(c)}{c}" for c in normalized)
        resp = requests.get(
            f"https://qt.gtimg.cn/q={query}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        result: dict[str, dict[str, Any]] = {}
        for line in resp.text.splitlines():
            if "=" not in line:
                continue
            _, _, value = line.partition("=")
            value = value.strip().strip('"').strip(";")
            parts = value.split("~")
            if len(parts) < 33:
                continue
            try:
                code = str(parts[2]).zfill(6)
                price = float(parts[3])
                change_pct = float(parts[32])
                name = parts[1]
                result[code] = {"price": price, "change_pct": change_pct, "name": name}
            except (ValueError, IndexError):
                continue
        return result

    def get_stock_quotes(self, stock_codes: list[str]) -> dict[str, dict[str, Any]]:
        """Get real-time quotes for a list of stock codes.

        Tries Sina Finance first, falls back to Tencent Finance.
        Returns dict mapping stock_code -> {price, change_pct, name}.
        Keys are always 6-digit zero-padded pure numeric strings.
        """
        if not stock_codes:
            return {}
        try:
            return self._get_stock_quotes_via_sina(stock_codes)
        except Exception as e:
            logger.warning(f"Sina Finance stock quotes failed ({e}), trying Tencent")
            try:
                return self._get_stock_quotes_via_tencent(stock_codes)
            except Exception as e2:
                logger.error(f"Tencent Finance fallback also failed: {e2}", exc_info=True)
                return {}

    def get_fund_holdings(self, fund_code: str, year: str) -> list[dict[str, Any]]:
        """Get fund top holdings from quarterly report.

        Returns list of {stock_code, stock_name, holding_ratio}.
        """
        try:
            df = ak.fund_portfolio_hold_em(symbol=fund_code, date=year)
            if df.empty:
                return []

            holdings = []
            for _, row in df.iterrows():
                holdings.append(
                    {
                        "stock_code": row["股票代码"],
                        "stock_name": row["股票名称"],
                        "holding_ratio": float(row["占净值比例"]) / 100.0,
                    }
                )
            return holdings
        except Exception as e:
            logger.error(f"Failed to fetch fund holdings for {fund_code}: {e}")
            return []

    def get_fund_nav(self, fund_code: str) -> dict[str, Any] | None:
        """Get the latest NAV for a fund.

        Returns {nav, nav_date, acc_nav} or None.
        """
        try:
            df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
            if df.empty:
                return None

            latest = df.iloc[-1]
            return {
                "nav": float(latest["单位净值"]),
                "nav_date": str(latest["净值日期"]),
                "acc_nav": float(latest.get("累计净值", latest.get("单位净值", 0))),
            }
        except Exception as e:
            logger.error(f"Failed to fetch NAV for {fund_code}: {e}")
            return None

    def get_fund_nav_history(self, fund_code: str) -> dict[str, float]:
        """Get full NAV history for a fund. Returns {date_str: nav}. Cached 1 hour."""
        now = time.time()
        if fund_code in _nav_history_cache:
            ts, data = _nav_history_cache[fund_code]
            if now - ts < _NAV_HISTORY_CACHE_TTL:
                return data
        try:
            df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
            nav_dict: dict[str, float] = {}
            for _, row in df.iterrows():
                date_str = str(row["净值日期"])[:10]  # "YYYY-MM-DD"
                nav_dict[date_str] = float(row["单位净值"])
            _nav_history_cache[fund_code] = (now, nav_dict)
            return nav_dict
        except Exception as e:
            logger.error(f"Failed to fetch NAV history for {fund_code}: {e}")
            return {}


# Global instance
market_data_service = MarketDataService()
