"""Pydantic schemas for API request/response."""

from pydantic import BaseModel


class FundResponse(BaseModel):
    fund_code: str
    fund_name: str
    fund_type: str
    last_nav: float | None = None
    nav_date: str | None = None


class FundEstimateResponse(BaseModel):
    fund_code: str
    fund_name: str
    est_nav: float
    est_change_pct: float
    last_nav: float
    coverage: float
    details: list[dict]


class HoldingResponse(BaseModel):
    stock_code: str
    stock_name: str
    holding_ratio: float
    report_date: str


class AddFundRequest(BaseModel):
    fund_code: str


class PortfolioCreateRequest(BaseModel):
    name: str


class PortfolioRenameRequest(BaseModel):
    name: str


class PortfolioFundAddRequest(BaseModel):
    fund_code: str
    shares: float
    cost_nav: float


class PortfolioResponse(BaseModel):
    id: int
    name: str
    created_at: str


class PortfolioFundResponse(BaseModel):
    fund_code: str
    fund_name: str
    shares: float
    cost_nav: float
    est_nav: float
    est_change_pct: float
    cost: float
    current_value: float
    profit: float
    profit_pct: float
    coverage: float
    holdings_date: str | None = None


class PortfolioDetailResponse(BaseModel):
    id: int
    name: str
    created_at: str
    funds: list[PortfolioFundResponse]
    total_cost: float
    total_estimate: float
    total_profit: float
    total_profit_pct: float
