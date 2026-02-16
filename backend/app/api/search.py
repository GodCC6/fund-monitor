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
        await fund_info_service.update_holdings(
            db, fund_code, top_holdings, report_date
        )

    return {
        "status": "created",
        "fund_code": fund_code,
        "nav": nav_data["nav"],
        "holdings_count": len(holdings[:10]) if holdings else 0,
    }
