"""Tests for fund search endpoint."""

import pytest
import pandas as pd
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models.database import get_db
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.models.database import Base
import pytest_asyncio


@pytest_asyncio.fixture
async def empty_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield
    app.dependency_overrides.clear()
    await engine.dispose()


MOCK_FUND_TABLE = pd.DataFrame({
    "基金代码": ["000001", "000002", "110022", "270002"],
    "基金简称": ["华夏成长混合", "华夏优势增长", "易方达消费行业", "广发稳健增长"],
    "基金类型": ["混合型", "股票型", "股票型", "混合型"],
})


@pytest.mark.asyncio
async def test_search_by_name(empty_db):
    with patch("app.api.search.ak.fund_name_em", return_value=MOCK_FUND_TABLE):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/search?q=华夏")
    assert resp.status_code == 200
    results = resp.json()
    codes = [r["fund_code"] for r in results]
    assert "000001" in codes
    assert "000002" in codes
    assert "110022" not in codes  # 不含"华夏"


@pytest.mark.asyncio
async def test_search_by_code(empty_db):
    with patch("app.api.search.ak.fund_name_em", return_value=MOCK_FUND_TABLE):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/search?q=1100")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["fund_code"] == "110022"


@pytest.mark.asyncio
async def test_search_returns_max_20(empty_db):
    """Results capped at 20 to avoid huge payloads."""
    big_table = pd.DataFrame({
        "基金代码": [f"{i:06d}" for i in range(100)],
        "基金简称": [f"测试基金{i}" for i in range(100)],
        "基金类型": ["混合型"] * 100,
    })
    with patch("app.api.search.ak.fund_name_em", return_value=big_table):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/search?q=测试")
    assert len(resp.json()) <= 20


@pytest.mark.asyncio
async def test_search_empty_query_returns_empty(empty_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/fund/search?q=")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_search_no_results(empty_db):
    with patch("app.api.search.ak.fund_name_em", return_value=MOCK_FUND_TABLE):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/search?q=不存在的基金名称XYZ")
    assert resp.status_code == 200
    assert resp.json() == []
