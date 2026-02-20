"""Tests for portfolio fund detail display (names, per-fund P&L)."""

import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.models.database import Base, get_db
from app.models.fund import Fund, FundHolding
from app.models.portfolio import Portfolio, PortfolioFund


@pytest_asyncio.fixture
async def db_with_data():
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
                   last_nav=2.0, nav_date="2026-02-17"))
        s.add(FundHolding(fund_code="000001", stock_code="600519",
                          stock_name="贵州茅台", holding_ratio=0.1, report_date="2025-12-31"))
        s.add(Portfolio(id=1, name="测试组合"))
        s.add(PortfolioFund(portfolio_id=1, fund_code="000001", shares=1000.0, cost_nav=1.8))
        await s.commit()

    yield

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_portfolio_fund_has_name(db_with_data):
    mock_quotes = {"600519": {"price": 1900.0, "change_pct": 2.0, "name": "贵州茅台"}}
    with patch("app.api.portfolio_routes.market_data_service.get_stock_quotes",
               return_value=mock_quotes):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/portfolio/1")
    assert resp.status_code == 200
    fund = resp.json()["funds"][0]
    assert fund["fund_name"] == "华夏成长"


@pytest.mark.asyncio
async def test_portfolio_fund_has_est_change_pct(db_with_data):
    mock_quotes = {"600519": {"price": 1900.0, "change_pct": 2.0, "name": "贵州茅台"}}
    with patch("app.api.portfolio_routes.market_data_service.get_stock_quotes",
               return_value=mock_quotes), \
         patch("app.api.portfolio_routes.market_data_service.is_market_trading_today",
               return_value=True):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/portfolio/1")
    fund = resp.json()["funds"][0]
    # est_change_pct = 0.1 * 2.0 = 0.2
    assert abs(fund["est_change_pct"] - 0.2) < 0.001
    assert fund["coverage"] == pytest.approx(0.1, abs=0.001)


@pytest.mark.asyncio
async def test_portfolio_fund_profit_pct(db_with_data):
    """profit_pct = (est_nav - cost_nav) / cost_nav * 100"""
    mock_quotes = {"600519": {"price": 1900.0, "change_pct": 0.0, "name": "贵州茅台"}}
    with patch("app.api.portfolio_routes.market_data_service.get_stock_quotes",
               return_value=mock_quotes):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/portfolio/1")
    fund = resp.json()["funds"][0]
    # est_nav = last_nav = 2.0 (change_pct=0, so estimate = last_nav * (1+0/100) = 2.0)
    expected_profit_pct = (2.0 - 1.8) / 1.8 * 100
    assert abs(fund["profit_pct"] - expected_profit_pct) < 0.01


@pytest.mark.asyncio
async def test_portfolio_fund_holdings_date(db_with_data):
    mock_quotes = {}
    with patch("app.api.portfolio_routes.market_data_service.get_stock_quotes",
               return_value=mock_quotes), \
         patch("app.api.portfolio_routes.market_data_service.is_market_trading_today",
               return_value=True):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/portfolio/1")
    fund = resp.json()["funds"][0]
    assert fund["holdings_date"] == "2025-12-31"
