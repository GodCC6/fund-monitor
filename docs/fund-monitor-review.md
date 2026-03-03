# Fund Monitor — Project Review

> **Review date:** 2026-03-03
> **Reviewed by:** Autonomous code review (Claude Sonnet 4.6)
> **Branch:** main @ `bb1cf3c`

---

## 1. Executive Summary

Fund Monitor is a production-ready, self-hosted fund tracking application for Chinese A-share open-end funds. It estimates intraday NAV in real time by combining a fund's quarterly holdings disclosure with live stock prices, then tracks portfolio P&L and plots multi-period performance against the Shanghai Index benchmark.

**Overall health: Very Good.** All original B-series engineering backlog items (B1–B11) are shipped. The test suite has grown to 118 passing tests. The architecture is clean and the core estimation pipeline works correctly in production. The outstanding gaps are now smaller product features and code hygiene items rather than structural defects.

| Dimension | Rating | Notes |
|-----------|--------|-------|
| Architecture clarity | ✅ Good | Clean separation across API / services / models / tasks |
| Test coverage | ✅ Good | 118 tests, unit + integration + API, all async |
| Error handling | ✅ Good | All market data paths return safe fallbacks; estimate degrades gracefully |
| API design | ✅ Good | REST, typed schemas, predictable patterns |
| Frontend quality | ✅ Good | Vue 3 Composition API, TypeScript, proper cleanup |
| Deployment readiness | ✅ Good | Docker Compose, GitHub Actions CI/CD, healthcheck rollback |
| Feature completeness | ✅ Good | Core investor workflow complete; C-series items are refinements |
| Documentation | ✅ Good | Roadmap and review updated to reflect current state |

---

## 2. Current State

### 2.1 Shipped Features (as of 2026-03-03)

| Feature | Status | Notes |
|---------|--------|-------|
| Core estimation engine (weighted holdings) | ✅ Done | `estimator.py` — correct math, good unit tests |
| 30s scheduler with intraday snapshots | ✅ Done | `scheduler.py` — trading-hours guard, coverage skip, backoff retry (B11) |
| Daily official NAV refresh (20:30 CST) | ✅ Done | `scheduler.py` — compares nav_date before overwriting |
| Daily holdings refresh (21:00 CST) | ✅ Done | `scheduler.py` — only updates on newer report_date |
| Estimate API graceful degradation | ✅ Done | `fund.py` — `degraded: true` flag when quotes unavailable (B1) |
| Portfolio CRUD (create, rename, add/remove funds) | ✅ Done | `portfolio_routes.py` |
| Input validation on fund add | ✅ Done | `portfolio_routes.py` — shares > 0, cost_nav > 0 (B6) |
| Manual refresh button | ✅ Done | `PortfolioDetail.vue` — disabled during load (B2) |
| Portfolio fund list sorting | ✅ Done | `PortfolioDetail.vue` — by est_change_pct / profit_pct (B3) |
| Combined holdings overlap view | ✅ Done | `portfolio_routes.py`, `PortfolioDetail.vue` — risk badges (B7) |
| Fund search by name / code | ✅ Done | `search.py` — cached 1 hour |
| Portfolio P&L (per-fund cost vs. est_nav) | ✅ Done | `portfolio_routes.py:97` |
| Portfolio value history chart | ✅ Done | `portfolio_routes.py:243` — on-the-fly, carry-forward |
| Shanghai Index historical chart | ✅ Done | `chart.py:25` — Sina source (East Money kline blocked) |
| Shanghai Index intraday chart | ✅ Done | `chart.py:63` — direct East Money trends2 endpoint |
| Fund NAV history chart (multi-period) | ✅ Done | `chart.py:126` |
| Fund intraday chart (spike filtering) | ✅ Done | `chart.py:175` — dedup + base_nav anchoring + V-spike suppression |
| Holdings staleness warning (>90 days) | ✅ Done | `PortfolioDetail.vue:119` |
| Stock code normalization (6-digit) | ✅ Done | `market_data.py`, `fund.py`, `scheduler.py` |
| NAV history cache in CacheService | ✅ Done | `market_data.py` — migrated from module-level dict (B9) |
| `is_market_trading_today()` cached 5 min | ✅ Done | `market_data.py:65` (B4) |
| Module-level imports in `chart.py` | ✅ Done | No inline `import akshare` (B10) |
| Docker Compose deployment | ✅ Done | Healthcheck, volume-mounted SQLite, Caddy HTTPS guide |
| GitHub Actions CI/CD | ✅ Done | Test → SSH deploy with health-check rollback |
| pytest async mode + in-memory DB safeguard | ✅ Done | `pyproject.toml`, `tests/conftest.py` (B8-infra) |
| Chart API test coverage (19 tests) | ✅ Done | `tests/test_api_chart.py` (B8) |

---

## 3. Architecture Assessment

### 3.1 Strengths

**Clean layered design.** API routes delegate to service classes (`fund_info_service`, `market_data_service`, `portfolio_service`), services are injected via FastAPI `Depends`, and caching is encapsulated in `CacheService`. Unit testing is straightforward without framework mocking.

**Async throughout (correctly).** FastAPI routes and SQLAlchemy sessions use `async/await`. APScheduler isolates blocking AKShare calls in thread-pool executors. The `CacheService` uses `threading.Lock` for thread-safety under concurrent access from both the async event loop and the scheduler's thread pool.

**Resilient market data.** Two fallback sources for stock quotes (Sina Finance → Tencent Finance). East Money kline blocked on production server: code uses Sina for historical index data and the `trends2` endpoint directly for intraday. Workarounds are clearly documented in code comments.

**Defensive cache strategy.** `stock_cache` TTL is 7 days — quotes survive weekends and public holidays, so `/estimate` responds even when the market is closed. `nav_history_cache` at 1 hour balances freshness with AKShare call volume.

**Solid test suite.** 118 tests across service, API, and integration layers. The pytest-asyncio auto-mode + in-memory SQLite fixture ensures all async tests are isolated and do not touch the production DB file.

**Production-hardened CI/CD.** GitHub Actions runs all tests before SSH deploy. The deploy script performs a live health check and rolls back by re-running the previous image if the check fails.

### 3.2 Weaknesses & Risks

#### W1 — Blocking I/O in async FastAPI handlers
`fund.py:get_estimate` directly calls `market_data_service.is_market_trading_today()` and `get_stock_quotes()` — both use `requests.get()` synchronously. This blocks the FastAPI event loop for the duration of each HTTP call (typically 100–500ms). Under concurrent requests, this degrades response time significantly.

**Risk level:** Medium for a personal tool under light load; higher if the deployment ever handles more than a few concurrent users.

**Fix:** Wrap with `asyncio.to_thread(market_data_service.get_stock_quotes, ...)`.

#### W2 — N+1 queries in `get_portfolio_detail`
`portfolio_routes.py:59-96` loops over each fund and issues two DB queries per fund (`get_fund()` + `get_holdings()`). For a 10-fund portfolio: 20+ sequential DB round-trips per request.

**Risk level:** Low for small portfolios on local SQLite; would noticeably degrade at ~10+ funds.

**Fix:** Batch both queries with `WHERE fund_code IN (...)`.

#### W3 — `isTradeTime()` frontend uses browser local time
`PortfolioDetail.vue:127` computes trading hours against `new Date()` (browser local time). Users whose browser is not set to UTC+8 will have auto-refresh activate and deactivate at incorrect times.

**Risk level:** Low for a single user in China; Medium if shared with users in other timezones.

**Fix:** Convert to UTC+8 offset before comparing: `const offset = 8 * 60; const cstMinutes = (now.getUTCHours() * 60 + now.getUTCMinutes() + offset) % (24 * 60)`.

#### W4 — Dead `estimate_cache` instance
`cache.py:46` creates `estimate_cache = CacheService(...)` but it is never referenced anywhere in the codebase. It's dead code that adds noise.

**Risk level:** None — cosmetic.

#### W5 — `search.py` fund name cache is not thread-safe
`search.py:18-28` uses a plain `dict` with manual timestamp TTL. Unlike `CacheService`, there is no `threading.Lock`. If two requests arrive simultaneously when the cache is stale, both will call `ak.fund_name_em()` concurrently and then write to the dict without coordination.

**Risk level:** Low — AKShare calls are slow but not dangerous to duplicate; the data is immutable and eventual-consistent.

#### W6 — Naive `datetime.now()` in portfolio history cutoff
`portfolio_routes.py:258` uses `datetime.now()` (local server time) to compute the history period cutoff. All other date computations use `datetime.now(_CST)`. This is inconsistent and could produce slightly off cutoffs if the server is not in UTC+8.

**Risk level:** Low — only affects the exact boundary dates of history periods.

#### W7 — No composite DB index on snapshot table
`fund_estimate_snapshot` queries by `(fund_code, snapshot_date)` but only has individual column indexes. For a high-frequency personal user with months of snapshots, a composite index would noticeably speed up the intraday chart endpoint.

**Risk level:** Low currently; grows proportionally with usage time.

#### W8 — AKShare remains a single point of failure
All stock quotes, NAV history, holdings, and fund search flow through AKShare. If AKShare releases a breaking API change, the estimation pipeline fails silently (logged only). There is no automated health check or alert.

**Risk level:** Medium for long-running production installs.

#### W9 — In-memory cache resets on restart
`CacheService` stores everything in a Python dict. A container restart clears all cached quotes. The scheduler repopulates within 30 seconds on the next trading tick, but estimates immediately after restart return degraded data.

**Risk level:** Low — `degraded: true` flag surfaces this correctly; the scheduler recovers quickly.

---

## 4. Code Quality

### 4.1 Test Coverage

The test suite covers all major code paths.

| Test module | Layer | What it verifies |
|-------------|-------|-----------------|
| `test_models.py` | ORM | SQLAlchemy model instantiation |
| `test_cache.py` | Service | TTL expiry, set/get/delete, thread-safety |
| `test_estimator.py` | Service | Weighted NAV math (with/without missing quotes) |
| `test_fund_info.py` | Service | Fund & holdings CRUD |
| `test_market_data.py` | Service | AKShare mocking, null handling, code normalization, CacheService integration |
| `test_portfolio.py` | Service | Portfolio CRUD |
| `test_api_fund.py` | API | GET fund, estimate, holdings, NAV refresh, degraded path |
| `test_api_portfolio.py` | API | Portfolio CRUD endpoints |
| `test_api_portfolio_fund_display.py` | API | Fund details in portfolio view |
| `test_api_portfolio_history.py` | API | History period filtering and carry-forward |
| `test_api_combined_holdings.py` | API | Combined holdings aggregation logic |
| `test_api_search.py` | API | Search & setup endpoints |
| `test_api_nav_refresh.py` | API | NAV refresh mechanics, trading-hours block |
| `test_api_chart.py` | API | All chart endpoints (19 tests) |
| `test_api_chart_intraday.py` | API | Intraday snapshot dedup and spike filtering |
| `test_portfolio_snapshot.py` | Task | Daily snapshot save logic |
| `test_scheduler.py` | Task | Exponential backoff retry logic |
| `test_integration.py` | E2E | setup → portfolio → estimate full flow |

**Remaining gaps:**
- No tests for `search.py` setup endpoint with live AKShare mock (covered indirectly in `test_integration.py`)
- No tests for `save_portfolio_snapshots` with multi-fund portfolios where some funds have no holdings
- No frontend tests (acceptable for a small Vue app at this stage)
- No CI coverage threshold gate (a minimum of ~60% could be enforced via `--cov-fail-under`)

### 4.2 Error Handling Matrix

| Call site | On failure | Assessment |
|-----------|-----------|-----------|
| `get_stock_quotes()` | Returns `{}`, logs warning | ✅ Correct |
| `get_fund_holdings()` | Returns `[]`, logs error | ✅ Correct |
| `get_fund_nav()` | Returns `None`, logs error | ✅ Correct |
| `get_index_history()` | Returns empty arrays | ✅ Correct |
| `get_index_intraday()` | Returns empty arrays | ✅ Correct |
| `get_fund_nav_history()` | Returns `{}`, logs error | ✅ Correct |
| `/estimate` with empty quotes | Returns `degraded: true`, 200 OK | ✅ Correct (B1) |
| DB session errors | Propagates as FastAPI 500 | ⚠️ Acceptable (internal service, not adversarial) |
| Scheduler job exceptions | Logged, job continues | ✅ Correct |
| `POST /funds` with negative values | Returns 400 | ✅ Correct (B6) |

### 4.3 Anti-Patterns

| Anti-pattern | Location | Severity |
|-------------|---------|---------|
| Blocking `requests.get` in async handler | `fund.py:130,135` | **Medium** — blocks event loop |
| Blocking `requests.get` in async portfolio handler | `portfolio_routes.py:53,81` | **Medium** |
| `_fund_name_cache` plain dict (not thread-safe, not CacheService) | `search.py:18` | Low |
| `estimate_cache` created but never used | `cache.py:46` | Cosmetic |
| Inline imports in `save_portfolio_snapshots` | `scheduler.py:156-157` | Cosmetic |
| Naive `datetime.now()` in history cutoff | `portfolio_routes.py:258` | Low |
| `isTradeTime()` uses browser local time, not CST | `PortfolioDetail.vue:127` | Low |
| N+1 DB queries in portfolio detail | `portfolio_routes.py:59-96` | Low (small datasets) |

---

## 5. Optimizations & New Features

See `docs/ROADMAP.md` for the full C-series backlog. Key items by tier:

### 5.1 P1 — Fix Now (all < 1h)

**C1 — DELETE portfolio endpoint + UI**
`portfolio_service.delete_portfolio()` exists but no API route or UI exposes it. Users cannot delete portfolios. Add `DELETE /api/portfolio/{id}` and a delete button to `Home.vue`.

**C2 — Prevent duplicate fund in portfolio**
`POST /api/portfolio/{id}/funds` with an already-tracked `fund_code` silently creates a duplicate row. Check for existence before insert; return 409 Conflict if duplicate.

**C3 — Fix `isTradeTime()` to use CST**
`PortfolioDetail.vue:127` uses `new Date()` (browser local time). One-line fix: compute offset from UTC.

### 5.2 P2 — Hygiene (all < 2h each)

- **C4–C7:** Remove dead `estimate_cache`; migrate `search.py` cache to CacheService; move inline imports; fix naive datetime in history cutoff.
- **C8:** Add composite index on `fund_estimate_snapshot(fund_code, snapshot_date)` to speed up intraday chart queries as the table grows.
- **C9:** Batch DB queries in `get_portfolio_detail` to eliminate N+1 pattern.
- **C10:** Wrap blocking `requests.get` market data calls with `asyncio.to_thread()` when called from async FastAPI handlers.
- **C11:** Add `ruff` lint step and TypeScript `tsc --noEmit` to GitHub Actions.

### 5.3 P3 — Product Improvements

- **C12:** Portfolio chart benchmark overlay — add Shanghai Index to `PortfolioChart.vue`, same pattern as `NavChart.vue`. Requires adding index data to the `/history` response or a separate fetch.
- **C13:** Annualized return (CAGR) — meaningful for long-term positions. `CAGR = (value/cost)^(1/years) - 1`. Computable client-side from existing `added_at` field.
- **C14:** Fund position edit — `PUT /api/portfolio/{id}/funds/{code}` to update `shares` and `cost_nav` without remove + re-add.
- **C15:** AKShare health monitoring — daily probe at 09:00, log prominent warning on failure (B13).
- **C16:** Fund comparison view — overlay two fund NAV curves (B14).

---

## 6. Key File Reference

| File | Purpose |
|------|---------|
| `backend/app/main.py` | App entry, lifespan, CORS, router mounts |
| `backend/app/config.py` | All configuration (DB URL, cache TTLs, trading hours) |
| `backend/app/api/fund.py` | Fund metadata, estimate, holdings, NAV refresh |
| `backend/app/api/portfolio_routes.py` | Portfolio CRUD, history, combined holdings |
| `backend/app/api/chart.py` | NAV history, intraday, Shanghai Index |
| `backend/app/api/search.py` | Fund search + setup |
| `backend/app/api/schemas.py` | Pydantic request/response schemas |
| `backend/app/services/estimator.py` | NAV estimation algorithm — `Σ(ratio_i × change_pct_i)` |
| `backend/app/services/market_data.py` | All AKShare + direct API integrations |
| `backend/app/services/cache.py` | Thread-safe in-memory TTL cache (`stock_cache`, `nav_history_cache`) |
| `backend/app/services/fund_info.py` | Fund + holdings CRUD |
| `backend/app/services/portfolio.py` | Portfolio + PortfolioFund CRUD |
| `backend/app/tasks/scheduler.py` | Background jobs (quotes+snapshots every 30s, NAV/holdings daily) |
| `backend/app/models/fund.py` | `Fund`, `FundHolding`, `FundEstimateSnapshot` ORM models |
| `backend/app/models/portfolio.py` | `Portfolio`, `PortfolioFund`, `PortfolioSnapshot` ORM models |
| `frontend/src/views/PortfolioDetail.vue` | Main portfolio page |
| `frontend/src/views/FundDetail.vue` | Fund detail page with estimate and holdings |
| `frontend/src/views/Home.vue` | Portfolio list and create |
| `frontend/src/components/NavChart.vue` | Fund NAV + index chart (ECharts) |
| `frontend/src/components/PortfolioChart.vue` | Portfolio history chart (ECharts) |
| `frontend/src/api/index.ts` | Typed API client (19 endpoints) |
| `.github/workflows/deploy.yml` | CI: test → SSH deploy with health-check rollback |

---

*Generated: 2026-03-03 | Fund Monitor main @ bb1cf3c*
