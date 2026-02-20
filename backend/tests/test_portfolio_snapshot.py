"""Tests for PortfolioSnapshot model."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.models.database import Base
from app.models.portfolio import Portfolio, PortfolioSnapshot


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_portfolio_snapshot(db):
    p = Portfolio(name="测试组合")
    db.add(p)
    await db.commit()

    snap = PortfolioSnapshot(
        portfolio_id=p.id,
        snapshot_date="2026-02-18",
        total_value=15000.0,
        total_cost=12000.0,
    )
    db.add(snap)
    await db.commit()

    assert snap.id is not None
    assert snap.total_value == 15000.0


@pytest.mark.asyncio
async def test_snapshot_profit_pct_computed(db):
    p = Portfolio(name="测试组合")
    db.add(p)
    await db.commit()

    snap = PortfolioSnapshot(
        portfolio_id=p.id,
        snapshot_date="2026-02-18",
        total_value=13200.0,
        total_cost=12000.0,
    )
    db.add(snap)
    await db.commit()

    # profit_pct = (13200 - 12000) / 12000 * 100 = 10.0
    assert abs(snap.profit_pct - 10.0) < 0.001
