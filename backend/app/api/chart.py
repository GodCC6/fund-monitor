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


# Static path routes MUST come before parameterized /{fund_code} routes
# to avoid FastAPI matching "index" as a fund_code.


@router.get("/index/history")
async def get_index_history(
    period: str = Query("30d", pattern="^(7d|30d|ytd|1y|3y)$"),
):
    """Get CSI 300 index historical close prices."""
    import httpx as hx

    today = datetime.now()
    if period == "7d":
        cutoff = today - timedelta(days=10)  # extra days for weekends
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

    beg = cutoff.strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    try:
        # secid=1.000300 is CSI 300
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
            f"?secid=1.000300&fields1=f1,f2,f3&fields2=f51,f52"
            f"&klt=101&fqt=1&beg={beg}&end={end}"
        )
        resp = hx.get(url, timeout=10)
        data = resp.json()
        klines = data.get("data", {}).get("klines", [])
    except Exception:
        return {"dates": [], "values": []}

    # Parse klines: "date,close" — f51=date, f52=close
    dates = []
    values = []
    for k in klines:
        parts = k.split(",")
        dates.append(parts[0])
        values.append(float(parts[1]))  # close price is second field (f52)

    # Now filter to match the exact period cutoff
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

    filtered_dates = []
    filtered_values = []
    for d, v in zip(dates, values):
        if d >= real_cutoff:
            filtered_dates.append(d)
            filtered_values.append(v)

    return {"dates": filtered_dates, "values": filtered_values, "name": "沪深300"}


@router.get("/index/intraday")
async def get_index_intraday():
    """Get CSI 300 index intraday minute-level data."""
    import httpx as hx

    try:
        url = (
            "https://push2.eastmoney.com/api/qt/stock/trends2/get"
            "?secid=1.000300&fields1=f1,f2,f3&fields2=f51,f52,f53&iscr=0&ndays=1"
        )
        resp = hx.get(url, timeout=10)
        data = resp.json()
        trends = data.get("data", {}).get("trends", [])
        pre_close = data.get("data", {}).get("preClose", 0)
    except Exception:
        return {"times": [], "values": [], "name": "沪深300"}

    times = []
    values = []
    for t in trends:
        parts = t.split(",")
        # parts[0] = "2026-02-13 09:30", parts[1] = price
        time_str = parts[0].split(" ")[1] if " " in parts[0] else parts[0]
        times.append(time_str)
        values.append(float(parts[1]))

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
