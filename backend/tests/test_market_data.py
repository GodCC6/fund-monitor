"""Tests for market data service."""

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from app.services.market_data import MarketDataService


@pytest.fixture
def market_service():
    return MarketDataService()


class TestGetStockQuote:
    def _mock_akshare_df(self, stocks: list[dict]) -> pd.DataFrame:
        """Helper to create a mock akshare DataFrame for stock_zh_a_spot_em."""
        if not stocks:
            return pd.DataFrame({"代码": [], "名称": [], "最新价": [], "涨跌幅": []})
        return pd.DataFrame({
            "代码": [s["code"] for s in stocks],
            "名称": [s["name"] for s in stocks],
            "最新价": [s["price"] for s in stocks],
            "涨跌幅": [s["change_pct"] for s in stocks],
        })

    def test_get_single_stock_quote(self, market_service):
        mock_df = self._mock_akshare_df([
            {"code": "600519", "name": "贵州茅台", "price": 1800.0, "change_pct": 2.5},
        ])
        with patch("app.services.market_data.ak.stock_zh_a_spot_em", return_value=mock_df):
            result = market_service.get_stock_quotes(["600519"])
            assert "600519" in result
            assert result["600519"]["price"] == 1800.0
            assert result["600519"]["change_pct"] == 2.5

    def test_get_multiple_stock_quotes(self, market_service):
        mock_df = self._mock_akshare_df([
            {"code": "600519", "name": "贵州茅台", "price": 1800.0, "change_pct": 2.5},
            {"code": "000858", "name": "五粮液", "price": 150.0, "change_pct": -1.2},
        ])
        with patch("app.services.market_data.ak.stock_zh_a_spot_em", return_value=mock_df):
            result = market_service.get_stock_quotes(["600519", "000858"])
            assert len(result) == 2
            assert result["000858"]["change_pct"] == -1.2

    def test_stock_not_found(self, market_service):
        mock_df = self._mock_akshare_df([
            {"code": "600000", "name": "浦发银行", "price": 10.0, "change_pct": 0.5},
        ])
        with patch("app.services.market_data.ak.stock_zh_a_spot_em", return_value=mock_df):
            result = market_service.get_stock_quotes(["999999"])
            assert len(result) == 0

    def test_hk_stock_skipped(self, market_service):
        """Hong Kong stock codes not present in A-share data should be absent from result."""
        mock_df = self._mock_akshare_df([])
        with patch("app.services.market_data.ak.stock_zh_a_spot_em", return_value=mock_df):
            result = market_service.get_stock_quotes(["00700"])
            assert isinstance(result, dict)


class TestGetFundHoldings:
    def test_get_fund_top_holdings(self, market_service):
        mock_df = pd.DataFrame(
            {
                "股票代码": ["600519", "000858"],
                "股票名称": ["贵州茅台", "五粮液"],
                "占净值比例": [8.9, 6.5],
            }
        )
        with patch(
            "app.services.market_data.ak.fund_portfolio_hold_em", return_value=mock_df
        ):
            result = market_service.get_fund_holdings("000001", "2025")
            assert len(result) == 2
            assert result[0]["stock_code"] == "600519"
            assert result[0]["holding_ratio"] == pytest.approx(0.089)


class TestGetFundNav:
    def test_get_latest_nav(self, market_service):
        mock_df = pd.DataFrame(
            {
                "净值日期": ["2026-02-13", "2026-02-14"],
                "单位净值": [1.220, 1.234],
                "日增长率": [-0.5, 1.15],
            }
        )
        with patch(
            "app.services.market_data.ak.fund_open_fund_info_em", return_value=mock_df
        ):
            result = market_service.get_fund_nav("000001")
            assert result["nav"] == 1.234
            assert result["nav_date"] == "2026-02-14"
