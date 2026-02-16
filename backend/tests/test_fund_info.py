"""Tests for fund info service."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.models.database import Base
from app.models.fund import Fund, FundHolding
from app.services.fund_info import FundInfoService


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
def fund_service():
    return FundInfoService()


@pytest.mark.asyncio
async def test_add_fund(db_session, fund_service):
    fund = await fund_service.add_fund(db_session, "000001", "华夏成长", "混合型")
    assert fund.fund_code == "000001"
    assert fund.fund_name == "华夏成长"


@pytest.mark.asyncio
async def test_get_fund(db_session, fund_service):
    await fund_service.add_fund(db_session, "000001", "华夏成长", "混合型")
    fund = await fund_service.get_fund(db_session, "000001")
    assert fund is not None
    assert fund.fund_name == "华夏成长"


@pytest.mark.asyncio
async def test_get_fund_not_found(db_session, fund_service):
    fund = await fund_service.get_fund(db_session, "999999")
    assert fund is None


@pytest.mark.asyncio
async def test_update_nav(db_session, fund_service):
    await fund_service.add_fund(db_session, "000001", "华夏成长", "混合型")
    await fund_service.update_nav(db_session, "000001", 1.234, "2026-02-14")
    fund = await fund_service.get_fund(db_session, "000001")
    assert fund.last_nav == 1.234
    assert fund.nav_date == "2026-02-14"


@pytest.mark.asyncio
async def test_update_holdings(db_session, fund_service):
    await fund_service.add_fund(db_session, "000001", "华夏成长", "混合型")
    holdings_data = [
        {"stock_code": "600519", "stock_name": "贵州茅台", "holding_ratio": 0.089},
        {"stock_code": "000858", "stock_name": "五粮液", "holding_ratio": 0.065},
    ]
    await fund_service.update_holdings(
        db_session, "000001", holdings_data, "2025-12-31"
    )
    holdings = await fund_service.get_holdings(db_session, "000001")
    assert len(holdings) == 2
    assert holdings[0].stock_code == "600519"


@pytest.mark.asyncio
async def test_update_holdings_replaces_old(db_session, fund_service):
    await fund_service.add_fund(db_session, "000001", "华夏成长", "混合型")

    old_data = [
        {"stock_code": "600519", "stock_name": "贵州茅台", "holding_ratio": 0.089}
    ]
    await fund_service.update_holdings(db_session, "000001", old_data, "2025-09-30")

    new_data = [{"stock_code": "000858", "stock_name": "五粮液", "holding_ratio": 0.07}]
    await fund_service.update_holdings(db_session, "000001", new_data, "2025-12-31")

    holdings = await fund_service.get_holdings(db_session, "000001")
    assert len(holdings) == 1
    assert holdings[0].stock_code == "000858"
