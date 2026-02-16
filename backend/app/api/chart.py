"""Chart data API routes."""

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.fund import FundEstimateSnapshot
from app.services.fund_info import fund_info_service
from app.services.market_data import market_data_service

router = APIRouter(prefix="/api/fund", tags=["chart"])


@router.get("/{fund_code}/nav-history")
async def get_nav_history(
    fund_code: str,
    period: str = Query("30d", pattern="^(7d|30d|ytd|1y|3y)$"),
    db: AsyncSession = Depends(get_db),
):
    """Get historical NAV data for chart display."""
    fund = await fund_info_service.get_fund(db, fund_code)
    if fund is None:
        raise HTTPException(status_code=404, detail="Fund not found")

    # Use akshare to get historical NAV
    try:
        import akshare as ak

        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
        if df.empty:
            return {"dates": [], "navs": []}
    except Exception:
        return {"dates": [], "navs": []}

    # Convert to lists
    dates = [str(d) for d in df["净值日期"].tolist()]
    navs = [float(n) for n in df["单位净值"].tolist()]

    # Filter by period
    today = datetime.now()
    if period == "7d":
        cutoff = today - timedelta(days=7)
    elif period == "30d":
        cutoff = today - timedelta(days=30)
    elif period == "ytd":
        cutoff = datetime(today.year, 1, 1)
    elif period == "1y":
        cutoff = today - timedelta(days=365)
    elif period == "3y":
        cutoff = today - timedelta(days=365 * 3)
    else:
        cutoff = today - timedelta(days=30)

    cutoff_str = cutoff.strftime("%Y-%m-%d")
    filtered_dates = []
    filtered_navs = []
    for d, n in zip(dates, navs):
        if d >= cutoff_str:
            filtered_dates.append(d)
            filtered_navs.append(n)

    return {"dates": filtered_dates, "navs": filtered_navs}


@router.get("/{fund_code}/intraday")
async def get_intraday(
    fund_code: str,
    db: AsyncSession = Depends(get_db),
):
    """Get intraday estimate snapshots for today."""
    fund = await fund_info_service.get_fund(db, fund_code)
    if fund is None:
        raise HTTPException(status_code=404, detail="Fund not found")

    today_str = datetime.now().strftime("%Y-%m-%d")
    result = await db.execute(
        select(FundEstimateSnapshot)
        .where(
            FundEstimateSnapshot.fund_code == fund_code,
            FundEstimateSnapshot.snapshot_date == today_str,
        )
        .order_by(FundEstimateSnapshot.snapshot_time)
    )
    snapshots = result.scalars().all()

    times = [s.snapshot_time for s in snapshots]
    navs = [s.est_nav for s in snapshots]

    return {
        "date": today_str,
        "last_nav": fund.last_nav,
        "times": times,
        "navs": navs,
    }
