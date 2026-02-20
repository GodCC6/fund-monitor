"""Tests for portfolio history endpoint."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.models.database import Base, get_db
from app.models.portfolio import Portfolio, PortfolioSnapshot


@pytest_asyncio.fixture
async def db_with_snapshots():
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
        for date, val, cost in [
            ("2026-02-10", 12100.0, 12000.0),
            ("2026-02-11", 12200.0, 12000.0),
            ("2026-02-12", 12050.0, 12000.0),
            ("2026-02-17", 12300.0, 12000.0),
            ("2026-02-18", 12500.0, 12000.0),
        ]:
            s.add(PortfolioSnapshot(portfolio_id=1, snapshot_date=date,
                                    total_value=val, total_cost=cost))
        await s.commit()

    yield

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_portfolio_history(db_with_snapshots):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/1/history?period=30d")
    assert resp.status_code == 200
    data = resp.json()
    assert "dates" in data
    assert "values" in data
    assert "profit_pcts" in data
    assert len(data["dates"]) == 5


@pytest.mark.asyncio
async def test_portfolio_history_sorted_asc(db_with_snapshots):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/1/history?period=30d")
    dates = resp.json()["dates"]
    assert dates == sorted(dates)


@pytest.mark.asyncio
async def test_portfolio_history_not_found(db_with_snapshots):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/999/history")
    assert resp.status_code == 404
