"""Tests for scheduler retry logic with exponential backoff."""

from unittest.mock import AsyncMock, call, patch

from app.tasks.scheduler import (
    _STOCK_FETCH_BASE_DELAY,
    _STOCK_FETCH_MAX_RETRIES,
    _fetch_quotes_with_retry,
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
