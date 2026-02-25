"""Chart data API routes."""

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.fund import FundEstimateSnapshot
from app.services.fund_info import fund_info_service
from app.services.market_data import market_data_service

# China Standard Time (UTC+8)
_CST = timezone(timedelta(hours=8))

router = APIRouter(prefix="/api/fund", tags=["chart"])


# Static path routes MUST come before parameterized /{fund_code} routes
# to avoid FastAPI matching "index" as a fund_code.


@router.get("/index/history")
async def get_index_history(
    period: str = Query("30d", pattern="^(7d|30d|ytd|1y|3y)$"),
):
    """Get CSI 300 index historical close prices via akshare."""
    import akshare as ak

    today = datetime.now(_CST)
    if period == "7d":
        cutoff = today - timedelta(days=10)
    elif period == "30d":
        cutoff = today - timedelta(days=45)
    elif period == "ytd":
        cutoff = datetime(today.year, 1, 1) - timedelta(days=5)
    elif period == "1y":
        cutoff = today - timedelta(days=400)
    elif period == "3y":
        cutoff = today - timedelta(days=365 * 3 + 30)
    else:
        cutoff = today - timedelta(days=45)

    try:
        df = ak.index_zh_a_hist(
            symbol="000300",
            period="daily",
            start_date=cutoff.strftime("%Y%m%d"),
            end_date=today.strftime("%Y%m%d"),
        )
        if df.empty:
            return {"dates": [], "values": [], "name": "沪深300"}
        dates = [str(d)[:10] for d in df["日期"].tolist()]
        values = [float(v) for v in df["收盘"].tolist()]
    except Exception:
        return {"dates": [], "values": [], "name": "沪深300"}

    # Filter to exact period cutoff
    if period == "7d":
        real_cutoff = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    elif period == "30d":
        real_cutoff = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    elif period == "ytd":
        real_cutoff = datetime(today.year, 1, 1).strftime("%Y-%m-%d")
    elif period == "1y":
        real_cutoff = (today - timedelta(days=365)).strftime("%Y-%m-%d")
    elif period == "3y":
        real_cutoff = (today - timedelta(days=365 * 3)).strftime("%Y-%m-%d")
    else:
        real_cutoff = (today - timedelta(days=30)).strftime("%Y-%m-%d")

    filtered_dates = [d for d in dates if d >= real_cutoff]
    filtered_values = [v for d, v in zip(dates, values) if d >= real_cutoff]

    return {"dates": filtered_dates, "values": filtered_values, "name": "沪深300"}


@router.get("/index/intraday")
async def get_index_intraday():
    """Get CSI 300 index intraday minute-level data via akshare."""
    import akshare as ak

    today = datetime.now(_CST)
    today_str = today.strftime("%Y-%m-%d")
    start_dt = today_str + " 09:25:00"
    end_dt = today.strftime("%Y-%m-%d %H:%M:%S")

    try:
        df = ak.index_zh_a_hist_min_em(
            symbol="000300",
            period="1",
            start_date=start_dt,
            end_date=end_dt,
        )
        if df.empty:
            return {"times": [], "values": [], "pre_close": 0, "name": "沪深300"}

        times = []
        values = []
        for _, row in df.iterrows():
            time_raw = str(row["时间"])
            # Format: "YYYY-MM-DD HH:MM:00" → extract "HH:MM"
            t = time_raw.split(" ")[1][:5] if " " in time_raw else time_raw[:5]
            try:
                val = float(row["收盘"])
            except (ValueError, TypeError):
                continue
            times.append(t)
            values.append(val)

        pre_close = values[0] if values else 0
    except Exception:
        return {"times": [], "values": [], "pre_close": 0, "name": "沪深300"}

    return {"times": times, "values": values, "pre_close": pre_close, "name": "沪深300"}


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

    today_str = datetime.now(_CST).strftime("%Y-%m-%d")

    # Find the most recent snapshot date so non-trading days fall back to last
    # trading day's data instead of returning empty.
    date_result = await db.execute(
        select(FundEstimateSnapshot.snapshot_date)
        .where(FundEstimateSnapshot.fund_code == fund_code)
        .order_by(FundEstimateSnapshot.snapshot_date.desc())
        .limit(1)
    )
    query_date = date_result.scalar() or today_str

    result = await db.execute(
        select(FundEstimateSnapshot)
        .where(
            FundEstimateSnapshot.fund_code == fund_code,
            FundEstimateSnapshot.snapshot_date == query_date,
        )
        .order_by(FundEstimateSnapshot.snapshot_time)
    )
    snapshots = result.scalars().all()

    times = [s.snapshot_time for s in snapshots]
    navs = [s.est_nav for s in snapshots]

    return {
        "date": query_date,
        "last_nav": fund.last_nav,
        "times": times,
        "navs": navs,
    }
