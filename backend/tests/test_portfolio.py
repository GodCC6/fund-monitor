"""Tests for portfolio service."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.models.database import Base
from app.models.fund import Fund
from app.models.portfolio import Portfolio, PortfolioFund
from app.services.portfolio import PortfolioService


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def portfolio_service():
    return PortfolioService()


@pytest.mark.asyncio
async def test_create_portfolio(db_session, portfolio_service):
    p = await portfolio_service.create_portfolio(db_session, "我的组合")
    assert p.id is not None
    assert p.name == "我的组合"


@pytest.mark.asyncio
async def test_get_portfolio(db_session, portfolio_service):
    created = await portfolio_service.create_portfolio(db_session, "组合A")
    fetched = await portfolio_service.get_portfolio(db_session, created.id)
    assert fetched is not None
    assert fetched.name == "组合A"


@pytest.mark.asyncio
async def test_list_portfolios(db_session, portfolio_service):
    await portfolio_service.create_portfolio(db_session, "组合A")
    await portfolio_service.create_portfolio(db_session, "组合B")
    portfolios = await portfolio_service.list_portfolios(db_session)
    assert len(portfolios) == 2


@pytest.mark.asyncio
async def test_add_fund_to_portfolio(db_session, portfolio_service):
    p = await portfolio_service.create_portfolio(db_session, "组合A")
    pf = await portfolio_service.add_fund(db_session, p.id, "000001", 1000.0, 1.5)
    assert pf.fund_code == "000001"
    assert pf.shares == 1000.0
    assert pf.cost_nav == 1.5


@pytest.mark.asyncio
async def test_get_portfolio_funds(db_session, portfolio_service):
    p = await portfolio_service.create_portfolio(db_session, "组合A")
    await portfolio_service.add_fund(db_session, p.id, "000001", 1000.0, 1.5)
    await portfolio_service.add_fund(db_session, p.id, "000002", 500.0, 2.0)
    funds = await portfolio_service.get_portfolio_funds(db_session, p.id)
    assert len(funds) == 2


@pytest.mark.asyncio
async def test_remove_fund_from_portfolio(db_session, portfolio_service):
    p = await portfolio_service.create_portfolio(db_session, "组合A")
    await portfolio_service.add_fund(db_session, p.id, "000001", 1000.0, 1.5)
    await portfolio_service.remove_fund(db_session, p.id, "000001")
    funds = await portfolio_service.get_portfolio_funds(db_session, p.id)
    assert len(funds) == 0


@pytest.mark.asyncio
async def test_delete_portfolio(db_session, portfolio_service):
    p = await portfolio_service.create_portfolio(db_session, "组合A")
    await portfolio_service.add_fund(db_session, p.id, "000001", 1000.0, 1.5)
    await portfolio_service.delete_portfolio(db_session, p.id)
    assert await portfolio_service.get_portfolio(db_session, p.id) is None
    funds = await portfolio_service.get_portfolio_funds(db_session, p.id)
    assert len(funds) == 0
