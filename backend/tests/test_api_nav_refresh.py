"""Tests for manual NAV refresh endpoint."""

import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

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
    with patch("app.api.fund.market_data_service.get_fund_nav", return_value=mock_nav):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/fund/000001/refresh-nav")
    assert resp.status_code == 200
    data = resp.json()
    assert data["nav"] == 1.55
    assert data["nav_date"] == "2026-02-18"


@pytest.mark.asyncio
async def test_refresh_nav_fund_not_found(db_with_fund):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/fund/999999/refresh-nav")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_refresh_nav_source_unavailable(db_with_fund):
    with patch("app.api.fund.market_data_service.get_fund_nav", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/fund/000001/refresh-nav")
    assert resp.status_code == 503
