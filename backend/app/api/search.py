"""Fund search and setup endpoints."""

import logging
import time
from typing import Any

import akshare as ak
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.services.fund_info import fund_info_service
from app.services.market_data import market_data_service

logger = logging.getLogger(__name__)

# Simple in-process cache for fund name table (refreshed every hour)
_fund_name_cache: dict[str, Any] = {"data": None, "ts": 0}
_FUND_NAME_CACHE_TTL = 3600  # 1 hour


def _get_fund_name_table():
    """Return cached fund name DataFrame, refresh if stale."""
    now = time.time()
    if _fund_name_cache["data"] is None or now - _fund_name_cache["ts"] > _FUND_NAME_CACHE_TTL:
        _fund_name_cache["data"] = ak.fund_name_em()
        _fund_name_cache["ts"] = now
    return _fund_name_cache["data"]

router = APIRouter(prefix="/api", tags=["search"])


@router.post("/fund/setup/{fund_code}")
async def setup_fund(fund_code: str, db: AsyncSession = Depends(get_db)):
    """Fetch fund info and holdings from akshare and save to database.

    This is used when adding a new fund to track.
    """
    # Check if fund already exists
    existing = await fund_info_service.get_fund(db, fund_code)
    if existing:
        return {
            "status": "exists",
            "fund_code": fund_code,
            "fund_name": existing.fund_name,
        }

    # Fetch NAV
    nav_data = market_data_service.get_fund_nav(fund_code)
    if nav_data is None:
        raise HTTPException(
            status_code=404, detail=f"Fund {fund_code} not found in akshare"
        )

    # Fetch holdings (current year)
    from datetime import datetime

    year = str(datetime.now().year)
    holdings = market_data_service.get_fund_holdings(fund_code, year)

    # If no holdings for current year, try last year
    if not holdings:
        holdings = market_data_service.get_fund_holdings(fund_code, str(int(year) - 1))

    # Get fund name and type
    basic_info = market_data_service.get_fund_basic_info(fund_code)
    fund_name = basic_info["fund_name"] if basic_info else f"Fund-{fund_code}"
    fund_type = basic_info["fund_type"] if basic_info else "未知"

    # Save fund
    fund = await fund_info_service.add_fund(
        db,
        fund_code=fund_code,
        fund_name=fund_name,
        fund_type=fund_type,
        last_nav=nav_data["nav"],
        nav_date=nav_data["nav_date"],
    )

    # Save holdings
    if holdings:
        # Only take top 10
        top_holdings = holdings[:10]
        report_date = year + "-12-31"
        await fund_info_service.update_holdings(
            db, fund_code, top_holdings, report_date
        )

    return {
        "status": "created",
        "fund_code": fund_code,
        "nav": nav_data["nav"],
        "holdings_count": len(holdings[:10]) if holdings else 0,
    }


@router.get("/fund/search")
async def search_funds(q: str = ""):
    """Search funds by name or code prefix.

    Returns up to 20 matches: [{fund_code, fund_name, fund_type}].
    """
    q = q.strip()
    if not q:
        return []

    try:
        df = _get_fund_name_table()
        mask = (
            df["基金代码"].str.startswith(q)
            | df["基金简称"].str.contains(q, case=False, na=False)
        )
        matched = df[mask].head(20)
        return [
            {
                "fund_code": str(row["基金代码"]),
                "fund_name": str(row["基金简称"]),
                "fund_type": str(row["基金类型"]),
            }
            for _, row in matched.iterrows()
        ]
    except Exception as e:
        logger.error(f"Fund search failed: {e}")
        return []
