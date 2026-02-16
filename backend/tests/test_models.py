"""Tests for database models."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.models.database import Base
from app.models.fund import Fund, FundHolding
from app.models.portfolio import Portfolio, PortfolioFund


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_fund(db_session):
    fund = Fund(
        fund_code="000001",
        fund_name="华夏成长混合",
        fund_type="混合型",
        last_nav=1.234,
        nav_date="2026-02-14",
    )
    db_session.add(fund)
    await db_session.commit()

    result = await db_session.get(Fund, "000001")
    assert result is not None
    assert result.fund_name == "华夏成长混合"
    assert result.last_nav == 1.234


@pytest.mark.asyncio
async def test_create_fund_holding(db_session):
    fund = Fund(fund_code="000001", fund_name="测试基金", fund_type="股票型")
    db_session.add(fund)
    await db_session.commit()

    holding = FundHolding(
        fund_code="000001",
        stock_code="600519",
        stock_name="贵州茅台",
        holding_ratio=0.089,
        report_date="2025-12-31",
    )
    db_session.add(holding)
    await db_session.commit()

    assert holding.id is not None
    assert holding.holding_ratio == 0.089


@pytest.mark.asyncio
async def test_create_portfolio_with_funds(db_session):
    fund = Fund(
        fund_code="000001", fund_name="测试基金", fund_type="混合型", last_nav=1.5
    )
    db_session.add(fund)
    await db_session.commit()

    portfolio = Portfolio(name="我的组合")
    db_session.add(portfolio)
    await db_session.commit()

    pf = PortfolioFund(
        portfolio_id=portfolio.id,
        fund_code="000001",
        shares=1000.0,
        cost_nav=1.45,
    )
    db_session.add(pf)
    await db_session.commit()

    assert pf.id is not None
    assert pf.shares == 1000.0
