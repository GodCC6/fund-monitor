"""Portfolio API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.services.portfolio import portfolio_service
from app.services.fund_info import fund_info_service
from app.services.market_data import market_data_service
from app.services.estimator import fund_estimator
from app.api.schemas import (
    PortfolioCreateRequest,
    PortfolioFundAddRequest,
    PortfolioResponse,
    PortfolioDetailResponse,
    PortfolioFundResponse,
)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.post("", response_model=PortfolioResponse)
async def create_portfolio(
    req: PortfolioCreateRequest, db: AsyncSession = Depends(get_db)
):
    p = await portfolio_service.create_portfolio(db, req.name)
    return PortfolioResponse(id=p.id, name=p.name, created_at=p.created_at)


@router.get("", response_model=list[PortfolioResponse])
async def list_portfolios(db: AsyncSession = Depends(get_db)):
    portfolios = await portfolio_service.list_portfolios(db)
    return [
        PortfolioResponse(id=p.id, name=p.name, created_at=p.created_at)
        for p in portfolios
    ]


@router.get("/{portfolio_id}", response_model=PortfolioDetailResponse)
async def get_portfolio_detail(portfolio_id: int, db: AsyncSession = Depends(get_db)):
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    pf_list = await portfolio_service.get_portfolio_funds(db, portfolio_id)

    total_cost = 0.0
    total_estimate = 0.0
    funds_response = []

    for pf in pf_list:
        fund = await fund_info_service.get_fund(db, pf.fund_code)
        last_nav = fund.last_nav if fund and fund.last_nav else 0.0
        fund_name = fund.fund_name if fund else pf.fund_code
        est_nav = last_nav
        est_change_pct = 0.0
        coverage = 0.0
        holdings_date: str | None = None

        # Try real-time estimate
        if fund and fund.last_nav:
            holdings = await fund_info_service.get_holdings(db, pf.fund_code)
            if holdings:
                holdings_date = holdings[0].report_date
                stock_codes = [h.stock_code for h in holdings]
                quotes = market_data_service.get_stock_quotes(stock_codes)
                holdings_data = [
                    {
                        "stock_code": h.stock_code,
                        "stock_name": h.stock_name,
                        "holding_ratio": h.holding_ratio,
                    }
                    for h in holdings
                ]
                estimate = fund_estimator.calculate_estimate(
                    holdings_data, quotes, fund.last_nav
                )
                est_nav = estimate["est_nav"]
                est_change_pct = estimate["est_change_pct"]
                coverage = estimate["coverage"]

        cost = pf.shares * pf.cost_nav
        current_value = pf.shares * est_nav
        profit = current_value - cost
        profit_pct = (profit / cost * 100) if cost > 0 else 0.0
        total_cost += cost
        total_estimate += current_value

        funds_response.append(
            PortfolioFundResponse(
                fund_code=pf.fund_code,
                fund_name=fund_name,
                shares=pf.shares,
                cost_nav=pf.cost_nav,
                est_nav=round(est_nav, 4),
                est_change_pct=round(est_change_pct, 4),
                cost=round(cost, 2),
                current_value=round(current_value, 2),
                profit=round(profit, 2),
                profit_pct=round(profit_pct, 4),
                coverage=round(coverage, 4),
                holdings_date=holdings_date,
            )
        )

    total_profit = total_estimate - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0.0

    return PortfolioDetailResponse(
        id=portfolio.id,
        name=portfolio.name,
        created_at=portfolio.created_at,
        funds=funds_response,
        total_cost=round(total_cost, 2),
        total_estimate=round(total_estimate, 2),
        total_profit=round(total_profit, 2),
        total_profit_pct=round(total_profit_pct, 4),
    )


@router.post("/{portfolio_id}/funds")
async def add_fund_to_portfolio(
    portfolio_id: int,
    req: PortfolioFundAddRequest,
    db: AsyncSession = Depends(get_db),
):
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    pf = await portfolio_service.add_fund(
        db, portfolio_id, req.fund_code, req.shares, req.cost_nav
    )
    return {"status": "ok", "fund_code": pf.fund_code}


@router.delete("/{portfolio_id}/funds/{fund_code}")
async def remove_fund_from_portfolio(
    portfolio_id: int,
    fund_code: str,
    db: AsyncSession = Depends(get_db),
):
    await portfolio_service.remove_fund(db, portfolio_id, fund_code)
    return {"status": "ok"}
