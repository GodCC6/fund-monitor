"""Market data service using akshare for fund info and eastmoney API for stock quotes."""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any

# China Standard Time (UTC+8)
_CST = timezone(timedelta(hours=8))

import akshare as ak
import requests
import pandas as pd

logger = logging.getLogger(__name__)

# Module-level cache: fund_code -> (timestamp, {date_str: nav})
_nav_history_cache: dict[str, tuple[float, dict[str, float]]] = {}
_NAV_HISTORY_CACHE_TTL = 3600  # 1 hour

# Browser-like headers to avoid anti-bot blocking on eastmoney APIs
_EM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.eastmoney.com/",
}



class MarketDataService:
    """Fetches market data from akshare."""

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

        Uses the CSI 300 intraday trends endpoint as the source of truth.
        On weekends and public holidays the endpoint returns the last trading
        day's data, whose date will not match today.
        """
        now_cst = datetime.now(_CST)
        today_str = now_cst.strftime("%Y-%m-%d")
        if now_cst.weekday() >= 5:  # Saturday or Sunday
            return False
        try:
            url = (
                "https://push2.eastmoney.com/api/qt/stock/trends2/get"
                "?secid=1.000300&fields1=f2&fields2=f51&iscr=0&ndays=1"
            )
            resp = requests.get(url, timeout=5, headers=_EM_HEADERS)
            data = resp.json()
            trends = (data.get("data") or {}).get("trends", [])
            if not trends:
                return False
            # Entry format: "2026-02-13 09:30"
            first_date = trends[0].split(",")[0].split(" ")[0]
            return first_date == today_str
        except Exception:
            return True  # If check fails, assume market is open

    def get_stock_quotes(self, stock_codes: list[str]) -> dict[str, dict[str, Any]]:
        """Get real-time quotes for a list of stock codes via akshare.

        Returns dict mapping stock_code -> {price, change_pct, name}.
        """
        if not stock_codes:
            return {}
        try:
            df = ak.stock_zh_a_spot_em()
            if df.empty:
                return {}

            cols = df.columns.tolist()
            logger.debug(f"stock_zh_a_spot_em columns ({len(cols)}): {cols}")

            # Detect actual column names defensively across akshare versions
            code_col = next(
                (c for c in ["代码", "股票代码", "symbol"] if c in cols), None
            )
            price_col = next(
                (c for c in ["最新价", "现价", "price"] if c in cols), None
            )
            change_col = next(
                (c for c in ["涨跌幅", "涨跌幅(%)", "change_pct"] if c in cols), None
            )
            name_col = next(
                (c for c in ["名称", "股票名称", "name"] if c in cols), None
            )

            if not code_col:
                logger.error(f"Cannot find stock code column in akshare output: {cols}")
                return {}
            if not price_col:
                logger.error(f"Cannot find price column in akshare output: {cols}")
                return {}
            if not change_col:
                logger.error(f"Cannot find change_pct column in akshare output: {cols}")
                return {}

            code_set = set(stock_codes)
            result = {}
            for _, row in df.iterrows():
                raw_code = row.get(code_col, "") if code_col else ""
                code = str(raw_code or "").strip().zfill(6)
                if code not in code_set:
                    continue
                try:
                    price_raw = row[price_col]
                    change_raw = row[change_col]
                    # Skip rows with null/non-numeric values (e.g. suspended stocks,
                    # or intraday fields not available after market hours)
                    if pd.isna(price_raw) or pd.isna(change_raw):
                        continue
                    price = float(price_raw)
                    change_pct = float(change_raw)
                    name = str(row.get(name_col, "") or "") if name_col else ""
                    result[code] = {
                        "price": price,
                        "change_pct": change_pct,
                        "name": name,
                    }
                except (ValueError, TypeError, KeyError):
                    continue
            return result
        except Exception as e:
            logger.error(f"Failed to fetch stock quotes via akshare: {e}", exc_info=True)
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
