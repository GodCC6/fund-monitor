"""Tests for portfolio API endpoints."""

from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


@pytest.mark.asyncio
async def test_add_fund_invalid_shares_zero(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]

        resp = await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 0, "cost_nav": 1.45},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "shares must be greater than 0"


@pytest.mark.asyncio
async def test_add_fund_invalid_shares_negative(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]

        resp = await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": -100, "cost_nav": 1.45},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "shares must be greater than 0"


@pytest.mark.asyncio
async def test_add_fund_invalid_cost_nav_zero(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]

        resp = await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 1000.0, "cost_nav": 0},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "cost_nav must be greater than 0"


@pytest.mark.asyncio
async def test_add_fund_invalid_cost_nav_negative(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]

        resp = await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 1000.0, "cost_nav": -1.5},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "cost_nav must be greater than 0"


@pytest.mark.asyncio
async def test_add_fund_duplicate_rejected(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]

        resp1 = await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 1000.0, "cost_nav": 1.45},
        )
        assert resp1.status_code == 200

        resp2 = await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 500.0, "cost_nav": 1.50},
        )
        assert resp2.status_code == 409
        assert resp2.json()["detail"] == "Fund already in portfolio"


@pytest.mark.asyncio
async def test_add_different_funds_allowed(db_session):
    """Two different fund codes can both be added."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]

        resp1 = await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 1000.0, "cost_nav": 1.45},
        )
        assert resp1.status_code == 200

        resp2 = await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000002", "shares": 500.0, "cost_nav": 1.20},
        )
        assert resp2.status_code == 200


@pytest.mark.asyncio
async def test_delete_portfolio(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]

        resp = await client.delete(f"/api/portfolio/{pid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Verify it's gone
        list_resp = await client.get("/api/portfolio")
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 0


@pytest.mark.asyncio
async def test_delete_portfolio_not_found(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/api/portfolio/9999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Portfolio not found"


@pytest.mark.asyncio
async def test_delete_portfolio_also_removes_funds(db_session):
    """Deleting a portfolio cascades to remove its fund entries."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]
        await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 1000.0, "cost_nav": 1.45},
        )

        del_resp = await client.delete(f"/api/portfolio/{pid}")
        assert del_resp.status_code == 200

        # Getting the deleted portfolio should return 404
        get_resp = await client.get(f"/api/portfolio/{pid}")
        assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_update_fund_position(db_session):
    """PATCH updates shares and cost_nav for a fund in the portfolio."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]
        await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 1000.0, "cost_nav": 1.45},
        )

        resp = await client.patch(
            f"/api/portfolio/{pid}/funds/000001",
            json={"shares": 1500.0, "cost_nav": 1.50},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["shares"] == 1500.0
        assert data["cost_nav"] == 1.50


@pytest.mark.asyncio
async def test_update_fund_position_not_found(db_session):
    """PATCH on a fund not in the portfolio returns 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]

        resp = await client.patch(
            f"/api/portfolio/{pid}/funds/999999",
            json={"shares": 500.0, "cost_nav": 1.20},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Fund not found in portfolio"


@pytest.mark.asyncio
async def test_update_fund_position_invalid_shares(db_session):
    """PATCH rejects shares <= 0."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]
        await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 1000.0, "cost_nav": 1.45},
        )

        resp = await client.patch(
            f"/api/portfolio/{pid}/funds/000001",
            json={"shares": 0, "cost_nav": 1.50},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "shares must be greater than 0"


@pytest.mark.asyncio
async def test_update_fund_position_invalid_cost_nav(db_session):
    """PATCH rejects cost_nav <= 0."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]
        await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 1000.0, "cost_nav": 1.45},
        )

        resp = await client.patch(
            f"/api/portfolio/{pid}/funds/000001",
            json={"shares": 1000.0, "cost_nav": -1.0},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "cost_nav must be greater than 0"


@pytest.mark.asyncio
async def test_add_fund_with_purchase_date(db_session):
    """Adding a fund with purchase_date stores and returns it in portfolio detail."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]

        resp = await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 1000.0, "cost_nav": 1.45, "purchase_date": "2024-01-15"},
        )
        assert resp.status_code == 200

        detail_resp = await client.get(f"/api/portfolio/{pid}")
        assert detail_resp.status_code == 200
        funds = detail_resp.json()["funds"]
        assert len(funds) == 1
        assert funds[0]["purchase_date"] == "2024-01-15"


@pytest.mark.asyncio
async def test_add_fund_without_purchase_date_defaults_null(db_session):
    """Adding a fund without purchase_date returns purchase_date=null."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]

        await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 1000.0, "cost_nav": 1.45},
        )

        detail_resp = await client.get(f"/api/portfolio/{pid}")
        funds = detail_resp.json()["funds"]
        assert funds[0]["purchase_date"] is None
        # added_at should still be present for fallback
        assert funds[0]["added_at"] is not None


@pytest.mark.asyncio
async def test_update_fund_position_with_purchase_date(db_session):
    """PATCH can set purchase_date on an existing position."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]
        await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 1000.0, "cost_nav": 1.45},
        )

        resp = await client.patch(
            f"/api/portfolio/{pid}/funds/000001",
            json={"shares": 1500.0, "cost_nav": 1.50, "purchase_date": "2023-06-01"},
        )
        assert resp.status_code == 200
        assert resp.json()["purchase_date"] == "2023-06-01"

        detail_resp = await client.get(f"/api/portfolio/{pid}")
        funds = detail_resp.json()["funds"]
        assert funds[0]["purchase_date"] == "2023-06-01"
        assert funds[0]["shares"] == 1500.0


@pytest.mark.asyncio
async def test_update_fund_clears_purchase_date_when_null(db_session):
    """PATCH with purchase_date=null clears the purchase date."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/portfolio", json={"name": "组合A"})
        pid = create_resp.json()["id"]
        await client.post(
            f"/api/portfolio/{pid}/funds",
            json={"fund_code": "000001", "shares": 1000.0, "cost_nav": 1.45, "purchase_date": "2023-06-01"},
        )

        resp = await client.patch(
            f"/api/portfolio/{pid}/funds/000001",
            json={"shares": 1000.0, "cost_nav": 1.45, "purchase_date": None},
        )
        assert resp.status_code == 200
        assert resp.json()["purchase_date"] is None
