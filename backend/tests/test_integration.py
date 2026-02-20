"""Integration test: full flow from fund setup to estimate calculation."""

import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.models.database import Base, get_db


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
    yield
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_full_flow(db_session):
    """Test: setup fund -> create portfolio -> add fund -> get estimate."""
    import pandas as pd

    mock_nav_df = pd.DataFrame(
        {
            "净值日期": ["2026-02-14"],
            "单位净值": [1.5],
            "累计净值": [3.0],
        }
    )
    mock_holdings_df = pd.DataFrame(
        {
            "股票代码": ["600519", "000858"],
            "股票名称": ["贵州茅台", "五粮液"],
            "占净值比例": [8.9, 6.5],
        }
    )
    mock_stock_df = pd.DataFrame(
        {
            "代码": ["600519", "000858"],
            "名称": ["贵州茅台", "五粮液"],
            "最新价": [1800.0, 150.0],
            "涨跌幅": [2.0, -1.0],
            "昨收": [1764.7, 151.5],
        }
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Setup fund
        with (
            patch(
                "app.services.market_data.ak.fund_open_fund_info_em",
                return_value=mock_nav_df,
            ),
            patch(
                "app.services.market_data.ak.fund_portfolio_hold_em",
                return_value=mock_holdings_df,
            ),
        ):
            resp = await client.post("/api/fund/setup/000001")
            assert resp.status_code == 200
            assert resp.json()["status"] == "created"

        # 2. Create portfolio
        resp = await client.post("/api/portfolio", json={"name": "测试组合"})
        assert resp.status_code == 200
        portfolio_id = resp.json()["id"]

        # 3. Add fund to portfolio
        resp = await client.post(
            f"/api/portfolio/{portfolio_id}/funds",
            json={"fund_code": "000001", "shares": 1000.0, "cost_nav": 1.45},
        )
        assert resp.status_code == 200

        # 4. Get estimate
        mock_quotes = {
            "600519": {"price": 1800.0, "change_pct": 2.0, "name": "贵州茅台"},
            "000858": {"price": 150.0, "change_pct": -1.0, "name": "五粮液"},
        }
        with patch(
            "app.api.fund.market_data_service.get_stock_quotes",
            return_value=mock_quotes,
        ), patch(
            "app.api.fund.market_data_service.is_market_trading_today",
            return_value=True,
        ):
            resp = await client.get("/api/fund/000001/estimate")
            assert resp.status_code == 200
            data = resp.json()
            assert data["est_change_pct"] > 0  # weighted positive
            assert len(data["details"]) == 2

        # 5. Get portfolio detail
        with patch(
            "app.api.portfolio_routes.market_data_service.get_stock_quotes",
            return_value=mock_quotes,
        ), patch(
            "app.api.portfolio_routes.market_data_service.is_market_trading_today",
            return_value=True,
        ):
            resp = await client.get(f"/api/portfolio/{portfolio_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_estimate"] > 0
            assert len(data["funds"]) == 1
