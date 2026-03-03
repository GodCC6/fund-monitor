"""Global test configuration.

Provides a safety-net fixture that ensures every async test uses an isolated
in-memory SQLite database, preventing accidental hits to the real database
file in CI environments where no SQLite file or tables exist.

Tests that need specific seed data should define their own db fixtures, which
will override app.dependency_overrides[get_db] after this autouse fixture runs.
In auto asyncio_mode (see pyproject.toml), this async autouse fixture applies
only to async tests; sync tests (test_cache, test_market_data, etc.) are
unaffected because they don't make HTTP requests and don't use get_db.
"""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.models.database import Base, get_db


@pytest.fixture(autouse=True)
async def _safe_db():
    """Safety-net: give every async test an isolated in-memory database.

    Tests with their own db fixtures will override this via
    app.dependency_overrides[get_db] after this fixture sets the default.
    Only our own override is removed on teardown; test-specific fixtures
    that called app.dependency_overrides.clear() have already handled cleanup.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override
    yield
    # Only remove our override if no test fixture has already cleared it
    if app.dependency_overrides.get(get_db) is _override:
        del app.dependency_overrides[get_db]
    await engine.dispose()
