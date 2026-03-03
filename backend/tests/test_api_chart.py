"""Tests for chart API endpoints (B8).

Covers:
- GET /api/fund/index/history          — index historical data
- GET /api/fund/index/intraday         — index intraday data
- GET /api/fund/{code}/nav-history     — fund NAV history
- GET /api/fund/{code}/intraday 404    — fund not found (complements
                                         test_api_chart_intraday.py which
                                         tests the happy-path scenarios)
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.models.database import Base, get_db
from app.models.fund import Fund

_FUND_CODE = "000001"
_CST = timezone(timedelta(hours=8))


@pytest.fixture
async def db_with_fund():
    """DB seeded with one fund (no snapshots)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = override

    async with factory() as s:
        s.add(Fund(
            fund_code=_FUND_CODE,
            fund_name="华夏成长",
            fund_type="混合型",
            last_nav=2.5376,
            nav_date="2026-01-01",
        ))
        await s.commit()

    yield

    app.dependency_overrides.clear()
    await engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# Index history — GET /api/fund/index/history
# ─────────────────────────────────────────────────────────────────────────────

async def test_index_history_returns_dates_and_values():
    """Index history endpoint returns dates, values, and name from akshare."""
    mock_df = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "close": [3000.0, 3050.0, 3100.0],
    })
    with patch("app.api.chart.ak.stock_zh_index_daily", return_value=mock_df):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/index/history?period=30d")

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "上证指数"
    assert isinstance(data["dates"], list)
    assert isinstance(data["values"], list)
    assert len(data["dates"]) == len(data["values"])


async def test_index_history_returns_empty_on_akshare_exception():
    """Index history returns empty lists when akshare raises an exception."""
    with patch("app.api.chart.ak.stock_zh_index_daily", side_effect=Exception("timeout")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/index/history")

    assert resp.status_code == 200
    data = resp.json()
    assert data["dates"] == []
    assert data["values"] == []
    assert data["name"] == "上证指数"


async def test_index_history_returns_empty_on_empty_dataframe():
    """Index history returns empty lists when akshare returns no rows."""
    mock_df = pd.DataFrame({"date": [], "close": []})
    with patch("app.api.chart.ak.stock_zh_index_daily", return_value=mock_df):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/index/history")

    assert resp.status_code == 200
    data = resp.json()
    assert data["dates"] == []
    assert data["values"] == []


async def test_index_history_invalid_period_returns_422():
    """Index history returns 422 Unprocessable Entity for invalid period."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/fund/index/history?period=invalid")
    assert resp.status_code == 422


async def test_index_history_7d_filters_to_last_seven_days():
    """Index history with period=7d returns only dates within the past 7 days."""
    today = date.today()
    all_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(60, -1, -1)]
    closes = [3000.0 + i for i in range(len(all_dates))]
    mock_df = pd.DataFrame({"date": all_dates, "close": closes})

    with patch("app.api.chart.ak.stock_zh_index_daily", return_value=mock_df):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/index/history?period=7d")

    assert resp.status_code == 200
    data = resp.json()
    cutoff = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    assert all(d >= cutoff for d in data["dates"])
    # 7d slice must be smaller than the full 60-day dataset
    assert len(data["dates"]) < len(all_dates)


async def test_index_history_1y_returns_more_data_than_7d():
    """Index history with period=1y returns more entries than period=7d."""
    today = date.today()
    all_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(400, -1, -1)]
    closes = [3000.0 + i * 0.5 for i in range(len(all_dates))]
    mock_df = pd.DataFrame({"date": all_dates, "close": closes})

    with patch("app.api.chart.ak.stock_zh_index_daily", return_value=mock_df):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp_7d = await c.get("/api/fund/index/history?period=7d")
            resp_1y = await c.get("/api/fund/index/history?period=1y")

    assert len(resp_1y.json()["dates"]) > len(resp_7d.json()["dates"])


# ─────────────────────────────────────────────────────────────────────────────
# Index intraday — GET /api/fund/index/intraday
# ─────────────────────────────────────────────────────────────────────────────

def _eastmoney_response(today_str: str, entries: list[tuple]) -> MagicMock:
    """Build a mock East Money trends2 response."""
    trends = [f"{today_str} {t},0,{p},0,0,0,0,0" for t, p in entries]
    mock = MagicMock()
    mock.json.return_value = {"data": {"trends": trends}}
    return mock


async def test_index_intraday_returns_times_and_values():
    """Index intraday returns parsed times, values, pre_close, and name."""
    fake_now = datetime(2026, 1, 5, 10, 0, tzinfo=_CST)  # Monday
    today_str = "2026-01-05"
    mock_resp = _eastmoney_response(today_str, [("09:30", 3000.0), ("09:31", 3010.0)])

    with patch("app.api.chart.datetime") as mock_dt, \
         patch("app.api.chart._requests.get", return_value=mock_resp):
        mock_dt.now.return_value = fake_now
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/index/intraday")

    assert resp.status_code == 200
    data = resp.json()
    assert data["times"] == ["09:30", "09:31"]
    assert data["values"] == [3000.0, 3010.0]
    assert data["pre_close"] == 3000.0  # first value in list
    assert data["name"] == "上证指数"


async def test_index_intraday_returns_empty_on_request_exception():
    """Index intraday returns empty lists when HTTP request raises an exception."""
    with patch("app.api.chart._requests.get", side_effect=ConnectionError("network error")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/index/intraday")

    assert resp.status_code == 200
    data = resp.json()
    assert data["times"] == []
    assert data["values"] == []
    assert data["pre_close"] == 0
    assert data["name"] == "上证指数"


async def test_index_intraday_filters_to_todays_entries_only():
    """Index intraday skips entries whose timestamp is not for today."""
    fake_now = datetime(2026, 1, 5, 10, 0, tzinfo=_CST)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "trends": [
                "2026-01-04 14:55,0,2990.0,0,0,0,0,0",   # yesterday — must be skipped
                "2026-01-05 09:30,0,3000.0,0,0,0,0,0",   # today
                "2026-01-05 09:31,0,3010.0,0,0,0,0,0",   # today
            ]
        }
    }

    with patch("app.api.chart.datetime") as mock_dt, \
         patch("app.api.chart._requests.get", return_value=mock_resp):
        mock_dt.now.return_value = fake_now
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/index/intraday")

    assert resp.status_code == 200
    data = resp.json()
    assert data["times"] == ["09:30", "09:31"]
    assert len(data["values"]) == 2


async def test_index_intraday_empty_when_trends_list_is_empty():
    """Index intraday returns empty response when trends list is empty."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": {"trends": []}}

    with patch("app.api.chart._requests.get", return_value=mock_resp):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/index/intraday")

    assert resp.status_code == 200
    data = resp.json()
    assert data["times"] == []
    assert data["values"] == []
    assert data["pre_close"] == 0


async def test_index_intraday_skips_malformed_entries():
    """Index intraday skips entries with fewer than 3 comma-separated fields."""
    fake_now = datetime(2026, 1, 5, 10, 0, tzinfo=_CST)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "trends": [
                "2026-01-05 09:30",                       # too few fields — skipped
                "2026-01-05 09:31,0,3010.0,0,0,0,0,0",  # valid
            ]
        }
    }

    with patch("app.api.chart.datetime") as mock_dt, \
         patch("app.api.chart._requests.get", return_value=mock_resp):
        mock_dt.now.return_value = fake_now
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/index/intraday")

    assert resp.status_code == 200
    data = resp.json()
    assert data["times"] == ["09:31"]
    assert data["values"] == [3010.0]


# ─────────────────────────────────────────────────────────────────────────────
# Fund NAV history — GET /api/fund/{code}/nav-history
# ─────────────────────────────────────────────────────────────────────────────

async def test_nav_history_returns_dates_and_navs(db_with_fund):
    """Fund NAV history returns dates and navs from akshare."""
    today = date.today()
    recent_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(2, -1, -1)]
    mock_df = pd.DataFrame({
        "净值日期": recent_dates,
        "单位净值": [2.50, 2.53, 2.54],
    })
    with patch("app.api.chart.ak.fund_open_fund_info_em", return_value=mock_df):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/api/fund/{_FUND_CODE}/nav-history")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["dates"], list)
    assert isinstance(data["navs"], list)
    assert len(data["dates"]) == len(data["navs"])
    assert len(data["dates"]) > 0


async def test_nav_history_fund_not_found_returns_404():
    """Fund NAV history returns 404 when the fund code is not in the database."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/fund/{_FUND_CODE}/nav-history")
    assert resp.status_code == 404


async def test_nav_history_returns_empty_on_akshare_exception(db_with_fund):
    """Fund NAV history returns empty lists when akshare raises an exception."""
    with patch("app.api.chart.ak.fund_open_fund_info_em", side_effect=Exception("API error")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/api/fund/{_FUND_CODE}/nav-history")

    assert resp.status_code == 200
    data = resp.json()
    assert data["dates"] == []
    assert data["navs"] == []


async def test_nav_history_returns_empty_on_empty_dataframe(db_with_fund):
    """Fund NAV history returns empty lists when akshare returns no rows."""
    mock_df = pd.DataFrame({"净值日期": [], "单位净值": []})
    with patch("app.api.chart.ak.fund_open_fund_info_em", return_value=mock_df):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/api/fund/{_FUND_CODE}/nav-history")

    assert resp.status_code == 200
    data = resp.json()
    assert data["dates"] == []
    assert data["navs"] == []


async def test_nav_history_invalid_period_returns_422(db_with_fund):
    """Fund NAV history returns 422 for invalid period query parameter."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/fund/{_FUND_CODE}/nav-history?period=bad")
    assert resp.status_code == 422


async def test_nav_history_7d_returns_subset_of_full_data(db_with_fund):
    """Fund NAV history with period=7d returns fewer entries than period=1y."""
    today = date.today()
    all_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(400, -1, -1)]
    navs = [2.0 + i * 0.001 for i in range(len(all_dates))]
    mock_df = pd.DataFrame({"净值日期": all_dates, "单位净值": navs})

    with patch("app.api.chart.ak.fund_open_fund_info_em", return_value=mock_df):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp_7d = await c.get(f"/api/fund/{_FUND_CODE}/nav-history?period=7d")
            resp_1y = await c.get(f"/api/fund/{_FUND_CODE}/nav-history?period=1y")

    assert resp_7d.status_code == 200
    assert resp_1y.status_code == 200
    data_7d = resp_7d.json()
    data_1y = resp_1y.json()
    assert len(data_1y["dates"]) > len(data_7d["dates"])

    cutoff_7d = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    assert all(d >= cutoff_7d for d in data_7d["dates"])


async def test_nav_history_navs_are_floats(db_with_fund):
    """Fund NAV history navs are all valid floats, not strings."""
    today = date.today()
    recent_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, -1, -1)]
    mock_df = pd.DataFrame({
        "净值日期": recent_dates,
        "单位净值": [2.5376, 2.5500],
    })
    with patch("app.api.chart.ak.fund_open_fund_info_em", return_value=mock_df):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/api/fund/{_FUND_CODE}/nav-history")

    data = resp.json()
    for nav in data["navs"]:
        assert isinstance(nav, float)


# ─────────────────────────────────────────────────────────────────────────────
# Fund intraday — 404 case (fund not found)
# Happy-path intraday tests live in test_api_chart_intraday.py
# ─────────────────────────────────────────────────────────────────────────────

async def test_fund_intraday_fund_not_found_returns_404():
    """Fund intraday endpoint returns 404 when fund is not in the database."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/fund/{_FUND_CODE}/intraday")
    assert resp.status_code == 404
