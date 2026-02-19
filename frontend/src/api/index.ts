const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) throw new Error(`API error: ${resp.status}`)
  return resp.json()
}

export interface FundInfo {
  fund_code: string
  fund_name: string
  fund_type: string
  last_nav: number | null
  nav_date: string | null
}

export interface FundEstimate {
  fund_code: string
  fund_name: string
  est_nav: number
  est_change_pct: number
  last_nav: number
  coverage: number
  details: Array<{
    stock_code: string
    stock_name: string
    holding_ratio: number
    price: number
    change_pct: number
    contribution: number
  }>
}

export interface PortfolioSummary {
  id: number
  name: string
  created_at: string
}

export interface PortfolioFund {
  fund_code: string
  fund_name: string
  shares: number
  cost_nav: number
  est_nav: number
  est_change_pct: number
  cost: number
  current_value: number
  profit: number
  profit_pct: number
  coverage: number
  holdings_date: string | null
}

export interface PortfolioDetail {
  id: number
  name: string
  created_at: string
  funds: PortfolioFund[]
  total_cost: number
  total_estimate: number
  total_profit: number
  total_profit_pct: number
}

export interface NavHistoryData {
  dates: string[]
  navs: number[]
}

export interface IntradayData {
  date: string
  last_nav: number
  times: string[]
  navs: number[]
}

export interface IndexHistoryData {
  dates: string[]
  values: number[]
  name: string
}

export interface IndexIntradayData {
  times: string[]
  values: number[]
  pre_close: number
  name: string
}

export const api = {
  getFund: (code: string) => request<FundInfo>(`/api/fund/${code}`),

  getFundEstimate: (code: string) => request<FundEstimate>(`/api/fund/${code}/estimate`),

  getFundHoldings: (code: string) => request<unknown[]>(`/api/fund/${code}/holdings`),

  listPortfolios: () => request<PortfolioSummary[]>('/api/portfolio'),

  createPortfolio: (name: string) =>
    request<PortfolioSummary>('/api/portfolio', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),

  getPortfolio: (id: number) => request<PortfolioDetail>(`/api/portfolio/${id}`),

  addFundToPortfolio: (id: number, fundCode: string, shares: number, costNav: number) =>
    request<unknown>(`/api/portfolio/${id}/funds`, {
      method: 'POST',
      body: JSON.stringify({ fund_code: fundCode, shares, cost_nav: costNav }),
    }),

  removeFundFromPortfolio: (id: number, fundCode: string) =>
    request<unknown>(`/api/portfolio/${id}/funds/${fundCode}`, { method: 'DELETE' }),

  setupFund: (code: string) => request<unknown>(`/api/fund/setup/${code}`, { method: 'POST' }),

  getNavHistory: (code: string, period: string) =>
    request<NavHistoryData>(`/api/fund/${code}/nav-history?period=${period}`),

  getIntraday: (code: string) =>
    request<IntradayData>(`/api/fund/${code}/intraday`),

  getIndexHistory: (period: string) =>
    request<IndexHistoryData>(`/api/fund/index/history?period=${period}`),

  getIndexIntraday: () =>
    request<IndexIntradayData>('/api/fund/index/intraday'),
}
