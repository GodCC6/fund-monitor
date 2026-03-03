"""Fund API routes."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import FundEstimateResponse, FundResponse, HoldingResponse
from app.models.database import get_db
from app.services.cache import stock_cache
from app.services.estimator import fund_estimator
from app.services.fund_info import fund_info_service
from app.services.market_data import market_data_service

logger = logging.getLogger(__name__)

# China Standard Time (UTC+8)
_CST = timezone(timedelta(hours=8))


def _is_trading_hours() -> bool:
    """Return True if current CST time is within A-share trading hours.

    Morning session:   09:25–11:35 CST
    Afternoon session: 12:55–15:05 CST
    """
    now = datetime.now(_CST)
    t = now.hour * 60 + now.minute  # minutes since midnight CST
    return (9 * 60 + 25 <= t <= 11 * 60 + 35) or (12 * 60 + 55 <= t <= 15 * 60 + 5)


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


@router.post("/{fund_code}/refresh-nav")
async def refresh_nav(fund_code: str, db: AsyncSession = Depends(get_db)):
    """Manually trigger NAV refresh from data source.

    Blocked during trading hours to prevent mid-session last_nav changes that
    would cause a visible jump in the intraday estimate chart.  The scheduled
    20:30 job bypasses this endpoint and updates the DB directly.
    """
    if _is_trading_hours():
        raise HTTPException(
            status_code=423,
            detail=(
                "NAV refresh is blocked during trading hours (09:25–11:35, "
                "12:55–15:05 CST). The scheduled refresh runs at 20:30."
            ),
        )

    fund = await fund_info_service.get_fund(db, fund_code)
    if fund is None:
        raise HTTPException(status_code=404, detail="Fund not found")

    nav_data = await market_data_service.get_fund_nav_async(fund_code)
    if nav_data is None:
        raise HTTPException(status_code=503, detail="NAV data source unavailable")

    await fund_info_service.update_nav(db, fund_code, nav_data["nav"], nav_data["nav_date"])
    return {"fund_code": fund_code, "nav": nav_data["nav"], "nav_date": nav_data["nav_date"]}


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

    logger.info(f'Holdings: {[h.stock_code for h in holdings]}')

    # Normalize all stock codes to 6-digit zero-padded strings to match cache keys
    stock_codes = [str(h.stock_code).zfill(6) for h in holdings]
    logger.info(f"[estimate] fund={fund_code} holdings({len(stock_codes)}): {stock_codes}")

    # Prefer scheduler-populated cache (TTL=7d) to avoid redundant HTTP calls.
    # With a long TTL the cache persists through non-trading hours and weekends,
    # so the fallback is only needed on the very first run before any scheduler write.
    stock_quotes: dict = {}
    for code in stock_codes:
        cached = stock_cache.get(f"stock:{code}")
        if cached is not None:
            stock_quotes[code] = cached

    logger.info(f'Cache hit: {len(stock_quotes)} / {len(stock_codes)}')
    logger.info(
        f"[estimate] fund={fund_code} cache hits={len(stock_quotes)}/{len(stock_codes)}"
        f" keys={list(stock_quotes.keys())}"
    )

    # Fall back to live fetch only when cache is empty AND the market has traded
    # today.  Guards against making slow paginated API calls on non-trading days
    # or when the app starts fresh before the first scheduler run on a holiday.
    if not stock_quotes:
        is_trading = await market_data_service.is_market_trading_today_async()
        logger.info(
            f"[estimate] fund={fund_code} cache empty, is_trading_today={is_trading}"
        )
        if is_trading:
            stock_quotes = await market_data_service.get_stock_quotes_async(stock_codes)
            logger.info(
                f"[estimate] fund={fund_code} live fetch returned"
                f" {len(stock_quotes)} quotes, keys={list(stock_quotes.keys())}"
            )

    logger.info(f'Fallback quotes keys: {list(stock_quotes.keys())}')
    logger.info(
        f"[estimate] fund={fund_code} final quotes({len(stock_quotes)})"
        f" keys={list(stock_quotes.keys())}"
    )

    holdings_data = [
        {
            "stock_code": str(h.stock_code).zfill(6),
            "stock_name": h.stock_name,
            "holding_ratio": h.holding_ratio,
        }
        for h in holdings
    ]

    estimate = fund_estimator.calculate_estimate(
        holdings_data, stock_quotes, fund.last_nav
    )

    degraded = len(stock_quotes) == 0
    return FundEstimateResponse(
        fund_code=fund.fund_code,
        fund_name=fund.fund_name,
        degraded=degraded,
        **estimate,
    )
