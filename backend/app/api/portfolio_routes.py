"""Portfolio API routes."""

import asyncio
import bisect
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    PortfolioCreateRequest,
    PortfolioDetailResponse,
    PortfolioFundAddRequest,
    PortfolioFundResponse,
    PortfolioFundUpdateRequest,
    PortfolioRenameRequest,
    PortfolioResponse,
)
from app.models.database import get_db
from app.services.cache import stock_cache
from app.services.estimator import fund_estimator
from app.services.fund_info import fund_info_service
from app.services.market_data import market_data_service
from app.services.portfolio import portfolio_service

_CST = timezone(timedelta(hours=8))

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

    # Batch-fetch all funds and holdings in two queries instead of N+1
    fund_codes = [pf.fund_code for pf in pf_list]
    funds_map = await fund_info_service.get_funds_by_codes(db, fund_codes)
    holdings_map = await fund_info_service.get_holdings_by_fund_codes(db, fund_codes)

    # Check trading day once — avoids redundant API calls per fund
    is_trading = await market_data_service.is_market_trading_today_async()

    total_cost = 0.0
    total_estimate = 0.0
    funds_response = []

    for pf in pf_list:
        fund = funds_map.get(pf.fund_code)
        last_nav = fund.last_nav if fund and fund.last_nav else 0.0
        fund_name = fund.fund_name if fund else pf.fund_code
        est_nav = last_nav
        est_change_pct = 0.0
        coverage = 0.0
        holdings_date: str | None = None

        # Try real-time estimate only on trading days
        if fund and fund.last_nav and is_trading:
            holdings = holdings_map.get(pf.fund_code, [])
            if holdings:
                holdings_date = holdings[0].report_date
                stock_codes = [h.stock_code for h in holdings]
                # Prefer scheduler-populated cache over redundant live HTTP calls
                quotes: dict = {}
                for _code in stock_codes:
                    _cached = stock_cache.get(f"stock:{_code}")
                    if _cached is not None:
                        quotes[_code] = _cached
                if not quotes:
                    quotes = await market_data_service.get_stock_quotes_async(stock_codes)
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
                added_at=pf.added_at,
                purchase_date=pf.purchase_date,
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


@router.delete("/{portfolio_id}")
async def delete_portfolio(portfolio_id: int, db: AsyncSession = Depends(get_db)):
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    await portfolio_service.delete_portfolio(db, portfolio_id)
    return {"status": "ok"}


@router.patch("/{portfolio_id}", response_model=PortfolioResponse)
async def rename_portfolio(
    portfolio_id: int,
    req: PortfolioRenameRequest,
    db: AsyncSession = Depends(get_db),
):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    portfolio = await portfolio_service.rename_portfolio(db, portfolio_id, name)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return PortfolioResponse(id=portfolio.id, name=portfolio.name, created_at=portfolio.created_at)


@router.post("/{portfolio_id}/funds")
async def add_fund_to_portfolio(
    portfolio_id: int,
    req: PortfolioFundAddRequest,
    db: AsyncSession = Depends(get_db),
):
    if req.shares <= 0:
        raise HTTPException(status_code=400, detail="shares must be greater than 0")
    if req.cost_nav <= 0:
        raise HTTPException(status_code=400, detail="cost_nav must be greater than 0")
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    existing = await portfolio_service.get_portfolio_funds(db, portfolio_id)
    if any(pf.fund_code == req.fund_code for pf in existing):
        raise HTTPException(status_code=409, detail="Fund already in portfolio")
    pf = await portfolio_service.add_fund(
        db, portfolio_id, req.fund_code, req.shares, req.cost_nav, req.purchase_date
    )
    return {"status": "ok", "fund_code": pf.fund_code}


@router.get("/{portfolio_id}/combined-holdings")
async def get_combined_holdings(portfolio_id: int, db: AsyncSession = Depends(get_db)):
    """Aggregate holdings across all funds weighted by portfolio allocation.

    Returns stocks sorted by combined_weight descending, with per-fund
    contributions for each stock.
    """
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    pf_list = await portfolio_service.get_portfolio_funds(db, portfolio_id)

    # Batch-fetch all funds and holdings in two queries
    fund_codes = [pf.fund_code for pf in pf_list]
    funds_map = await fund_info_service.get_funds_by_codes(db, fund_codes)
    holdings_map = await fund_info_service.get_holdings_by_fund_codes(db, fund_codes)

    # Step 1: Compute fund market values using last_nav as conservative estimate
    fund_values: dict[str, float] = {}
    for pf in pf_list:
        fund = funds_map.get(pf.fund_code)
        nav = fund.last_nav if fund and fund.last_nav else 0.0
        fund_values[pf.fund_code] = pf.shares * nav

    total_value = sum(fund_values.values())
    if total_value <= 0:
        return {"holdings": [], "total_value": 0, "coverage": 0}

    # Step 2: Weight each fund's holdings by its share of the portfolio
    combined: dict[str, dict] = {}
    for pf in pf_list:
        fund = funds_map.get(pf.fund_code)
        fund_weight = fund_values[pf.fund_code] / total_value
        holdings = holdings_map.get(pf.fund_code, [])

        for h in holdings:
            contribution = h.holding_ratio * fund_weight
            if h.stock_code not in combined:
                combined[h.stock_code] = {
                    "stock_code": h.stock_code,
                    "stock_name": h.stock_name,
                    "combined_weight": 0.0,
                    "by_fund": [],
                }
            combined[h.stock_code]["combined_weight"] += contribution
            combined[h.stock_code]["by_fund"].append({
                "fund_code": pf.fund_code,
                "fund_name": fund.fund_name if fund else pf.fund_code,
                "fund_weight": round(fund_weight, 4),
                "holding_ratio": h.holding_ratio,
                "contribution": round(contribution, 4),
            })

    # Step 3: Sort by combined_weight descending and round
    result = sorted(combined.values(), key=lambda x: x["combined_weight"], reverse=True)
    for item in result:
        item["combined_weight"] = round(item["combined_weight"], 4)

    total_coverage = sum(h["combined_weight"] for h in result)

    return {
        "holdings": result,
        "total_value": round(total_value, 2),
        "coverage": round(total_coverage, 4),
    }


@router.patch("/{portfolio_id}/funds/{fund_code}")
async def update_fund_in_portfolio(
    portfolio_id: int,
    fund_code: str,
    req: PortfolioFundUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update shares and cost_nav for a fund position (e.g. after dollar-cost averaging)."""
    if req.shares <= 0:
        raise HTTPException(status_code=400, detail="shares must be greater than 0")
    if req.cost_nav <= 0:
        raise HTTPException(status_code=400, detail="cost_nav must be greater than 0")
    pf = await portfolio_service.update_fund(db, portfolio_id, fund_code, req.shares, req.cost_nav, req.purchase_date)
    if pf is None:
        raise HTTPException(status_code=404, detail="Fund not found in portfolio")
    return {"status": "ok", "fund_code": pf.fund_code, "shares": pf.shares, "cost_nav": pf.cost_nav, "purchase_date": pf.purchase_date}


@router.delete("/{portfolio_id}/funds/{fund_code}")
async def remove_fund_from_portfolio(
    portfolio_id: int,
    fund_code: str,
    db: AsyncSession = Depends(get_db),
):
    await portfolio_service.remove_fund(db, portfolio_id, fund_code)
    return {"status": "ok"}


@router.get("/{portfolio_id}/history")
async def get_portfolio_history(
    portfolio_id: int,
    period: str = "30d",
    db: AsyncSession = Depends(get_db),
):
    """Compute portfolio value history from fund NAV history (on-the-fly)."""
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    pf_list = await portfolio_service.get_portfolio_funds(db, portfolio_id)
    if not pf_list:
        return {"dates": [], "values": [], "costs": [], "profit_pcts": []}

    today = datetime.now(_CST)
    period_map = {
        "7d": today - timedelta(days=7),
        "30d": today - timedelta(days=30),
        "ytd": datetime(today.year, 1, 1, tzinfo=_CST),
        "1y": today - timedelta(days=365),
    }
    cutoff_str = period_map.get(period, today - timedelta(days=30)).strftime("%Y-%m-%d")
    total_cost = sum(pf.shares * pf.cost_nav for pf in pf_list)

    # Fetch NAV history for each fund (1-hour cached), run in parallel
    nav_results = await asyncio.gather(
        *[market_data_service.get_fund_nav_history_async(pf.fund_code) for pf in pf_list]
    )
    full_navs: dict[str, dict[str, float]] = {
        pf.fund_code: nav for pf, nav in zip(pf_list, nav_results)
    }

    # Collect all trading-day dates in the period where any fund has data
    all_dates = sorted({
        d
        for nav_dict in full_navs.values()
        for d in nav_dict
        if d >= cutoff_str
    })
    if not all_dates:
        return {"dates": [], "values": [], "costs": [], "profit_pcts": []}

    # Pre-sort NAV series per fund for O(log n) carry-forward lookups
    nav_sorted: dict[str, tuple[list[str], list[float]]] = {
        code: ([d for d, _ in sorted(nav.items())], [v for _, v in sorted(nav.items())])
        for code, nav in full_navs.items()
    }

    def nav_on_or_before(fund_code: str, date_str: str) -> float | None:
        if fund_code not in nav_sorted:
            return None
        dates, navs = nav_sorted[fund_code]
        idx = bisect.bisect_right(dates, date_str) - 1
        return navs[idx] if idx >= 0 else None

    dates_out, values_out, costs_out, profit_pcts_out = [], [], [], []
    for date_str in all_dates:
        value = sum(
            pf.shares * (nav_on_or_before(pf.fund_code, date_str) or pf.cost_nav)
            for pf in pf_list
        )
        profit_pct = (value - total_cost) / total_cost * 100 if total_cost > 0 else 0.0
        dates_out.append(date_str)
        values_out.append(round(value, 2))
        costs_out.append(round(total_cost, 2))
        profit_pcts_out.append(round(profit_pct, 4))

    return {
        "dates": dates_out,
        "values": values_out,
        "costs": costs_out,
        "profit_pcts": profit_pcts_out,
    }
