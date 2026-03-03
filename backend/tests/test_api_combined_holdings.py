"""Tests for portfolio combined holdings overlap endpoint."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.models.database import Base, get_db
from app.models.fund import Fund, FundHolding
from app.models.portfolio import Portfolio, PortfolioFund


@pytest_asyncio.fixture
async def db_two_funds():
    """Two funds both holding 茅台, one also holding 五粮液."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = override

    async with factory() as s:
        # Fund A: 7% 茅台, 2% 五粮液
        s.add(Fund(fund_code="000001", fund_name="基金A", fund_type="股票型",
                   last_nav=2.0, nav_date="2026-02-17"))
        s.add(FundHolding(fund_code="000001", stock_code="600519",
                          stock_name="贵州茅台", holding_ratio=0.07, report_date="2025-12-31"))
        s.add(FundHolding(fund_code="000001", stock_code="000858",
                          stock_name="五粮液", holding_ratio=0.02, report_date="2025-12-31"))

        # Fund B: 6% 茅台
        s.add(Fund(fund_code="000002", fund_name="基金B", fund_type="股票型",
                   last_nav=1.5, nav_date="2026-02-17"))
        s.add(FundHolding(fund_code="000002", stock_code="600519",
                          stock_name="贵州茅台", holding_ratio=0.06, report_date="2025-12-31"))

        # Portfolio: 1000 shares of A (value=2000), 2000 shares of B (value=3000)
        s.add(Portfolio(id=1, name="测试组合"))
        s.add(PortfolioFund(portfolio_id=1, fund_code="000001", shares=1000.0, cost_nav=1.8))
        s.add(PortfolioFund(portfolio_id=1, fund_code="000002", shares=2000.0, cost_nav=1.4))
        await s.commit()

    yield

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_combined_holdings_endpoint_exists(db_two_funds):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/1/combined-holdings")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_combined_holdings_merges_same_stock(db_two_funds):
    """茅台 should appear once with combined weight from both funds."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/1/combined-holdings")
    holdings = resp.json()["holdings"]
    codes = [h["stock_code"] for h in holdings]
    assert codes.count("600519") == 1  # merged into one entry


@pytest.mark.asyncio
async def test_combined_holdings_weight_calculation(db_two_funds):
    """
    Portfolio total value = 1000*2.0 + 2000*1.5 = 5000
    Fund A weight = 2000/5000 = 0.4
    Fund B weight = 3000/5000 = 0.6
    茅台 combined = 0.07*0.4 + 0.06*0.6 = 0.028 + 0.036 = 0.064
    五粮液 combined = 0.02*0.4 = 0.008
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/1/combined-holdings")
    holdings = {h["stock_code"]: h for h in resp.json()["holdings"]}
    assert abs(holdings["600519"]["combined_weight"] - 0.064) < 0.001
    assert abs(holdings["000858"]["combined_weight"] - 0.008) < 0.001


@pytest.mark.asyncio
async def test_combined_holdings_sorted_by_weight(db_two_funds):
    """Holdings should be sorted by combined_weight descending."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/1/combined-holdings")
    weights = [h["combined_weight"] for h in resp.json()["holdings"]]
    assert weights == sorted(weights, reverse=True)


@pytest.mark.asyncio
async def test_combined_holdings_not_found():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/999/combined-holdings")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_combined_holdings_by_fund_details(db_two_funds):
    """茅台 should have contributions from both funds in by_fund."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/1/combined-holdings")
    holdings = {h["stock_code"]: h for h in resp.json()["holdings"]}
    moutai = holdings["600519"]
    fund_codes = [f["fund_code"] for f in moutai["by_fund"]]
    assert "000001" in fund_codes
    assert "000002" in fund_codes
