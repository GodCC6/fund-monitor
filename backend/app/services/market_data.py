"""Market data service using akshare for fund info and eastmoney API for stock quotes."""

import logging
import time
from datetime import datetime
from typing import Any

import akshare as ak
import httpx
import pandas as pd

logger = logging.getLogger(__name__)

# Module-level cache: fund_code -> (timestamp, {date_str: nav})
_nav_history_cache: dict[str, tuple[float, dict[str, float]]] = {}
_NAV_HISTORY_CACHE_TTL = 3600  # 1 hour


# Eastmoney market prefix: 沪市=1, 深市=0
def _get_secid(stock_code: str) -> str:
    """Convert stock code to eastmoney secid format."""
    if stock_code.startswith(("6", "9")):
        return f"1.{stock_code}"
    elif stock_code.startswith(("0", "3", "2")):
        return f"0.{stock_code}"
    else:
        # 港股等暂不支持
        return ""


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
        today_str = datetime.now().strftime("%Y-%m-%d")
        if datetime.now().weekday() >= 5:  # Saturday or Sunday
            return False
        try:
            url = (
                "https://push2.eastmoney.com/api/qt/stock/trends2/get"
                "?secid=1.000300&fields1=f2&fields2=f51&iscr=0&ndays=1"
            )
            resp = httpx.get(url, timeout=5)
            data = resp.json()
            trends = data.get("data", {}).get("trends", [])
            if not trends:
                return False
            # Entry format: "2026-02-13 09:30"
            first_date = trends[0].split(",")[0].split(" ")[0]
            return first_date == today_str
        except Exception:
            return True  # If check fails, assume market is open

    def get_stock_quotes(self, stock_codes: list[str]) -> dict[str, dict[str, Any]]:
        """Get real-time quotes for a list of stock codes.

        Uses eastmoney batch API for fast retrieval (only requested stocks).
        Returns dict mapping stock_code -> {price, change_pct, name}.
        """
        try:
            # Build secids, filtering out unsupported codes (e.g. HK stocks)
            secid_map = {}
            for code in stock_codes:
                secid = _get_secid(code)
                if secid:
                    secid_map[code] = secid

            if not secid_map:
                return {}

            secids = ",".join(secid_map.values())
            url = (
                f"https://push2.eastmoney.com/api/qt/ulist.np/get"
                f"?fltt=2&fields=f2,f3,f12,f14&secids={secids}"
            )
            resp = httpx.get(url, timeout=10)
            data = resp.json()

            if not data.get("data") or not data["data"].get("diff"):
                return {}

            result = {}
            for item in data["data"]["diff"]:
                code = str(item["f12"])
                price = item.get("f2")
                change_pct = item.get("f3")
                if price is not None and price != "-" and change_pct is not None:
                    result[code] = {
                        "price": float(price),
                        "change_pct": float(change_pct),
                        "name": str(item.get("f14", "")),
                    }
            return result
        except Exception as e:
            logger.error(f"Failed to fetch stock quotes: {e}")
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
