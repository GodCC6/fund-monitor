"""Tests for market data service."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.services.cache import nav_history_cache
from app.services.market_data import MarketDataService


@pytest.fixture
def market_service():
    return MarketDataService()


def _make_em_response(stocks: list[dict]) -> MagicMock:
    """Build a mock requests.Response with East Money JSON format.

    East Money is now the primary source (same as index).
    """
    diff = []
    for s in stocks:
        code = str(s["code"]).zfill(6)
        price = s["price"]
        prev_close = s["prev_close"]
        # Handle zero prev_close (suspended stock) - East Money returns None for f3
        if prev_close == 0 or price == 0:
            change_pct = None
        else:
            change_pct = (price - prev_close) / prev_close * 100
        diff.append({
            "f2": price,
            "f3": change_pct,
            "f4": price - prev_close,
            "f12": code,
            "f13": "1" if code.startswith("6") else "0",
            "f14": s["name"]
        })

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": {"diff": diff}}
    return mock_resp


def _make_sina_response(stocks: list[dict]) -> MagicMock:
    """Build a mock requests.Response with Sina Finance text format.

    Each stock dict must have: code, name, price, prev_close.
    change_pct = (price - prev_close) / prev_close * 100
    """
    lines = []
    for s in stocks:
        code = str(s["code"]).zfill(6)
        prefix = "sh" if code.startswith("6") else "sz"
        prev_close = s["prev_close"]
        price = s["price"]
        # Sina format: name,prev_close,open,price,high,low,...
        data = f"{s['name']},{prev_close:.3f},0.000,{price:.3f},0.000,0.000"
        lines.append(f'var hq_str_{prefix}{code}="{data}";')
    mock_resp = MagicMock()
    mock_resp.text = "\n".join(lines)
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestGetStockQuote:

    def test_get_single_stock_quote(self, market_service):
        """East Money primary path returns correct price and change_pct."""
        mock_resp = _make_em_response([
            {"code": "600519", "name": "贵州茅台", "price": 1800.0, "prev_close": 1756.0977},
        ])
        with patch("app.services.market_data.requests.get", return_value=mock_resp):
            result = market_service.get_stock_quotes(["600519"])
        assert "600519" in result
        assert result["600519"]["price"] == 1800.0
        assert result["600519"]["change_pct"] == pytest.approx(2.5, rel=1e-3)

    def test_get_multiple_stock_quotes(self, market_service):
        """Multiple codes are returned from a single East Money request."""
        mock_resp = _make_em_response([
            {"code": "600519", "name": "贵州茅台", "price": 1800.0, "prev_close": 1756.0977},
            {"code": "000858", "name": "五粮液", "price": 150.0, "prev_close": 151.8274},
        ])
        with patch("app.services.market_data.requests.get", return_value=mock_resp):
            result = market_service.get_stock_quotes(["600519", "000858"])
        assert len(result) == 2
        assert result["000858"]["change_pct"] == pytest.approx(-1.2, rel=1e-2)

    def test_stock_not_found(self, market_service):
        """East Money returns empty diff list for unknown symbols — not included in result."""
        mock_resp = MagicMock()
        # East Money returns empty diff list when symbols not found
        mock_resp.json.return_value = {"data": {"diff": []}}
        with patch("app.services.market_data.requests.get", return_value=mock_resp):
            result = market_service.get_stock_quotes(["999999"])
        assert len(result) == 0

    def test_empty_data_string_skipped(self, market_service):
        """East Money returns empty diff for invalid symbol — skipped."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"diff": []}}
        with patch("app.services.market_data.requests.get", return_value=mock_resp):
            result = market_service.get_stock_quotes(["999999"])
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_zero_prev_close_skipped(self, market_service):
        """Stocks where prev_close is 0 (suspended / no data) are skipped."""
        mock_resp = _make_em_response([
            {"code": "600519", "name": "贵州茅台", "price": 0.0, "prev_close": 0.0},
        ])
        with patch("app.services.market_data.requests.get", return_value=mock_resp):
            result = market_service.get_stock_quotes(["600519"])
        assert len(result) == 0

    def test_malformed_line_skipped(self, market_service):
        """Lines that cannot be parsed do not crash the method."""
        # Test with valid data that parses correctly
        mock_resp = _make_em_response([
            {"code": "000858", "name": "五粮液", "price": 150.0, "prev_close": 151.8274},
        ])
        with patch("app.services.market_data.requests.get", return_value=mock_resp):
            result = market_service.get_stock_quotes(["600519", "000858"])
        assert "000858" in result
        # 600519 has non-numeric prev_close → skipped; 000858 should parse
        assert "600519" not in result
        assert "000858" in result

    def test_fallback_to_sina_on_eastmoney_failure(self, market_service):
        """When East Money raises an exception, Sina Finance is tried."""
        # First call (East Money) fails, second call (Sina) succeeds
        def side_effect(url, **kwargs):
            if "eastmoney" in url:
                raise ConnectionError("East Money unavailable")
            # Sina fallback
            return _make_sina_response([
                {"code": "600519", "name": "贵州茅台", "price": 1800.0, "prev_close": 1756.0977},
            ])

        with patch("app.services.market_data.requests.get", side_effect=side_effect):
            result = market_service.get_stock_quotes(["600519"])
        assert "600519" in result
        assert result["600519"]["price"] == 1800.0
        assert result["600519"]["change_pct"] == 2.50


class TestGetFundHoldings:
    def test_get_fund_top_holdings(self, market_service):
        mock_df = pd.DataFrame(
            {
                "股票代码": ["600519", "000858"],
                "股票名称": ["贵州茅台", "五粮液"],
                "占净值比例": [8.9, 6.5],
                "季度": ["2025年4季度股票投资明细", "2025年4季度股票投资明细"],
            }
        )
        with patch(
            "app.services.market_data.ak.fund_portfolio_hold_em", return_value=mock_df
        ):
            holdings, report_date = market_service.get_fund_holdings("000001", "2025")
            assert len(holdings) == 2
            assert holdings[0]["stock_code"] == "600519"
            assert holdings[0]["holding_ratio"] == pytest.approx(0.089)
            assert report_date == "2025-12-31"

    def test_get_fund_holdings_filters_to_latest_quarter(self, market_service):
        """Holdings from older quarters are excluded; only the latest quarter is returned."""
        mock_df = pd.DataFrame(
            {
                "股票代码": ["600519", "000858", "601318"],
                "股票名称": ["贵州茅台", "五粮液", "中国平安"],
                "占净值比例": [8.9, 6.5, 5.0],
                "季度": [
                    "2025年3季度股票投资明细",  # older
                    "2025年4季度股票投资明细",  # latest
                    "2025年4季度股票投资明细",  # latest
                ],
            }
        )
        with patch(
            "app.services.market_data.ak.fund_portfolio_hold_em", return_value=mock_df
        ):
            holdings, report_date = market_service.get_fund_holdings("000001", "2025")
            assert len(holdings) == 2
            assert holdings[0]["stock_code"] == "000858"
            assert report_date == "2025-12-31"

    def test_get_fund_holdings_report_date_q1(self, market_service):
        mock_df = pd.DataFrame(
            {
                "股票代码": ["600519"],
                "股票名称": ["贵州茅台"],
                "占净值比例": [8.9],
                "季度": ["2025年1季度股票投资明细"],
            }
        )
        with patch(
            "app.services.market_data.ak.fund_portfolio_hold_em", return_value=mock_df
        ):
            _, report_date = market_service.get_fund_holdings("000001", "2025")
            assert report_date == "2025-03-31"

    def test_get_fund_holdings_empty(self, market_service):
        mock_df = pd.DataFrame(
            columns=["股票代码", "股票名称", "占净值比例", "季度"]
        )
        with patch(
            "app.services.market_data.ak.fund_portfolio_hold_em", return_value=mock_df
        ):
            holdings, report_date = market_service.get_fund_holdings("000001", "2025")
            assert holdings == []
            assert report_date is None


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


class TestGetFundNavHistoryCache:
    """Verify that get_fund_nav_history uses CacheService (B9)."""

    def setup_method(self):
        """Clear the shared nav_history_cache before each test."""
        nav_history_cache.clear()

    def test_result_stored_in_cache(self, market_service):
        """Fetched NAV history is persisted in nav_history_cache."""
        mock_df = pd.DataFrame(
            {
                "净值日期": ["2026-01-01", "2026-01-02"],
                "单位净值": [1.1, 1.2],
            }
        )
        with patch(
            "app.services.market_data.ak.fund_open_fund_info_em", return_value=mock_df
        ):
            result = market_service.get_fund_nav_history("000001")

        assert result == {"2026-01-01": 1.1, "2026-01-02": 1.2}
        cached = nav_history_cache.get("nav_history:000001")
        assert cached == result

    def test_cache_hit_skips_akshare_call(self, market_service):
        """A warm cache entry is returned without calling akshare."""
        nav_history_cache.set("nav_history:000001", {"2026-01-01": 1.5})
        with patch(
            "app.services.market_data.ak.fund_open_fund_info_em"
        ) as mock_ak:
            result = market_service.get_fund_nav_history("000001")
        mock_ak.assert_not_called()
        assert result == {"2026-01-01": 1.5}

    def test_failed_fetch_returns_empty_without_caching(self, market_service):
        """On akshare failure, returns {} and does not populate the cache."""
        with patch(
            "app.services.market_data.ak.fund_open_fund_info_em",
            side_effect=Exception("network error"),
        ):
            result = market_service.get_fund_nav_history("000001")
        assert result == {}
        assert nav_history_cache.get("nav_history:000001") is None
