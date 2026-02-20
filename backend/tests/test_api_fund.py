"""Tests for fund API endpoints."""

import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.models.database import Base, get_db
from app.models.fund import Fund, FundHolding


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    async with session_factory() as session:
        # Seed data
        fund = Fund(
            fund_code="000001",
            fund_name="华夏成长",
            fund_type="混合型",
            last_nav=1.5,
            nav_date="2026-02-14",
        )
        session.add(fund)
        holding = FundHolding(
            fund_code="000001",
            stock_code="600519",
            stock_name="贵州茅台",
            holding_ratio=0.089,
            report_date="2025-12-31",
        )
        session.add(holding)
        await session.commit()

    yield

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_fund(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/fund/000001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["fund_code"] == "000001"
        assert data["fund_name"] == "华夏成长"


@pytest.mark.asyncio
async def test_get_fund_not_found(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/fund/999999")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_holdings(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/fund/000001/holdings")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["stock_code"] == "600519"


@pytest.mark.asyncio
async def test_get_estimate(db_session):
    mock_quotes = {
        "600519": {"price": 1800.0, "change_pct": 2.0, "name": "贵州茅台"},
    }
    with patch(
        "app.api.fund.market_data_service.get_stock_quotes",
        return_value=mock_quotes,
    ), patch(
        "app.api.fund.market_data_service.is_market_trading_today",
        return_value=True,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/fund/000001/estimate")
            assert resp.status_code == 200
            data = resp.json()
            assert data["fund_code"] == "000001"
            assert data["est_change_pct"] > 0
            assert "details" in data


@pytest.mark.asyncio
async def test_get_estimate_non_trading_day(db_session):
    """On non-trading days estimate returns last_nav with zero change."""
    with patch(
        "app.api.fund.market_data_service.is_market_trading_today",
        return_value=False,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/fund/000001/estimate")
            assert resp.status_code == 200
            data = resp.json()
            assert data["fund_code"] == "000001"
            assert data["est_change_pct"] == 0.0
            assert data["est_nav"] == 1.5  # equals last_nav seeded in fixture
            assert data["details"] == []
