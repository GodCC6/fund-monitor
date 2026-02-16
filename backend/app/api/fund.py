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
