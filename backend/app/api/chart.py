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
    """Get CSI 300 index historical close prices via akshare (Sina source)."""
    import akshare as ak

    today = datetime.now(_CST)

    # Determine cutoff date for filtering
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

    try:
        # Use Sina-based daily data (push2his.eastmoney.com kline endpoint is blocked)
        df = ak.stock_zh_index_daily(symbol="sh000300")
        if df.empty:
            return {"dates": [], "values": [], "name": "沪深300"}
        # Columns: date, open, high, low, close, volume
        dates = [str(d)[:10] for d in df["date"].tolist()]
        values = [float(v) for v in df["close"].tolist()]
    except Exception:
        return {"dates": [], "values": [], "name": "沪深300"}

    filtered_dates = [d for d in dates if d >= real_cutoff]
    filtered_values = [v for d, v in zip(dates, values) if d >= real_cutoff]

    return {"dates": filtered_dates, "values": filtered_values, "name": "沪深300"}


@router.get("/index/intraday")
async def get_index_intraday():
    """Get CSI 300 index intraday minute-level data via direct East Money API.

    Uses push2his.eastmoney.com/api/qt/stock/trends2/get directly instead of
    akshare, because akshare's index_zh_a_hist_min_em calls index_code_id_map_em()
    first which hits a blocked East Money endpoint on this server.
    """
    import requests as _requests

    today = datetime.now(_CST)
    today_str = today.strftime("%Y-%m-%d")

    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://finance.eastmoney.com/",
    }

    try:
        resp = _requests.get(
            "https://push2his.eastmoney.com/api/qt/stock/trends2/get",
            params={
                "secid": "1.000300",
                "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
                "iscr": "0",
                "ndays": "1",
            },
            headers=_HEADERS,
            timeout=10,
        )
        data = resp.json()
        raw_trends = (data.get("data") or {}).get("trends", [])
        if not raw_trends:
            return {"times": [], "values": [], "pre_close": 0, "name": "沪深300"}

        times = []
        values = []
        for entry in raw_trends:
            parts = entry.split(",")
            if len(parts) < 3:
                continue
            # parts[0]: "YYYY-MM-DD HH:MM", parts[2]: close price
            dt_str = parts[0]
            if not dt_str.startswith(today_str):
                continue  # skip data from other days
            t = dt_str.split(" ")[1][:5]  # "HH:MM"
            try:
                val = float(parts[2])
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
    today = datetime.now(_CST)
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

    now_cst = datetime.now(_CST)
    today_str = now_cst.strftime("%Y-%m-%d")
    is_weekday = now_cst.weekday() < 5  # Mon-Fri

    if is_weekday:
        # On trading days only show today's snapshots; don't fall back to a
        # previous day so that stale data never gets paired with today's index.
        query_date = today_str
    else:
        # On weekends fall back to the most recent trading day with snapshots.
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
        .order_by(FundEstimateSnapshot.snapshot_time, FundEstimateSnapshot.id)
    )
    snapshots = result.scalars().all()

    # Deduplicate by time: keep the last snapshot per HH:MM (highest id wins
    # since snapshots are ordered by time then id ascending).
    seen: dict[str, tuple[str, float]] = {}
    for s in snapshots:
        seen[s.snapshot_time] = (s.snapshot_time, s.est_nav)
    deduped = sorted(seen.values(), key=lambda x: x[0])

    times = [t for t, _ in deduped]
    navs = [n for _, n in deduped]

    # Compute the base nav that was used when the snapshots were saved.
    # The first snapshot's est_nav was calculated as last_nav*(1+change/100),
    # so base_nav = est_nav / (1 + est_change_pct/100).  Using this as
    # last_nav in the response anchors the frontend correctly and avoids a
    # visible jump when fund.last_nav has since been refreshed.
    base_nav = fund.last_nav
    if snapshots:
        first = snapshots[0]
        denom = 1.0 + first.est_change_pct / 100.0
        if denom != 0:
            base_nav = round(first.est_nav / denom, 4)

    return {
        "date": query_date,
        "last_nav": base_nav,
        "times": times,
        "navs": navs,
    }
