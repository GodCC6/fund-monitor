"""Market data service using akshare for stock quotes and fund info."""

import logging
from typing import Any

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


class MarketDataService:
    """Fetches market data from akshare."""

    def get_stock_quotes(self, stock_codes: list[str]) -> dict[str, dict[str, Any]]:
        """Get real-time quotes for a list of stock codes.

        Returns dict mapping stock_code -> {price, change_pct, name}.
        """
        try:
            df = ak.stock_zh_a_spot_em()
            if df.empty:
                return {}

            code_set = set(stock_codes)
            filtered = df[df["代码"].isin(code_set)]

            result = {}
            for _, row in filtered.iterrows():
                code = row["代码"]
                result[code] = {
                    "price": float(row["最新价"]),
                    "change_pct": float(row["涨跌幅"]),
                    "name": row["名称"],
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

            latest = df.iloc[0]
            return {
                "nav": float(latest["单位净值"]),
                "nav_date": str(latest["净值日期"]),
                "acc_nav": float(latest.get("累计净值", 0)),
            }
        except Exception as e:
            logger.error(f"Failed to fetch NAV for {fund_code}: {e}")
            return None


# Global instance
market_data_service = MarketDataService()
