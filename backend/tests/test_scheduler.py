"""Tests for scheduler retry logic with exponential backoff and AKShare health probe."""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pandas as pd
import pytest

from app.tasks.scheduler import (
    _STOCK_FETCH_BASE_DELAY,
    _STOCK_FETCH_MAX_RETRIES,
    _fetch_quotes_with_retry,
    probe_akshare_health,
)

STOCK_CODES = ["600519", "000858"]
SAMPLE_QUOTES = {
    "600519": {"price": 1800.0, "change_pct": 1.5, "name": "贵州茅台"},
    "000858": {"price": 150.0, "change_pct": -0.5, "name": "五粮液"},
}


class TestFetchQuotesWithRetry:
    async def test_success_on_first_attempt_no_sleep(self):
        """When quotes are returned on the first attempt, no sleep is called."""
        with patch(
            "app.tasks.scheduler.market_data_service.get_stock_quotes",
            return_value=SAMPLE_QUOTES,
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await _fetch_quotes_with_retry(STOCK_CODES)
        assert result == SAMPLE_QUOTES
        mock_sleep.assert_not_called()

    async def test_retries_on_empty_result_and_succeeds(self):
        """An empty result triggers a retry; succeeds when second attempt returns data."""
        with patch(
            "app.tasks.scheduler.market_data_service.get_stock_quotes",
            side_effect=[{}, SAMPLE_QUOTES],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await _fetch_quotes_with_retry(STOCK_CODES)
        assert result == SAMPLE_QUOTES
        # Should sleep once before the second attempt (base_delay * 2^0 = base_delay)
        mock_sleep.assert_called_once_with(_STOCK_FETCH_BASE_DELAY)

    async def test_exponential_backoff_delay_doubles_each_retry(self):
        """Delays follow exponential backoff: base, base*2, base*4, ..."""
        # Fail first two attempts, succeed on third
        with patch(
            "app.tasks.scheduler.market_data_service.get_stock_quotes",
            side_effect=[{}, {}, SAMPLE_QUOTES],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await _fetch_quotes_with_retry(STOCK_CODES)
        assert result == SAMPLE_QUOTES
        assert mock_sleep.call_count == 2
        assert mock_sleep.call_args_list[0] == call(_STOCK_FETCH_BASE_DELAY * 1)
        assert mock_sleep.call_args_list[1] == call(_STOCK_FETCH_BASE_DELAY * 2)

    async def test_gives_up_after_max_retries_returns_empty(self):
        """After _STOCK_FETCH_MAX_RETRIES failed attempts, returns empty dict."""
        with patch(
            "app.tasks.scheduler.market_data_service.get_stock_quotes",
            return_value={},
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await _fetch_quotes_with_retry(STOCK_CODES)
        assert result == {}
        # Sleep is called between attempts but not after the last one
        assert mock_sleep.call_count == _STOCK_FETCH_MAX_RETRIES - 1

    async def test_no_sleep_after_final_failed_attempt(self):
        """The last retry attempt does not sleep after failure."""
        sleep_calls = []
        get_calls = []

        async def fake_sleep(delay):
            sleep_calls.append(delay)

        def fake_get_quotes(codes):
            get_calls.append(codes)
            return {}

        with patch(
            "app.tasks.scheduler.market_data_service.get_stock_quotes",
            side_effect=fake_get_quotes,
        ):
            with patch("asyncio.sleep", side_effect=fake_sleep):
                await _fetch_quotes_with_retry(STOCK_CODES)

        assert len(get_calls) == _STOCK_FETCH_MAX_RETRIES
        assert len(sleep_calls) == _STOCK_FETCH_MAX_RETRIES - 1

    async def test_empty_stock_codes_returns_empty_without_fetch(self):
        """Empty codes list returns {} without calling get_stock_quotes."""
        with patch(
            "app.tasks.scheduler.market_data_service.get_stock_quotes",
        ) as mock_get:
            result = await _fetch_quotes_with_retry([])
        assert result == {}
        mock_get.assert_not_called()


class TestProbeAkshareHealth:
    """Tests for the AKShare health monitoring probe."""

    @pytest.fixture
    def ok_df(self):
        """A non-empty DataFrame simulating a healthy API response."""
        return pd.DataFrame({"value": [1.0, 2.0]})

    @pytest.fixture
    def empty_df(self):
        """An empty DataFrame simulating a degraded API response."""
        return pd.DataFrame()

    async def test_all_probes_ok_returns_ok_status(self, ok_df):
        """When all three probes succeed, result maps each name to 'ok'."""
        with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=ok_df):
            results = await probe_akshare_health()
        assert results == {
            "fund_nav_history": "ok",
            "fund_holdings": "ok",
            "index_daily": "ok",
        }

    async def test_empty_df_probe_returns_empty_status(self, ok_df, empty_df):
        """When a probe returns an empty DataFrame it is reported as 'empty'."""
        call_count = 0

        async def side_effect(fn):
            nonlocal call_count
            call_count += 1
            # First call (fund_nav_history) returns empty; rest return ok
            return empty_df if call_count == 1 else ok_df

        with patch("asyncio.to_thread", side_effect=side_effect):
            results = await probe_akshare_health()

        assert results["fund_nav_history"] == "empty"
        assert results["fund_holdings"] == "ok"
        assert results["index_daily"] == "ok"

    async def test_exception_probe_returns_error_status(self, ok_df):
        """When a probe raises an exception it is reported as 'error'."""
        call_count = 0

        async def side_effect(fn):
            nonlocal call_count
            call_count += 1
            # Second call (fund_holdings) raises
            if call_count == 2:
                raise ConnectionError("network error")
            return ok_df

        with patch("asyncio.to_thread", side_effect=side_effect):
            results = await probe_akshare_health()

        assert results["fund_nav_history"] == "ok"
        assert results["fund_holdings"] == "error"
        assert results["index_daily"] == "ok"

    async def test_all_probes_fail_all_reported_as_error(self):
        """When all probes raise, all are reported as 'error'."""
        with patch("asyncio.to_thread", new_callable=AsyncMock, side_effect=RuntimeError("down")):
            results = await probe_akshare_health()
        assert all(v == "error" for v in results.values())
        assert len(results) == 3
