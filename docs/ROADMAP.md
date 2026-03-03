# Fund Monitor — Product Roadmap

> Last updated: 2026-03-03
> Based on full codebase review at main @ `bb1cf3c` (all B1–B11 complete, 118 tests passing)

---

## Current Status

### Completed Features

| Module | Feature | Shipped |
|--------|---------|---------|
| Estimation engine | Weighted-holdings real-time NAV estimate, coverage % | ✅ |
| Scheduler | 30s intraday quote refresh + snapshot persistence | ✅ |
| Scheduler | Exponential backoff retry on failed stock fetches (B11) | ✅ |
| Scheduler | Daily official NAV refresh at 20:30 CST | ✅ |
| Scheduler | Daily holdings refresh at 21:00 CST | ✅ |
| Estimate API | Graceful degradation: `degraded: true` flag, no error banner on market close (B1) | ✅ |
| Portfolio CRUD | Create, rename, add/remove funds; cost basis + P&L | ✅ |
| Portfolio view | Manual refresh button (B2) | ✅ |
| Portfolio view | Fund list sort by est_change_pct / profit_pct (B3) | ✅ |
| Portfolio view | Combined holdings overlap panel with risk badges (B7) | ✅ |
| Fund search | Name / code search, cached 1 hour | ✅ |
| Portfolio history | On-the-fly NAV history, period filtering, carry-forward | ✅ |
| CSI 300 historical chart | Sina Finance source (East Money kline blocked) | ✅ |
| CSI 300 intraday chart | Direct East Money trends2 API with browser headers | ✅ |
| Fund NAV history chart | Multi-period (7d / 30d / ytd / 1y / 3y) | ✅ |
| Fund intraday chart | Snapshot dedup + base_nav anchoring (no jump on refresh) | ✅ |
| Holdings staleness warning | Frontend badge when holdings > 90 days old | ✅ |
| Stock code normalization | 6-digit zero-padded across cache, scheduler, fund API | ✅ |
| Input validation | `shares > 0`, `cost_nav > 0` on fund add (B6) | ✅ |
| Cache | `is_market_trading_today()` cached 5 min (B4) | ✅ |
| Cache | `_nav_history_cache` migrated to shared `CacheService` (B9) | ✅ |
| Chart | Timezone-aware `datetime.now(_CST)` throughout `chart.py` (B5) | ✅ |
| Chart | Module-level imports (no inline `import akshare`) (B10) | ✅ |
| Docker | Docker Compose deployment, healthcheck, volume-mounted SQLite | ✅ |
| CI/CD | GitHub Actions: test → SSH deploy with health-check rollback | ✅ |
| Tests | pytest asyncio auto-mode + in-memory DB safeguard (B8-infra) | ✅ |
| Tests | Comprehensive chart.py endpoint coverage — 19 tests (B8) | ✅ |

---

## Development Backlog

### Tier 1 — P1 Feature Gaps (quick fixes, high impact)

| ID | Task | Effort | Files | Status |
|----|------|--------|-------|--------|
| C1 | DELETE portfolio endpoint + Home.vue delete button | 1h | `portfolio_routes.py`, `Home.vue`, `api/index.ts` | 📋 |
| C2 | Prevent duplicate fund in portfolio (check before add) | 30m | `portfolio_routes.py` | 📋 |
| C3 | `isTradeTime()` frontend uses local browser time, not CST — fix to UTC+8 | 15m | `PortfolioDetail.vue` | 📋 |

**C1 details:** `portfolio_service.delete_portfolio()` already exists in `services/portfolio.py:26` — no API route or UI exposes it. Users can create portfolios but cannot delete them.

**C2 details:** `POST /api/portfolio/{id}/funds` with a `fund_code` already in the portfolio silently creates a duplicate row, resulting in doubled position size.

**C3 details:** `PortfolioDetail.vue:127-133` calls `new Date()` for trade-hours detection — this uses the browser's local timezone. Users outside UTC+8 will see auto-refresh trigger at wrong times.

---

### Tier 2 — P2 Engineering Hygiene

| ID | Task | Effort | Files | Status |
|----|------|--------|-------|--------|
| C4 | Remove dead `estimate_cache` — created in `cache.py` but never used anywhere | 5m | `app/services/cache.py` | 📋 |
| C5 | Migrate `_fund_name_cache` in `search.py` to `CacheService` (thread-safety + consistency) | 30m | `app/api/search.py`, `app/config.py` | 📋 |
| C6 | Move inline imports in `scheduler.py:save_portfolio_snapshots` to module level | 15m | `app/tasks/scheduler.py` | 📋 |
| C7 | Fix naive `datetime.now()` in `portfolio_routes.py:258` history cutoff to `datetime.now(_CST)` | 15m | `app/api/portfolio_routes.py` | 📋 |
| C8 | Add composite DB index on `fund_estimate_snapshot(fund_code, snapshot_date)` | 30m | `app/models/fund.py` | 📋 |
| C9 | N+1 query fix in `get_portfolio_detail` — batch `get_fund` + `get_holdings` calls | 2h | `app/api/portfolio_routes.py` | 📋 |
| C10 | Wrap blocking `requests.get` calls in async handlers with `asyncio.to_thread()` | 2h | `app/api/fund.py`, `app/api/portfolio_routes.py`, `app/services/market_data.py` | 📋 |
| C11 | Add `ruff` linting and TypeScript `tsc --noEmit` type-check step to CI | 1h | `.github/workflows/deploy.yml` | 📋 |

**C9 details:** `get_portfolio_detail()` issues ~20 sequential DB queries for a 10-fund portfolio (2 per fund: `get_fund()` + `get_holdings()`). Refactor to batch queries with `WHERE fund_code IN (...)`.

**C10 details:** `fund.py:get_estimate` calls `market_data_service.is_market_trading_today()` and `get_stock_quotes()` synchronously. These use `requests.get()` (blocking I/O) inside async FastAPI handlers, blocking the event loop for the duration of the HTTP call. The scheduler correctly uses `to_thread` via APScheduler; the direct API path does not.

---

### Tier 3 — P3 Product Features

| ID | Task | Effort | Files | Status |
|----|------|--------|-------|--------|
| C12 | Portfolio history benchmark overlay (CSI 300 / Shanghai Index on portfolio chart) | 3h | `portfolio_routes.py`, `PortfolioChart.vue`, `api/index.ts` | 📋 |
| C13 | Annualized return (CAGR) display on portfolio and fund detail pages | 1h | `portfolio_routes.py`, `PortfolioDetail.vue` | 📋 |
| C14 | Fund position edit — update `shares` and `cost_nav` after buy-in averaging | 2h | `portfolio_routes.py`, `PortfolioDetail.vue`, `api/index.ts` | 📋 |
| C15 | AKShare health monitoring job — daily probe + warning log | 2h | `app/tasks/scheduler.py` | 📋 |
| C16 | Fund comparison view — overlay two fund NAV curves | 4h | new `FundCompare.vue`, `chart.py`, `router/index.ts` | 📋 |

**C12 details:** `PortfolioChart.vue` shows only portfolio profit %; `NavChart.vue` already shows fund vs. index — the same pattern (fetch index history, align dates, render dual series) can be applied to the portfolio chart. Requires adding index data to the `/history` response or fetching it separately.

**C13 details:** Total return % is easy to interpret for short-term positions but misleading for long-term ones. CAGR = `(current_value/cost)^(1/years) - 1`. Can be computed client-side from `cost_nav`, `current_value`, and `added_at` date already present in the `PortfolioFund` model.

**C14 details:** No PATCH or PUT endpoint for `PortfolioFund`. Users who dollar-cost-average must remove and re-add a fund at the weighted average cost, which is tedious and loses the original position metadata.

---

### Tier 4 — Future / Optional

| ID | Task | Effort | Notes |
|----|------|--------|-------|
| C17 | Email / push alerts when fund drops > X% | 6h+ | Requires notification infrastructure (SMTP or push service) |
| C18 | Redis persistent cache | 4h | Only useful if deploying multiple backend replicas |
| C19 | Portfolio CSV export (positions + cost basis + P&L) | 2h | Useful for tax reporting and external analysis |
| C20 | WebSocket live updates instead of 30s polling | 6h+ | Higher complexity, marginal UX gain for personal use |

---

## Architecture Notes

- **Backend:** FastAPI + SQLite (aiosqlite) + AKShare + APScheduler
- **Frontend:** Vue 3 Composition API + TypeScript, no UI library, ECharts for charts
- **Tests:** pytest + pytest-asyncio, 118 tests — all new endpoints require tests; use in-memory SQLite via conftest.py
- **DB migrations:** Add tables in `models/`, auto-created via `Base.metadata.create_all` in `init_db()`
- **A-share colour convention:** up = `#ff4444` (red), down = `#00c853` (green)
- **Estimate badge:** all non-official NAVs must show the orange `估` badge
- **Market data sources:** Sina Finance (primary quotes), Tencent Finance (fallback), East Money trends2 (intraday index), AKShare (NAV history, holdings, fund search)
- **Blocking I/O pattern:** AKShare + requests calls are synchronous. Safe in scheduler (APScheduler uses thread-pool executor). **Not** safe when called directly from FastAPI async handlers — should use `asyncio.to_thread()`.
- **Cache hierarchy:** `stock_cache` (7d TTL, quotes survive weekends), `nav_history_cache` (1h TTL), `_trading_today_cache` (5m TTL, module-level tuple — intentionally lightweight)
- **SQLite WAL mode not explicitly set** — auto-created tables use default journal mode. WAL (`PRAGMA journal_mode=WAL`) would improve read concurrency under Docker.

---

## Documentation

| Document | Status |
|----------|--------|
| `README.md` | ✅ Current |
| `docs/DEPLOYMENT.md` | ✅ Current |
| `docs/ROADMAP.md` | ✅ Updated 2026-03-03 |
| `docs/fund-monitor-review.md` | ✅ Updated 2026-03-03 |
| `docs/plans/2026-02-18-holdings-overlap-analysis.md` | ✅ Archived — B7 shipped |
| `docs/plans/2026-02-18-engineering-improvements.md` | ✅ Archived — B1/B2/B3/B6 shipped |
