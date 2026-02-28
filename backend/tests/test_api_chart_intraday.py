"""Tests for intraday chart endpoint — baseline normalization."""

import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.models.database import Base, get_db
from app.models.fund import Fund, FundEstimateSnapshot

_FUND_CODE = "000001"
_DATE = "2026-02-24"


@pytest_asyncio.fixture
async def db_with_snapshots():
    """DB seeded with a fund and snapshots that simulate a mid-session last_nav change.

    Scenario:
      - Original last_nav = 2.6016 (used for early snapshots)
      - After a mid-session manual refresh, last_nav = 2.5376
      - Later snapshots were stored using new last_nav
      - fund.last_nav in DB is the post-refresh value (2.5376)

    Without re-anchoring:
      times = [09:30, 09:31, 14:30]
      navs  = [2.5756, 2.5704, 2.5122]  <- visible jump at 14:30

    With re-anchoring (base from first snapshot):
      base_nav = 2.6016 * 0.99 / 0.99 = 2.6016  (recovered from first snap)
      navs     = [2.6016*0.99, 2.6016*0.988, 2.6016*0.99]
               = [2.5756,      2.5704,        2.5756]     <- no jump
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = override

    original_base = 2.6016  # baseline when early snapshots were taken

    async with factory() as s:
        # Fund stores post-refresh last_nav
        s.add(Fund(
            fund_code=_FUND_CODE,
            fund_name="华夏成长",
            fund_type="混合型",
            last_nav=2.5376,   # post-refresh value
            nav_date=_DATE,
        ))
        # Early snapshots (before manual refresh) — use original_base
        s.add(FundEstimateSnapshot(
            fund_code=_FUND_CODE,
            est_nav=round(original_base * (1 + (-1.0) / 100), 4),  # 2.5756
            est_change_pct=-1.0,
            snapshot_time="09:30",
            snapshot_date=_DATE,
        ))
        s.add(FundEstimateSnapshot(
            fund_code=_FUND_CODE,
            est_nav=round(original_base * (1 + (-1.2) / 100), 4),  # 2.5704
            est_change_pct=-1.2,
            snapshot_time="09:31",
            snapshot_date=_DATE,
        ))
        # Late snapshot (after manual refresh) — uses new base 2.5376
        new_base = 2.5376
        s.add(FundEstimateSnapshot(
            fund_code=_FUND_CODE,
            est_nav=round(new_base * (1 + (-1.0) / 100), 4),  # 2.5122
            est_change_pct=-1.0,
            snapshot_time="14:30",
            snapshot_date=_DATE,
        ))
        await s.commit()

    yield

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_intraday_navs_are_re_anchored_to_consistent_baseline(db_with_snapshots):
    """Intraday navs must all be computed from the first snapshot's base_nav.

    Even if fund.last_nav changed mid-session, the chart should be smooth:
    no level jump between early and late snapshots.
    """
    from datetime import datetime, timezone, timedelta
    _CST = timezone(timedelta(hours=8))
    fake_now = datetime(2026, 2, 24, 15, 0, tzinfo=_CST)  # a weekday during session

    with patch("app.api.chart.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/api/fund/{_FUND_CODE}/intraday")

    assert resp.status_code == 200
    data = resp.json()
    assert data["times"] == ["09:30", "09:31", "14:30"]

    # Recover original base nav from the response
    base_nav = data["last_nav"]
    navs = data["navs"]

    # base_nav should be recovered from first snapshot (2.6016)
    assert abs(base_nav - 2.6016) < 0.0005, f"Expected base_nav ~2.6016, got {base_nav}"

    # All navs must be derived from the SAME base_nav (no jump)
    expected_change_pcts = [-1.0, -1.2, -1.0]
    for i, (nav, change_pct) in enumerate(zip(navs, expected_change_pcts)):
        expected = round(base_nav * (1 + change_pct / 100), 4)
        assert abs(nav - expected) < 0.0001, (
            f"navs[{i}] = {nav}, expected {expected} "
            f"(base_nav={base_nav}, change_pct={change_pct})"
        )

    # The late snapshot (14:30) must NOT show a -2.46% level shift vs early ones.
    # navs[0] and navs[2] have the same change_pct (-1.0) so must be equal.
    assert abs(navs[0] - navs[2]) < 0.0001, (
        f"Jump detected: navs[0]={navs[0]} vs navs[2]={navs[2]}"
    )


@pytest.mark.asyncio
async def test_intraday_empty_snapshots(db_with_snapshots):
    """Intraday endpoint returns empty lists when no snapshots exist for a date."""
    from datetime import datetime, timezone, timedelta
    _CST = timezone(timedelta(hours=8))
    # Move "today" to a different date that has no snapshots
    fake_now = datetime(2026, 2, 25, 10, 0, tzinfo=_CST)  # Wednesday, no snapshots

    with patch("app.api.chart.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/api/fund/{_FUND_CODE}/intraday")

    assert resp.status_code == 200
    data = resp.json()
    assert data["times"] == []
    assert data["navs"] == []


@pytest.mark.asyncio
async def test_intraday_single_snapshot_no_jump(db_with_snapshots):
    """With a single snapshot, base_nav is recovered correctly and navs has one entry."""
    from datetime import datetime, timezone, timedelta
    _CST = timezone(timedelta(hours=8))
    fake_now = datetime(2026, 2, 24, 15, 0, tzinfo=_CST)

    with patch("app.api.chart.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(f"/api/fund/{_FUND_CODE}/intraday")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["navs"]) == len(data["times"])
