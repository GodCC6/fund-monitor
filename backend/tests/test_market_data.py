"""Tests for market data service."""

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from app.services.market_data import MarketDataService


@pytest.fixture
def market_service():
    return MarketDataService()


class TestGetStockQuote:
    def test_get_single_stock_quote(self, market_service):
        mock_df = pd.DataFrame(
            {
                "代码": ["600519"],
                "名称": ["贵州茅台"],
                "最新价": [1800.0],
                "涨跌幅": [2.5],
                "昨收": [1756.10],
            }
        )
        with patch(
            "app.services.market_data.ak.stock_zh_a_spot_em", return_value=mock_df
        ):
            result = market_service.get_stock_quotes(["600519"])
            assert "600519" in result
            assert result["600519"]["price"] == 1800.0
            assert result["600519"]["change_pct"] == 2.5

    def test_get_multiple_stock_quotes(self, market_service):
        mock_df = pd.DataFrame(
            {
                "代码": ["600519", "000858"],
                "名称": ["贵州茅台", "五粮液"],
                "最新价": [1800.0, 150.0],
                "涨跌幅": [2.5, -1.2],
                "昨收": [1756.10, 151.82],
            }
        )
        with patch(
            "app.services.market_data.ak.stock_zh_a_spot_em", return_value=mock_df
        ):
            result = market_service.get_stock_quotes(["600519", "000858"])
            assert len(result) == 2
            assert result["000858"]["change_pct"] == -1.2

    def test_stock_not_found(self, market_service):
        mock_df = pd.DataFrame(
            {
                "代码": ["600519"],
                "名称": ["贵州茅台"],
                "最新价": [1800.0],
                "涨跌幅": [2.5],
                "昨收": [1756.10],
            }
        )
        with patch(
            "app.services.market_data.ak.stock_zh_a_spot_em", return_value=mock_df
        ):
            result = market_service.get_stock_quotes(["999999"])
            assert len(result) == 0


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
                "净值日期": ["2026-02-14", "2026-02-13"],
                "单位净值": [1.234, 1.220],
                "累计净值": [3.456, 3.442],
            }
        )
        with patch(
            "app.services.market_data.ak.fund_open_fund_info_em", return_value=mock_df
        ):
            result = market_service.get_fund_nav("000001")
            assert result["nav"] == 1.234
            assert result["nav_date"] == "2026-02-14"
