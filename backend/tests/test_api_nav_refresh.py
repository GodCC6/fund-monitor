"""Tests for manual NAV refresh endpoint."""

from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.fund import _is_trading_hours
from app.main import app
from app.models.database import Base, get_db
from app.models.fund import Fund


@pytest_asyncio.fixture
async def db_with_fund():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    async with factory() as s:
        s.add(Fund(fund_code="000001", fund_name="华夏成长", fund_type="混合型",
                   last_nav=1.5, nav_date="2026-02-14"))
        await s.commit()
    yield
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_refresh_nav_updates_db(db_with_fund):
    mock_nav = {"nav": 1.55, "nav_date": "2026-02-18", "acc_nav": 3.1}
    with patch("app.api.fund._is_trading_hours", return_value=False), \
         patch("app.api.fund.market_data_service.get_fund_nav", return_value=mock_nav):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/fund/000001/refresh-nav")
    assert resp.status_code == 200
    data = resp.json()
    assert data["nav"] == 1.55
    assert data["nav_date"] == "2026-02-18"


@pytest.mark.asyncio
async def test_refresh_nav_fund_not_found(db_with_fund):
    with patch("app.api.fund._is_trading_hours", return_value=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/fund/999999/refresh-nav")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_refresh_nav_source_unavailable(db_with_fund):
    with patch("app.api.fund._is_trading_hours", return_value=False), \
         patch("app.api.fund.market_data_service.get_fund_nav", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/fund/000001/refresh-nav")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Trading-hours guard tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_nav_blocked_during_morning_session(db_with_fund):
    """refresh-nav returns 423 when called during the morning trading session."""
    with patch("app.api.fund._is_trading_hours", return_value=True):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/fund/000001/refresh-nav")
    assert resp.status_code == 423
    assert "trading hours" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_refresh_nav_allowed_outside_trading_hours(db_with_fund):
    """refresh-nav succeeds when called outside trading hours."""
    mock_nav = {"nav": 1.55, "nav_date": "2026-02-18", "acc_nav": 3.1}
    with patch("app.api.fund._is_trading_hours", return_value=False), \
         patch("app.api.fund.market_data_service.get_fund_nav", return_value=mock_nav):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/fund/000001/refresh-nav")
    assert resp.status_code == 200
    assert resp.json()["nav"] == 1.55


# ---------------------------------------------------------------------------
# _is_trading_hours unit tests
# ---------------------------------------------------------------------------

def test_is_trading_hours_morning_open():
    """09:30 CST is within trading hours."""
    from datetime import datetime, timedelta, timezone
    _CST = timezone(timedelta(hours=8))
    fake_now = datetime(2026, 2, 28, 9, 30, tzinfo=_CST)
    with patch("app.api.fund.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        assert _is_trading_hours() is True


def test_is_trading_hours_before_open():
    """09:00 CST (before opening) is NOT trading hours."""
    from datetime import datetime, timedelta, timezone
    _CST = timezone(timedelta(hours=8))
    fake_now = datetime(2026, 2, 28, 9, 0, tzinfo=_CST)
    with patch("app.api.fund.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        assert _is_trading_hours() is False


def test_is_trading_hours_afternoon_open():
    """13:00 CST is within afternoon trading hours."""
    from datetime import datetime, timedelta, timezone
    _CST = timezone(timedelta(hours=8))
    fake_now = datetime(2026, 2, 28, 13, 0, tzinfo=_CST)
    with patch("app.api.fund.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        assert _is_trading_hours() is True


def test_is_trading_hours_evening():
    """20:30 CST (scheduled refresh time) is NOT trading hours."""
    from datetime import datetime, timedelta, timezone
    _CST = timezone(timedelta(hours=8))
    fake_now = datetime(2026, 2, 28, 20, 30, tzinfo=_CST)
    with patch("app.api.fund.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        assert _is_trading_hours() is False
