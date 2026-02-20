"""Tests for portfolio history endpoint (on-the-fly NAV computation)."""

import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.models.database import Base, get_db
from app.models.portfolio import Portfolio, PortfolioFund


@pytest_asyncio.fixture
async def db_with_portfolio():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = override

    async with factory() as s:
        s.add(Portfolio(id=1, name="测试组合"))
        # Fund 110011: 1000 shares @ cost 1.0 → cost contribution = 1000
        s.add(PortfolioFund(portfolio_id=1, fund_code="110011", shares=1000.0, cost_nav=1.0))
        # Fund 000001: 500 shares @ cost 2.0 → cost contribution = 1000
        s.add(PortfolioFund(portfolio_id=1, fund_code="000001", shares=500.0, cost_nav=2.0))
        await s.commit()

    yield

    app.dependency_overrides.clear()
    await engine.dispose()


# Mock NAV history data — dates within a typical 30-day window
MOCK_NAV_110011 = {
    "2026-02-10": 1.10,
    "2026-02-11": 1.15,
    "2026-02-12": 1.12,
    "2026-02-13": 1.18,
    "2026-02-17": 1.20,
}
MOCK_NAV_000001 = {
    "2026-02-10": 2.05,
    "2026-02-11": 2.10,
    "2026-02-12": 2.08,
    "2026-02-13": 2.15,
    "2026-02-17": 2.20,
}


def _mock_nav_history(fund_code: str) -> dict[str, float]:
    if fund_code == "110011":
        return MOCK_NAV_110011
    return MOCK_NAV_000001


@pytest.mark.asyncio
async def test_get_portfolio_history(db_with_portfolio):
    with patch(
        "app.api.portfolio_routes.market_data_service.get_fund_nav_history",
        side_effect=_mock_nav_history,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/portfolio/1/history?period=30d")

    assert resp.status_code == 200
    data = resp.json()
    assert "dates" in data
    assert "values" in data
    assert "costs" in data
    assert "profit_pcts" in data
    # 5 distinct trading dates across both mock funds
    assert len(data["dates"]) == 5


@pytest.mark.asyncio
async def test_portfolio_history_sorted_asc(db_with_portfolio):
    with patch(
        "app.api.portfolio_routes.market_data_service.get_fund_nav_history",
        side_effect=_mock_nav_history,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/portfolio/1/history?period=30d")

    dates = resp.json()["dates"]
    assert dates == sorted(dates)


@pytest.mark.asyncio
async def test_portfolio_history_value_computation(db_with_portfolio):
    """Portfolio value is correctly summed from fund NAV on each date."""
    with patch(
        "app.api.portfolio_routes.market_data_service.get_fund_nav_history",
        side_effect=_mock_nav_history,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/portfolio/1/history?period=30d")

    data = resp.json()
    idx = data["dates"].index("2026-02-10")

    # value = 1000 * 1.10 + 500 * 2.05 = 1100 + 1025 = 2125.0
    # cost  = 1000 * 1.0  + 500 * 2.0  = 1000 + 1000 = 2000.0
    # profit_pct = (2125 - 2000) / 2000 * 100 = 6.25%
    assert data["values"][idx] == 2125.0
    assert data["costs"][idx] == 2000.0
    assert abs(data["profit_pcts"][idx] - 6.25) < 0.001


@pytest.mark.asyncio
async def test_portfolio_history_not_found(db_with_portfolio):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/999/history")
    assert resp.status_code == 404
