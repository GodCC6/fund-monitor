# 基金盘中实时估值监测系统 - 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a fund real-time estimation monitoring system with Python FastAPI backend and uni-app frontend (Web + WeChat Mini Program).

**Architecture:** FastAPI backend calculates fund NAV estimates using quarterly holdings data + real-time stock quotes from akshare. In-memory cache (TTL-based dict) replaces Redis for MVP. SQLite stores fund info, holdings, and user portfolios. uni-app frontend serves both Web and WeChat Mini Program.

**Tech Stack:** Python 3.13, FastAPI, akshare, SQLite, cachetools, APScheduler, Vue3/uni-app

---

### Task 1: Project Scaffolding & Dependencies

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/__init__.py`

**Step 1: Create backend directory structure**

```bash
mkdir -p backend/app/api backend/app/models backend/app/services backend/app/tasks backend/tests
touch backend/app/__init__.py backend/app/api/__init__.py backend/app/models/__init__.py
touch backend/app/services/__init__.py backend/app/tasks/__init__.py backend/tests/__init__.py
```

**Step 2: Create requirements.txt**

Write `backend/requirements.txt`:

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
akshare>=1.14.0
sqlalchemy==2.0.36
aiosqlite==0.20.0
cachetools==5.5.1
apscheduler==3.11.0
httpx==0.28.1
pydantic==2.10.4
pytest==8.3.4
pytest-asyncio==0.25.0
pytest-httpx==0.35.0
```

**Step 3: Create config.py**

Write `backend/app/config.py`:

```python
"""Application configuration."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "fund_monitor.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

# Cache settings (in-memory, replaces Redis for MVP)
STOCK_CACHE_TTL = 60  # seconds
ESTIMATE_CACHE_TTL = 30  # seconds

# Market data settings
MARKET_DATA_INTERVAL = 30  # seconds between stock quote fetches
TRADING_START = "09:30"
TRADING_END = "15:00"

# Ensure data directory exists
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
```

**Step 4: Create minimal main.py**

Write `backend/app/main.py`:

```python
"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Fund Monitor", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
```

**Step 5: Install dependencies and verify**

```bash
cd backend && pip install -r requirements.txt
python -c "from app.main import app; print('App created:', app.title)"
```

Expected: `App created: Fund Monitor`

**Step 6: Commit**

```bash
git add backend/
git commit -m "feat: scaffold backend project with FastAPI and dependencies"
```

---

### Task 2: Database Models & Initialization

**Files:**
- Create: `backend/app/models/database.py`
- Create: `backend/app/models/fund.py`
- Create: `backend/app/models/portfolio.py`
- Create: `backend/tests/test_models.py`

**Step 1: Write failing test for database models**

Write `backend/tests/test_models.py`:

```python
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
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
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
    fund = Fund(fund_code="000001", fund_name="测试基金", fund_type="混合型", last_nav=1.5)
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
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_models.py -v
```

Expected: FAIL (modules not found)

**Step 3: Create database base**

Write `backend/app/models/database.py`:

```python
"""Database engine and session setup."""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


engine = create_async_engine(DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    """Dependency for FastAPI routes."""
    async with async_session_factory() as session:
        yield session


async def init_db():
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

**Step 4: Create Fund models**

Write `backend/app/models/fund.py`:

```python
"""Fund and FundHolding models."""

from datetime import datetime
from sqlalchemy import String, Float, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.database import Base


class Fund(Base):
    __tablename__ = "fund"

    fund_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    fund_name: Mapped[str] = mapped_column(String(100))
    fund_type: Mapped[str] = mapped_column(String(20))
    last_nav: Mapped[float | None] = mapped_column(Float, nullable=True)
    nav_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    updated_at: Mapped[str] = mapped_column(
        String(30), default=lambda: datetime.now().isoformat()
    )


class FundHolding(Base):
    __tablename__ = "fund_holding"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(10), index=True)
    stock_code: Mapped[str] = mapped_column(String(10))
    stock_name: Mapped[str] = mapped_column(String(50))
    holding_ratio: Mapped[float] = mapped_column(Float)
    report_date: Mapped[str] = mapped_column(String(10))
    updated_at: Mapped[str] = mapped_column(
        String(30), default=lambda: datetime.now().isoformat()
    )
```

**Step 5: Create Portfolio models**

Write `backend/app/models/portfolio.py`:

```python
"""Portfolio and PortfolioFund models."""

from datetime import datetime
from sqlalchemy import String, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.models.database import Base


class Portfolio(Base):
    __tablename__ = "portfolio"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[str] = mapped_column(
        String(30), default=lambda: datetime.now().isoformat()
    )


class PortfolioFund(Base):
    __tablename__ = "portfolio_fund"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, index=True)
    fund_code: Mapped[str] = mapped_column(String(10))
    shares: Mapped[float] = mapped_column(Float)
    cost_nav: Mapped[float] = mapped_column(Float)
    added_at: Mapped[str] = mapped_column(
        String(30), default=lambda: datetime.now().isoformat()
    )
```

**Step 6: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_models.py -v
```

Expected: 3 tests PASS

**Step 7: Commit**

```bash
git add backend/
git commit -m "feat: add SQLAlchemy database models for fund, holdings, and portfolio"
```

---

### Task 3: In-Memory Cache Service

**Files:**
- Create: `backend/app/services/cache.py`
- Create: `backend/tests/test_cache.py`

**Step 1: Write failing test**

Write `backend/tests/test_cache.py`:

```python
"""Tests for in-memory cache service."""

import time
import pytest
from app.services.cache import CacheService


def test_set_and_get():
    cache = CacheService(default_ttl=60)
    cache.set("key1", {"price": 100.5})
    result = cache.get("key1")
    assert result == {"price": 100.5}


def test_get_missing_key():
    cache = CacheService(default_ttl=60)
    assert cache.get("nonexistent") is None


def test_ttl_expiry():
    cache = CacheService(default_ttl=1)
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"
    time.sleep(1.1)
    assert cache.get("key1") is None


def test_custom_ttl():
    cache = CacheService(default_ttl=60)
    cache.set("key1", "value1", ttl=1)
    assert cache.get("key1") == "value1"
    time.sleep(1.1)
    assert cache.get("key1") is None


def test_delete():
    cache = CacheService(default_ttl=60)
    cache.set("key1", "value1")
    cache.delete("key1")
    assert cache.get("key1") is None


def test_clear():
    cache = CacheService(default_ttl=60)
    cache.set("key1", "v1")
    cache.set("key2", "v2")
    cache.clear()
    assert cache.get("key1") is None
    assert cache.get("key2") is None
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_cache.py -v
```

Expected: FAIL

**Step 3: Implement cache service**

Write `backend/app/services/cache.py`:

```python
"""In-memory TTL cache service (replaces Redis for MVP)."""

import time
import threading
from typing import Any


class CacheService:
    """Thread-safe in-memory cache with TTL support."""

    def __init__(self, default_ttl: int = 60):
        self._store: dict[str, tuple[Any, float]] = {}
        self._default_ttl = default_ttl
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.time() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.time() + ttl
        with self._lock:
            self._store[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# Global cache instances
stock_cache = CacheService(default_ttl=60)
estimate_cache = CacheService(default_ttl=30)
```

**Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_cache.py -v
```

Expected: 6 tests PASS

**Step 5: Commit**

```bash
git add backend/
git commit -m "feat: add in-memory TTL cache service"
```

---

### Task 4: Market Data Service (akshare Integration)

**Files:**
- Create: `backend/app/services/market_data.py`
- Create: `backend/tests/test_market_data.py`

**Step 1: Write failing test with mocked akshare**

Write `backend/tests/test_market_data.py`:

```python
"""Tests for market data service."""

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from app.services.market_data import MarketDataService


@pytest.fixture
def market_service():
    return MarketDataService()


class TestGetStockQuote:
    def test_get_single_stock_quote(self, market_service):
        mock_df = pd.DataFrame({
            "代码": ["600519"],
            "名称": ["贵州茅台"],
            "最新价": [1800.0],
            "涨跌幅": [2.5],
            "昨收": [1756.10],
        })
        with patch("app.services.market_data.ak.stock_zh_a_spot_em", return_value=mock_df):
            result = market_service.get_stock_quotes(["600519"])
            assert "600519" in result
            assert result["600519"]["price"] == 1800.0
            assert result["600519"]["change_pct"] == 2.5

    def test_get_multiple_stock_quotes(self, market_service):
        mock_df = pd.DataFrame({
            "代码": ["600519", "000858"],
            "名称": ["贵州茅台", "五粮液"],
            "最新价": [1800.0, 150.0],
            "涨跌幅": [2.5, -1.2],
            "昨收": [1756.10, 151.82],
        })
        with patch("app.services.market_data.ak.stock_zh_a_spot_em", return_value=mock_df):
            result = market_service.get_stock_quotes(["600519", "000858"])
            assert len(result) == 2
            assert result["000858"]["change_pct"] == -1.2

    def test_stock_not_found(self, market_service):
        mock_df = pd.DataFrame({
            "代码": ["600519"],
            "名称": ["贵州茅台"],
            "最新价": [1800.0],
            "涨跌幅": [2.5],
            "昨收": [1756.10],
        })
        with patch("app.services.market_data.ak.stock_zh_a_spot_em", return_value=mock_df):
            result = market_service.get_stock_quotes(["999999"])
            assert len(result) == 0


class TestGetFundHoldings:
    def test_get_fund_top_holdings(self, market_service):
        mock_df = pd.DataFrame({
            "股票代码": ["600519", "000858"],
            "股票名称": ["贵州茅台", "五粮液"],
            "占净值比例": [8.9, 6.5],
        })
        with patch("app.services.market_data.ak.fund_portfolio_hold_em", return_value=mock_df):
            result = market_service.get_fund_holdings("000001", "2025")
            assert len(result) == 2
            assert result[0]["stock_code"] == "600519"
            assert result[0]["holding_ratio"] == 0.089


class TestGetFundNav:
    def test_get_latest_nav(self, market_service):
        mock_df = pd.DataFrame({
            "净值日期": ["2026-02-14", "2026-02-13"],
            "单位净值": [1.234, 1.220],
            "累计净值": [3.456, 3.442],
        })
        with patch("app.services.market_data.ak.fund_open_fund_info_em", return_value=mock_df):
            result = market_service.get_fund_nav("000001")
            assert result["nav"] == 1.234
            assert result["nav_date"] == "2026-02-14"
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_market_data.py -v
```

Expected: FAIL

**Step 3: Implement market data service**

Write `backend/app/services/market_data.py`:

```python
"""Market data service using akshare for stock quotes and fund info."""

import logging
from typing import Any

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


class MarketDataService:
    """Fetches market data from akshare."""

    def get_stock_quotes(self, stock_codes: list[str]) -> dict[str, dict[str, Any]]:
        """Get real-time quotes for a list of stock codes.

        Returns dict mapping stock_code -> {price, change_pct, name}.
        """
        try:
            df = ak.stock_zh_a_spot_em()
            if df.empty:
                return {}

            code_set = set(stock_codes)
            filtered = df[df["代码"].isin(code_set)]

            result = {}
            for _, row in filtered.iterrows():
                code = row["代码"]
                result[code] = {
                    "price": float(row["最新价"]),
                    "change_pct": float(row["涨跌幅"]),
                    "name": row["名称"],
                }
            return result
        except Exception as e:
            logger.error(f"Failed to fetch stock quotes: {e}")
            return {}

    def get_fund_holdings(
        self, fund_code: str, year: str
    ) -> list[dict[str, Any]]:
        """Get fund top holdings from quarterly report.

        Returns list of {stock_code, stock_name, holding_ratio}.
        """
        try:
            df = ak.fund_portfolio_hold_em(symbol=fund_code, date=year)
            if df.empty:
                return []

            holdings = []
            for _, row in df.iterrows():
                holdings.append({
                    "stock_code": row["股票代码"],
                    "stock_name": row["股票名称"],
                    "holding_ratio": float(row["占净值比例"]) / 100.0,
                })
            return holdings
        except Exception as e:
            logger.error(f"Failed to fetch fund holdings for {fund_code}: {e}")
            return []

    def get_fund_nav(self, fund_code: str) -> dict[str, Any] | None:
        """Get the latest NAV for a fund.

        Returns {nav, nav_date, acc_nav} or None.
        """
        try:
            df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
            if df.empty:
                return None

            latest = df.iloc[0]
            return {
                "nav": float(latest["单位净值"]),
                "nav_date": str(latest["净值日期"]),
                "acc_nav": float(latest.get("累计净值", 0)),
            }
        except Exception as e:
            logger.error(f"Failed to fetch NAV for {fund_code}: {e}")
            return None


# Global instance
market_data_service = MarketDataService()
```

**Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_market_data.py -v
```

Expected: 5 tests PASS

**Step 5: Commit**

```bash
git add backend/
git commit -m "feat: add market data service with akshare integration"
```

---

### Task 5: Estimator Engine (Core Business Logic)

**Files:**
- Create: `backend/app/services/estimator.py`
- Create: `backend/tests/test_estimator.py`

**Step 1: Write failing test**

Write `backend/tests/test_estimator.py`:

```python
"""Tests for fund estimator engine."""

import pytest
from unittest.mock import patch, MagicMock
from app.services.estimator import FundEstimator


@pytest.fixture
def estimator():
    return FundEstimator()


class TestCalculateEstimate:
    def test_basic_estimate(self, estimator):
        """Fund with 2 holdings, both up."""
        holdings = [
            {"stock_code": "600519", "stock_name": "贵州茅台", "holding_ratio": 0.089},
            {"stock_code": "000858", "stock_name": "五粮液", "holding_ratio": 0.065},
        ]
        stock_quotes = {
            "600519": {"price": 1800.0, "change_pct": 2.0, "name": "贵州茅台"},
            "000858": {"price": 150.0, "change_pct": -1.0, "name": "五粮液"},
        }
        last_nav = 1.0

        result = estimator.calculate_estimate(holdings, stock_quotes, last_nav)

        # Expected: 0.089 * 2.0% + 0.065 * (-1.0%) = 0.178% - 0.065% = 0.113%
        expected_change_pct = 0.089 * 2.0 + 0.065 * (-1.0)
        expected_nav = last_nav * (1 + expected_change_pct / 100)

        assert abs(result["est_change_pct"] - expected_change_pct) < 0.0001
        assert abs(result["est_nav"] - expected_nav) < 0.0001
        assert result["coverage"] == pytest.approx(0.154, abs=0.001)

    def test_all_holdings_flat(self, estimator):
        """All stocks unchanged."""
        holdings = [
            {"stock_code": "600519", "stock_name": "贵州茅台", "holding_ratio": 0.089},
        ]
        stock_quotes = {
            "600519": {"price": 1800.0, "change_pct": 0.0, "name": "贵州茅台"},
        }
        result = estimator.calculate_estimate(holdings, stock_quotes, 2.0)
        assert result["est_change_pct"] == 0.0
        assert result["est_nav"] == 2.0

    def test_missing_stock_quote(self, estimator):
        """A holding stock has no quote available."""
        holdings = [
            {"stock_code": "600519", "stock_name": "贵州茅台", "holding_ratio": 0.089},
            {"stock_code": "999999", "stock_name": "已退市", "holding_ratio": 0.05},
        ]
        stock_quotes = {
            "600519": {"price": 1800.0, "change_pct": 3.0, "name": "贵州茅台"},
        }
        result = estimator.calculate_estimate(holdings, stock_quotes, 1.5)

        # Only 600519 contributes
        expected_change = 0.089 * 3.0
        assert abs(result["est_change_pct"] - expected_change) < 0.0001
        assert result["coverage"] == pytest.approx(0.089, abs=0.001)

    def test_empty_holdings(self, estimator):
        """No holdings data."""
        result = estimator.calculate_estimate([], {}, 1.0)
        assert result["est_change_pct"] == 0.0
        assert result["est_nav"] == 1.0
        assert result["coverage"] == 0.0

    def test_holding_details_in_result(self, estimator):
        """Result includes per-stock contribution details."""
        holdings = [
            {"stock_code": "600519", "stock_name": "贵州茅台", "holding_ratio": 0.089},
        ]
        stock_quotes = {
            "600519": {"price": 1800.0, "change_pct": 2.0, "name": "贵州茅台"},
        }
        result = estimator.calculate_estimate(holdings, stock_quotes, 1.0)
        assert len(result["details"]) == 1
        detail = result["details"][0]
        assert detail["stock_code"] == "600519"
        assert detail["change_pct"] == 2.0
        assert abs(detail["contribution"] - 0.089 * 2.0) < 0.0001
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_estimator.py -v
```

Expected: FAIL

**Step 3: Implement estimator**

Write `backend/app/services/estimator.py`:

```python
"""Fund NAV estimation engine.

Calculates real-time fund NAV estimates based on holdings and stock quotes.

Algorithm:
    est_change_pct = Σ (holding_ratio_i * stock_change_pct_i)
    est_nav = last_nav * (1 + est_change_pct / 100)
"""

from typing import Any


class FundEstimator:
    """Calculates fund NAV estimates from holdings and real-time stock quotes."""

    def calculate_estimate(
        self,
        holdings: list[dict[str, Any]],
        stock_quotes: dict[str, dict[str, Any]],
        last_nav: float,
    ) -> dict[str, Any]:
        """Calculate estimated NAV change for a fund.

        Args:
            holdings: List of {stock_code, stock_name, holding_ratio}.
            stock_quotes: Dict of stock_code -> {price, change_pct, name}.
            last_nav: The fund's last published NAV.

        Returns:
            {est_nav, est_change_pct, coverage, details: [{stock_code, stock_name,
             holding_ratio, change_pct, contribution}]}
        """
        est_change_pct = 0.0
        coverage = 0.0
        details = []

        for holding in holdings:
            stock_code = holding["stock_code"]
            quote = stock_quotes.get(stock_code)
            if quote is None:
                continue

            ratio = holding["holding_ratio"]
            change_pct = quote["change_pct"]
            contribution = ratio * change_pct

            est_change_pct += contribution
            coverage += ratio

            details.append({
                "stock_code": stock_code,
                "stock_name": holding["stock_name"],
                "holding_ratio": ratio,
                "price": quote["price"],
                "change_pct": change_pct,
                "contribution": contribution,
            })

        est_nav = last_nav * (1 + est_change_pct / 100)

        return {
            "est_nav": round(est_nav, 4),
            "est_change_pct": round(est_change_pct, 4),
            "coverage": round(coverage, 4),
            "last_nav": last_nav,
            "details": details,
        }


# Global instance
fund_estimator = FundEstimator()
```

**Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_estimator.py -v
```

Expected: 5 tests PASS

**Step 5: Commit**

```bash
git add backend/
git commit -m "feat: add fund NAV estimation engine with weighted holdings calculation"
```

---

### Task 6: Fund Info Service (DB CRUD)

**Files:**
- Create: `backend/app/services/fund_info.py`
- Create: `backend/tests/test_fund_info.py`

**Step 1: Write failing test**

Write `backend/tests/test_fund_info.py`:

```python
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
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
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
    await fund_service.update_holdings(db_session, "000001", holdings_data, "2025-12-31")
    holdings = await fund_service.get_holdings(db_session, "000001")
    assert len(holdings) == 2
    assert holdings[0].stock_code == "600519"


@pytest.mark.asyncio
async def test_update_holdings_replaces_old(db_session, fund_service):
    await fund_service.add_fund(db_session, "000001", "华夏成长", "混合型")

    old_data = [{"stock_code": "600519", "stock_name": "贵州茅台", "holding_ratio": 0.089}]
    await fund_service.update_holdings(db_session, "000001", old_data, "2025-09-30")

    new_data = [{"stock_code": "000858", "stock_name": "五粮液", "holding_ratio": 0.07}]
    await fund_service.update_holdings(db_session, "000001", new_data, "2025-12-31")

    holdings = await fund_service.get_holdings(db_session, "000001")
    assert len(holdings) == 1
    assert holdings[0].stock_code == "000858"
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_fund_info.py -v
```

Expected: FAIL

**Step 3: Implement fund info service**

Write `backend/app/services/fund_info.py`:

```python
"""Fund information CRUD service."""

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.fund import Fund, FundHolding


class FundInfoService:
    """Manages fund metadata and holdings in the database."""

    async def add_fund(
        self,
        session: AsyncSession,
        fund_code: str,
        fund_name: str,
        fund_type: str,
        last_nav: float | None = None,
        nav_date: str | None = None,
    ) -> Fund:
        fund = Fund(
            fund_code=fund_code,
            fund_name=fund_name,
            fund_type=fund_type,
            last_nav=last_nav,
            nav_date=nav_date,
        )
        session.add(fund)
        await session.commit()
        return fund

    async def get_fund(self, session: AsyncSession, fund_code: str) -> Fund | None:
        return await session.get(Fund, fund_code)

    async def get_all_funds(self, session: AsyncSession) -> list[Fund]:
        result = await session.execute(select(Fund))
        return list(result.scalars().all())

    async def update_nav(
        self, session: AsyncSession, fund_code: str, nav: float, nav_date: str
    ) -> None:
        fund = await session.get(Fund, fund_code)
        if fund:
            fund.last_nav = nav
            fund.nav_date = nav_date
            await session.commit()

    async def update_holdings(
        self,
        session: AsyncSession,
        fund_code: str,
        holdings_data: list[dict],
        report_date: str,
    ) -> None:
        # Delete old holdings for this fund
        await session.execute(
            delete(FundHolding).where(FundHolding.fund_code == fund_code)
        )

        # Insert new holdings
        for h in holdings_data:
            holding = FundHolding(
                fund_code=fund_code,
                stock_code=h["stock_code"],
                stock_name=h["stock_name"],
                holding_ratio=h["holding_ratio"],
                report_date=report_date,
            )
            session.add(holding)

        await session.commit()

    async def get_holdings(
        self, session: AsyncSession, fund_code: str
    ) -> list[FundHolding]:
        result = await session.execute(
            select(FundHolding).where(FundHolding.fund_code == fund_code)
        )
        return list(result.scalars().all())


fund_info_service = FundInfoService()
```

**Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_fund_info.py -v
```

Expected: 6 tests PASS

**Step 5: Commit**

```bash
git add backend/
git commit -m "feat: add fund info CRUD service"
```

---

### Task 7: Portfolio Service

**Files:**
- Create: `backend/app/services/portfolio.py`
- Create: `backend/tests/test_portfolio.py`

**Step 1: Write failing test**

Write `backend/tests/test_portfolio.py`:

```python
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
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
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
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_portfolio.py -v
```

Expected: FAIL

**Step 3: Implement portfolio service**

Write `backend/app/services/portfolio.py`:

```python
"""Portfolio management service."""

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.portfolio import Portfolio, PortfolioFund


class PortfolioService:
    """Manages user portfolios and their fund holdings."""

    async def create_portfolio(self, session: AsyncSession, name: str) -> Portfolio:
        portfolio = Portfolio(name=name)
        session.add(portfolio)
        await session.commit()
        return portfolio

    async def get_portfolio(self, session: AsyncSession, portfolio_id: int) -> Portfolio | None:
        return await session.get(Portfolio, portfolio_id)

    async def list_portfolios(self, session: AsyncSession) -> list[Portfolio]:
        result = await session.execute(select(Portfolio))
        return list(result.scalars().all())

    async def delete_portfolio(self, session: AsyncSession, portfolio_id: int) -> None:
        await session.execute(
            delete(PortfolioFund).where(PortfolioFund.portfolio_id == portfolio_id)
        )
        await session.execute(
            delete(Portfolio).where(Portfolio.id == portfolio_id)
        )
        await session.commit()

    async def add_fund(
        self,
        session: AsyncSession,
        portfolio_id: int,
        fund_code: str,
        shares: float,
        cost_nav: float,
    ) -> PortfolioFund:
        pf = PortfolioFund(
            portfolio_id=portfolio_id,
            fund_code=fund_code,
            shares=shares,
            cost_nav=cost_nav,
        )
        session.add(pf)
        await session.commit()
        return pf

    async def get_portfolio_funds(
        self, session: AsyncSession, portfolio_id: int
    ) -> list[PortfolioFund]:
        result = await session.execute(
            select(PortfolioFund).where(PortfolioFund.portfolio_id == portfolio_id)
        )
        return list(result.scalars().all())

    async def remove_fund(
        self, session: AsyncSession, portfolio_id: int, fund_code: str
    ) -> None:
        await session.execute(
            delete(PortfolioFund).where(
                PortfolioFund.portfolio_id == portfolio_id,
                PortfolioFund.fund_code == fund_code,
            )
        )
        await session.commit()


portfolio_service = PortfolioService()
```

**Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_portfolio.py -v
```

Expected: 7 tests PASS

**Step 5: Commit**

```bash
git add backend/
git commit -m "feat: add portfolio management service"
```

---

### Task 8: API Routes - Fund Endpoints

**Files:**
- Create: `backend/app/api/fund.py`
- Create: `backend/app/api/schemas.py`
- Create: `backend/tests/test_api_fund.py`
- Modify: `backend/app/main.py` (add router)

**Step 1: Write failing test**

Write `backend/app/api/schemas.py`:

```python
"""Pydantic schemas for API request/response."""

from pydantic import BaseModel


class FundResponse(BaseModel):
    fund_code: str
    fund_name: str
    fund_type: str
    last_nav: float | None = None
    nav_date: str | None = None


class FundEstimateResponse(BaseModel):
    fund_code: str
    fund_name: str
    est_nav: float
    est_change_pct: float
    last_nav: float
    coverage: float
    details: list[dict]


class HoldingResponse(BaseModel):
    stock_code: str
    stock_name: str
    holding_ratio: float
    report_date: str


class AddFundRequest(BaseModel):
    fund_code: str


class PortfolioCreateRequest(BaseModel):
    name: str


class PortfolioFundAddRequest(BaseModel):
    fund_code: str
    shares: float
    cost_nav: float


class PortfolioResponse(BaseModel):
    id: int
    name: str
    created_at: str


class PortfolioFundResponse(BaseModel):
    fund_code: str
    shares: float
    cost_nav: float


class PortfolioDetailResponse(BaseModel):
    id: int
    name: str
    created_at: str
    funds: list[PortfolioFundResponse]
    total_cost: float
    total_estimate: float
    total_profit: float
    total_profit_pct: float
```

Write `backend/tests/test_api_fund.py`:

```python
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
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/fund/000001/estimate")
            assert resp.status_code == 200
            data = resp.json()
            assert data["fund_code"] == "000001"
            assert data["est_change_pct"] > 0
            assert "details" in data
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_api_fund.py -v
```

Expected: FAIL

**Step 3: Implement fund API routes**

Write `backend/app/api/fund.py`:

```python
"""Fund API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.services.fund_info import fund_info_service
from app.services.market_data import market_data_service
from app.services.estimator import fund_estimator
from app.api.schemas import FundResponse, FundEstimateResponse, HoldingResponse

router = APIRouter(prefix="/api/fund", tags=["fund"])


@router.get("/{fund_code}", response_model=FundResponse)
async def get_fund(fund_code: str, db: AsyncSession = Depends(get_db)):
    fund = await fund_info_service.get_fund(db, fund_code)
    if fund is None:
        raise HTTPException(status_code=404, detail="Fund not found")
    return FundResponse(
        fund_code=fund.fund_code,
        fund_name=fund.fund_name,
        fund_type=fund.fund_type,
        last_nav=fund.last_nav,
        nav_date=fund.nav_date,
    )


@router.get("/{fund_code}/holdings", response_model=list[HoldingResponse])
async def get_holdings(fund_code: str, db: AsyncSession = Depends(get_db)):
    holdings = await fund_info_service.get_holdings(db, fund_code)
    return [
        HoldingResponse(
            stock_code=h.stock_code,
            stock_name=h.stock_name,
            holding_ratio=h.holding_ratio,
            report_date=h.report_date,
        )
        for h in holdings
    ]


@router.get("/{fund_code}/estimate", response_model=FundEstimateResponse)
async def get_estimate(fund_code: str, db: AsyncSession = Depends(get_db)):
    fund = await fund_info_service.get_fund(db, fund_code)
    if fund is None:
        raise HTTPException(status_code=404, detail="Fund not found")
    if fund.last_nav is None:
        raise HTTPException(status_code=400, detail="Fund NAV not available")

    holdings = await fund_info_service.get_holdings(db, fund_code)
    if not holdings:
        raise HTTPException(status_code=400, detail="No holdings data available")

    stock_codes = [h.stock_code for h in holdings]
    stock_quotes = market_data_service.get_stock_quotes(stock_codes)

    holdings_data = [
        {
            "stock_code": h.stock_code,
            "stock_name": h.stock_name,
            "holding_ratio": h.holding_ratio,
        }
        for h in holdings
    ]

    estimate = fund_estimator.calculate_estimate(
        holdings_data, stock_quotes, fund.last_nav
    )

    return FundEstimateResponse(
        fund_code=fund.fund_code,
        fund_name=fund.fund_name,
        **estimate,
    )
```

**Step 4: Update main.py to include router**

Modify `backend/app/main.py` — add after the CORS middleware:

```python
"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.models.database import init_db
from app.api.fund import router as fund_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Fund Monitor", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(fund_router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
```

**Step 5: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_api_fund.py -v
```

Expected: 4 tests PASS

**Step 6: Commit**

```bash
git add backend/
git commit -m "feat: add fund API routes with estimate endpoint"
```

---

### Task 9: API Routes - Portfolio Endpoints

**Files:**
- Create: `backend/app/api/portfolio_routes.py`
- Create: `backend/tests/test_api_portfolio.py`
- Modify: `backend/app/main.py` (add router)

**Step 1: Write failing test**

Write `backend/tests/test_api_portfolio.py`:

```python
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
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    async with session_factory() as session:
        fund = Fund(
            fund_code="000001", fund_name="华夏成长", fund_type="混合型",
            last_nav=1.5, nav_date="2026-02-14",
        )
        session.add(fund)
        holding = FundHolding(
            fund_code="000001", stock_code="600519", stock_name="贵州茅台",
            holding_ratio=0.089, report_date="2025-12-31",
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
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_api_portfolio.py -v
```

Expected: FAIL

**Step 3: Implement portfolio API routes**

Write `backend/app/api/portfolio_routes.py`:

```python
"""Portfolio API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.services.portfolio import portfolio_service
from app.services.fund_info import fund_info_service
from app.services.market_data import market_data_service
from app.services.estimator import fund_estimator
from app.api.schemas import (
    PortfolioCreateRequest,
    PortfolioFundAddRequest,
    PortfolioResponse,
    PortfolioDetailResponse,
    PortfolioFundResponse,
)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.post("", response_model=PortfolioResponse)
async def create_portfolio(req: PortfolioCreateRequest, db: AsyncSession = Depends(get_db)):
    p = await portfolio_service.create_portfolio(db, req.name)
    return PortfolioResponse(id=p.id, name=p.name, created_at=p.created_at)


@router.get("", response_model=list[PortfolioResponse])
async def list_portfolios(db: AsyncSession = Depends(get_db)):
    portfolios = await portfolio_service.list_portfolios(db)
    return [
        PortfolioResponse(id=p.id, name=p.name, created_at=p.created_at)
        for p in portfolios
    ]


@router.get("/{portfolio_id}", response_model=PortfolioDetailResponse)
async def get_portfolio_detail(portfolio_id: int, db: AsyncSession = Depends(get_db)):
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    pf_list = await portfolio_service.get_portfolio_funds(db, portfolio_id)

    total_cost = 0.0
    total_estimate = 0.0
    funds_response = []

    for pf in pf_list:
        fund = await fund_info_service.get_fund(db, pf.fund_code)
        est_nav = fund.last_nav if fund and fund.last_nav else 0.0

        # Try to get real-time estimate
        if fund and fund.last_nav:
            holdings = await fund_info_service.get_holdings(db, pf.fund_code)
            if holdings:
                stock_codes = [h.stock_code for h in holdings]
                quotes = market_data_service.get_stock_quotes(stock_codes)
                holdings_data = [
                    {
                        "stock_code": h.stock_code,
                        "stock_name": h.stock_name,
                        "holding_ratio": h.holding_ratio,
                    }
                    for h in holdings
                ]
                estimate = fund_estimator.calculate_estimate(
                    holdings_data, quotes, fund.last_nav
                )
                est_nav = estimate["est_nav"]

        cost = pf.shares * pf.cost_nav
        current_value = pf.shares * est_nav
        total_cost += cost
        total_estimate += current_value

        funds_response.append(
            PortfolioFundResponse(
                fund_code=pf.fund_code,
                shares=pf.shares,
                cost_nav=pf.cost_nav,
            )
        )

    total_profit = total_estimate - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0.0

    return PortfolioDetailResponse(
        id=portfolio.id,
        name=portfolio.name,
        created_at=portfolio.created_at,
        funds=funds_response,
        total_cost=round(total_cost, 2),
        total_estimate=round(total_estimate, 2),
        total_profit=round(total_profit, 2),
        total_profit_pct=round(total_profit_pct, 4),
    )


@router.post("/{portfolio_id}/funds")
async def add_fund_to_portfolio(
    portfolio_id: int,
    req: PortfolioFundAddRequest,
    db: AsyncSession = Depends(get_db),
):
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    pf = await portfolio_service.add_fund(
        db, portfolio_id, req.fund_code, req.shares, req.cost_nav
    )
    return {"status": "ok", "fund_code": pf.fund_code}


@router.delete("/{portfolio_id}/funds/{fund_code}")
async def remove_fund_from_portfolio(
    portfolio_id: int,
    fund_code: str,
    db: AsyncSession = Depends(get_db),
):
    await portfolio_service.remove_fund(db, portfolio_id, fund_code)
    return {"status": "ok"}
```

**Step 4: Update main.py to include portfolio router**

Modify `backend/app/main.py` — add import and include_router:

```python
"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.models.database import init_db
from app.api.fund import router as fund_router
from app.api.portfolio_routes import router as portfolio_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Fund Monitor", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(fund_router)
app.include_router(portfolio_router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
```

**Step 5: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_api_portfolio.py -v
```

Expected: 5 tests PASS

**Step 6: Run all tests**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: All tests PASS (total ~30 tests)

**Step 7: Commit**

```bash
git add backend/
git commit -m "feat: add portfolio API routes with real-time estimate calculation"
```

---

### Task 10: Background Task Scheduler

**Files:**
- Create: `backend/app/tasks/scheduler.py`
- Modify: `backend/app/main.py` (start scheduler in lifespan)

**Step 1: Implement scheduler**

Write `backend/app/tasks/scheduler.py`:

```python
"""Background task scheduler for periodic market data updates."""

import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.services.market_data import market_data_service
from app.services.cache import stock_cache
from app.services.fund_info import fund_info_service
from app.models.database import async_session_factory
from app.config import MARKET_DATA_INTERVAL

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def is_trading_hours() -> bool:
    """Check if current time is within A-share trading hours."""
    now = datetime.now()
    # Skip weekends
    if now.weekday() >= 5:
        return False
    current_time = now.strftime("%H:%M")
    # Morning: 09:30-11:30, Afternoon: 13:00-15:00
    return ("09:25" <= current_time <= "11:35") or ("12:55" <= current_time <= "15:05")


async def update_stock_quotes():
    """Fetch and cache real-time stock quotes for all tracked funds."""
    if not is_trading_hours():
        return

    try:
        async with async_session_factory() as session:
            funds = await fund_info_service.get_all_funds(session)
            all_stock_codes = set()
            for fund in funds:
                holdings = await fund_info_service.get_holdings(session, fund.fund_code)
                for h in holdings:
                    all_stock_codes.add(h.stock_code)

        if not all_stock_codes:
            return

        quotes = market_data_service.get_stock_quotes(list(all_stock_codes))
        for code, quote in quotes.items():
            stock_cache.set(f"stock:{code}", quote)

        logger.info(f"Updated {len(quotes)} stock quotes")
    except Exception as e:
        logger.error(f"Failed to update stock quotes: {e}")


def start_scheduler():
    """Start the background scheduler."""
    scheduler.add_job(
        update_stock_quotes,
        trigger=IntervalTrigger(seconds=MARKET_DATA_INTERVAL),
        id="update_stock_quotes",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started, updating every {MARKET_DATA_INTERVAL}s")


def stop_scheduler():
    """Stop the background scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
```

**Step 2: Update main.py to include scheduler**

Modify `backend/app/main.py`:

```python
"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.models.database import init_db
from app.api.fund import router as fund_router
from app.api.portfolio_routes import router as portfolio_router
from app.tasks.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Fund Monitor", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(fund_router)
app.include_router(portfolio_router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
```

**Step 3: Verify all tests still pass**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: All tests PASS

**Step 4: Commit**

```bash
git add backend/
git commit -m "feat: add background scheduler for periodic stock quote updates"
```

---

### Task 11: Fund Search & Auto-Setup Endpoint

**Files:**
- Create: `backend/app/api/search.py`
- Modify: `backend/app/main.py` (add router)

**Step 1: Implement fund search and auto-setup**

Write `backend/app/api/search.py`:

```python
"""Fund search and setup endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.services.fund_info import fund_info_service
from app.services.market_data import market_data_service

router = APIRouter(prefix="/api", tags=["search"])


@router.post("/fund/setup/{fund_code}")
async def setup_fund(fund_code: str, db: AsyncSession = Depends(get_db)):
    """Fetch fund info and holdings from akshare and save to database.

    This is used when adding a new fund to track.
    """
    # Check if fund already exists
    existing = await fund_info_service.get_fund(db, fund_code)
    if existing:
        return {"status": "exists", "fund_code": fund_code, "fund_name": existing.fund_name}

    # Fetch NAV
    nav_data = market_data_service.get_fund_nav(fund_code)
    if nav_data is None:
        raise HTTPException(status_code=404, detail=f"Fund {fund_code} not found in akshare")

    # Fetch holdings (current year)
    from datetime import datetime
    year = str(datetime.now().year)
    holdings = market_data_service.get_fund_holdings(fund_code, year)

    # If no holdings for current year, try last year
    if not holdings:
        holdings = market_data_service.get_fund_holdings(fund_code, str(int(year) - 1))

    # Save fund
    fund = await fund_info_service.add_fund(
        db,
        fund_code=fund_code,
        fund_name=f"Fund-{fund_code}",  # Will be updated when we have name
        fund_type="未知",
        last_nav=nav_data["nav"],
        nav_date=nav_data["nav_date"],
    )

    # Save holdings
    if holdings:
        # Only take top 10
        top_holdings = holdings[:10]
        report_date = year + "-12-31"
        await fund_info_service.update_holdings(db, fund_code, top_holdings, report_date)

    return {
        "status": "created",
        "fund_code": fund_code,
        "nav": nav_data["nav"],
        "holdings_count": len(holdings[:10]) if holdings else 0,
    }
```

**Step 2: Update main.py**

Add to `backend/app/main.py`:

```python
from app.api.search import router as search_router
```

and:

```python
app.include_router(search_router)
```

**Step 3: Commit**

```bash
git add backend/
git commit -m "feat: add fund setup endpoint for auto-fetching fund info and holdings"
```

---

### Task 12: Frontend Scaffolding (uni-app + Vue3)

**Files:**
- Create: `frontend/` directory with uni-app project

**Step 1: Initialize uni-app project**

```bash
npx degit dcloudio/uni-preset-vue#vite-ts frontend
cd frontend && npm install
```

If `degit` fails, manually scaffold a minimal uni-app project.

**Step 2: Create API layer**

Write `frontend/src/api/index.ts`:

```typescript
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);
  return resp.json();
}

export interface FundInfo {
  fund_code: string;
  fund_name: string;
  fund_type: string;
  last_nav: number | null;
  nav_date: string | null;
}

export interface FundEstimate {
  fund_code: string;
  fund_name: string;
  est_nav: number;
  est_change_pct: number;
  last_nav: number;
  coverage: number;
  details: Array<{
    stock_code: string;
    stock_name: string;
    holding_ratio: number;
    price: number;
    change_pct: number;
    contribution: number;
  }>;
}

export interface PortfolioDetail {
  id: number;
  name: string;
  created_at: string;
  funds: Array<{ fund_code: string; shares: number; cost_nav: number }>;
  total_cost: number;
  total_estimate: number;
  total_profit: number;
  total_profit_pct: number;
}

export const api = {
  getFund: (code: string) => request<FundInfo>(`/api/fund/${code}`),
  getFundEstimate: (code: string) => request<FundEstimate>(`/api/fund/${code}/estimate`),
  listPortfolios: () => request<Array<{ id: number; name: string; created_at: string }>>('/api/portfolio'),
  createPortfolio: (name: string) => request('/api/portfolio', {
    method: 'POST', body: JSON.stringify({ name }),
  }),
  getPortfolio: (id: number) => request<PortfolioDetail>(`/api/portfolio/${id}`),
  addFundToPortfolio: (id: number, fundCode: string, shares: number, costNav: number) =>
    request(`/api/portfolio/${id}/funds`, {
      method: 'POST', body: JSON.stringify({ fund_code: fundCode, shares, cost_nav: costNav }),
    }),
  removeFundFromPortfolio: (id: number, fundCode: string) =>
    request(`/api/portfolio/${id}/funds/${fundCode}`, { method: 'DELETE' }),
  setupFund: (code: string) => request(`/api/fund/setup/${code}`, { method: 'POST' }),
};
```

**Step 3: Commit**

```bash
git add frontend/
git commit -m "feat: scaffold uni-app frontend with API layer"
```

---

### Task 13: Frontend Pages - Portfolio Overview (Index)

**NOTE:** This task and remaining frontend tasks involve building uni-app Vue3 pages. The exact file paths depend on the uni-app scaffolding result from Task 12. The key pages to implement are:

1. **Index page** (`pages/index/index.vue`) — Portfolio list with summary cards
2. **Portfolio detail** (`pages/portfolio/detail.vue`) — Fund list with real-time estimates
3. **Fund detail** (`pages/fund-detail/index.vue`) — Fund info + holdings breakdown
4. **Settings** (`pages/settings/index.vue`) — Add/remove funds and portfolios

Each page should:
- Call the API layer from Task 12
- Auto-refresh during trading hours (setInterval, 30s)
- Use red (#ff4444) for gains, green (#00c853) for losses (A-share convention)
- Label estimated values with "估" badge

**Step 1: Implement pages one by one, test in browser**
**Step 2: Commit after each page**

---

### Task 14: Integration Test & End-to-End Verification

**Files:**
- Create: `backend/tests/test_integration.py`

**Step 1: Write integration test**

Write `backend/tests/test_integration.py`:

```python
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
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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

    mock_nav_df = pd.DataFrame({
        "净值日期": ["2026-02-14"],
        "单位净值": [1.5],
        "累计净值": [3.0],
    })
    mock_holdings_df = pd.DataFrame({
        "股票代码": ["600519", "000858"],
        "股票名称": ["贵州茅台", "五粮液"],
        "占净值比例": [8.9, 6.5],
    })
    mock_stock_df = pd.DataFrame({
        "代码": ["600519", "000858"],
        "名称": ["贵州茅台", "五粮液"],
        "最新价": [1800.0, 150.0],
        "涨跌幅": [2.0, -1.0],
        "昨收": [1764.7, 151.5],
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Setup fund
        with patch("app.services.market_data.ak.fund_open_fund_info_em", return_value=mock_nav_df), \
             patch("app.services.market_data.ak.fund_portfolio_hold_em", return_value=mock_holdings_df):
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
        with patch("app.services.market_data.ak.stock_zh_a_spot_em", return_value=mock_stock_df):
            resp = await client.get("/api/fund/000001/estimate")
            assert resp.status_code == 200
            data = resp.json()
            assert data["est_change_pct"] > 0  # weighted positive
            assert len(data["details"]) == 2

        # 5. Get portfolio detail
        with patch("app.services.market_data.ak.stock_zh_a_spot_em", return_value=mock_stock_df):
            resp = await client.get(f"/api/portfolio/{portfolio_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_estimate"] > 0
            assert len(data["funds"]) == 1
```

**Step 2: Run integration test**

```bash
cd backend && python -m pytest tests/test_integration.py -v
```

Expected: PASS

**Step 3: Run all tests**

```bash
cd backend && python -m pytest tests/ -v --tb=short
```

Expected: All tests PASS

**Step 4: Commit**

```bash
git add backend/
git commit -m "test: add integration test for full fund setup to estimate flow"
```

---

### Task 15: Documentation & Run Instructions

**Files:**
- Modify: `docs/plans/2026-02-15-fund-realtime-estimate-design.md` (add run instructions section)

Add a "Quick Start" section to the design doc with:

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

**Commit:**

```bash
git add docs/
git commit -m "docs: add quick start instructions"
```
