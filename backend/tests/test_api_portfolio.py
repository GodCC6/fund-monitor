"""Tests for portfolio API endpoints."""

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
async def test_create_portfolio(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/portfolio", json={"name": "我的组合"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "我的组合"
        assert "id" in data


@pytest.mark.asyncio
async def test_list_portfolios(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/portfolio", json={"name": "组合A"})
        await client.post("/api/portfolio", json={"name": "组合B"})
        resp = await client.get("/api/portfolio")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_add_fund_to_portfolio(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]

        resp = await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 1000.0, "cost_nav": 1.45},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_portfolio_detail(db_session):
    mock_quotes = {"600519": {"price": 1800.0, "change_pct": 2.0, "name": "贵州茅台"}}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]
        await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 1000.0, "cost_nav": 1.45},
        )

        with patch(
            "app.api.portfolio_routes.market_data_service.get_stock_quotes",
            return_value=mock_quotes,
        ):
            resp = await client.get(f"/api/portfolio/{pid}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == "组合A"
            assert len(data["funds"]) == 1
            assert "total_estimate" in data


@pytest.mark.asyncio
async def test_remove_fund_from_portfolio(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]
        await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 1000.0, "cost_nav": 1.45},
        )

        resp = await client.delete(f"/api/portfolio/{pid}/funds/000001")
        assert resp.status_code == 200
