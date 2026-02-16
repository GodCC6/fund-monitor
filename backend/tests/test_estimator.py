"""Tests for fund estimator engine."""

import pytest
from unittest.mock import patch, MagicMock
from app.services.estimator import FundEstimator


@pytest.fixture
def estimator():
    return FundEstimator()


class TestCalculateEstimate:
    def test_basic_estimate(self, estimator):
        """Fund with 2 holdings, both up."""
        holdings = [
            {"stock_code": "600519", "stock_name": "贵州茅台", "holding_ratio": 0.089},
            {"stock_code": "000858", "stock_name": "五粮液", "holding_ratio": 0.065},
        ]
        stock_quotes = {
            "600519": {"price": 1800.0, "change_pct": 2.0, "name": "贵州茅台"},
            "000858": {"price": 150.0, "change_pct": -1.0, "name": "五粮液"},
        }
        last_nav = 1.0

        result = estimator.calculate_estimate(holdings, stock_quotes, last_nav)

        # Expected: 0.089 * 2.0% + 0.065 * (-1.0%) = 0.178% - 0.065% = 0.113%
        expected_change_pct = 0.089 * 2.0 + 0.065 * (-1.0)
        expected_nav = last_nav * (1 + expected_change_pct / 100)

        assert abs(result["est_change_pct"] - expected_change_pct) < 0.0001
        assert abs(result["est_nav"] - expected_nav) < 0.0001
        assert result["coverage"] == pytest.approx(0.154, abs=0.001)

    def test_all_holdings_flat(self, estimator):
        """All stocks unchanged."""
        holdings = [
            {"stock_code": "600519", "stock_name": "贵州茅台", "holding_ratio": 0.089},
        ]
        stock_quotes = {
            "600519": {"price": 1800.0, "change_pct": 0.0, "name": "贵州茅台"},
        }
        result = estimator.calculate_estimate(holdings, stock_quotes, 2.0)
        assert result["est_change_pct"] == 0.0
        assert result["est_nav"] == 2.0

    def test_missing_stock_quote(self, estimator):
        """A holding stock has no quote available."""
        holdings = [
            {"stock_code": "600519", "stock_name": "贵州茅台", "holding_ratio": 0.089},
            {"stock_code": "999999", "stock_name": "已退市", "holding_ratio": 0.05},
        ]
        stock_quotes = {
            "600519": {"price": 1800.0, "change_pct": 3.0, "name": "贵州茅台"},
        }
        result = estimator.calculate_estimate(holdings, stock_quotes, 1.5)

        # Only 600519 contributes
        expected_change = 0.089 * 3.0
        assert abs(result["est_change_pct"] - expected_change) < 0.0001
        assert result["coverage"] == pytest.approx(0.089, abs=0.001)

    def test_empty_holdings(self, estimator):
        """No holdings data."""
        result = estimator.calculate_estimate([], {}, 1.0)
        assert result["est_change_pct"] == 0.0
        assert result["est_nav"] == 1.0
        assert result["coverage"] == 0.0

    def test_holding_details_in_result(self, estimator):
        """Result includes per-stock contribution details."""
        holdings = [
            {"stock_code": "600519", "stock_name": "贵州茅台", "holding_ratio": 0.089},
        ]
        stock_quotes = {
            "600519": {"price": 1800.0, "change_pct": 2.0, "name": "贵州茅台"},
        }
        result = estimator.calculate_estimate(holdings, stock_quotes, 1.0)
        assert len(result["details"]) == 1
        detail = result["details"][0]
        assert detail["stock_code"] == "600519"
        assert detail["change_pct"] == 2.0
        assert abs(detail["contribution"] - 0.089 * 2.0) < 0.0001
