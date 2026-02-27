# Fund Monitor — Project Review

> **Review date:** 2026-02-28
> **Reviewed by:** Autonomous code review (Claude Sonnet 4.6)
> **Branch:** main @ `3ed65a2`

---

## 1. Executive Summary

Fund Monitor is a production-ready, self-hosted fund tracking application for Chinese A-share open-end funds. It estimates intraday NAV in real time by combining a fund's quarterly holdings disclosure with live stock prices, then tracks portfolio P&L and plots multi-period performance against the CSI 300 benchmark.

**Overall health: Good.** The architecture is clean, the test suite is substantive, and the core estimation pipeline works correctly in production. The outstanding gaps are product features (holdings overlap analysis, API degradation handling, sorting) rather than structural defects.

| Dimension | Rating | Notes |
|-----------|--------|-------|
| Architecture clarity | ✅ Good | Clean separation across API / services / models / tasks |
| Test coverage | ✅ Good | 14 test files, unit + integration, all async |
| Error handling | ⚠️ Mixed | Market data is defensive; DB/scheduler errors are not |
| API design | ✅ Good | REST, typed schemas, predictable patterns |
| Frontend quality | ✅ Good | Vue 3 Composition API, TypeScript, proper cleanup |
| Deployment readiness | ✅ Good | Docker Compose, healthcheck, Nginx, Caddy guide |
| Feature completeness | ⚠️ Partial | P2/P3 backlog remains |
| Documentation | ⚠️ Stale | ROADMAP reflects Feb 18 state; most items since shipped |

---

## 2. Current Status

### 2.1 Completed Features

| Feature | Status | Notes |
|---------|--------|-------|
| Core estimation engine (weighted holdings) | ✅ Done | `estimator.py` — correct math, good unit tests |
| 30s scheduler with intraday snapshots | ✅ Done | `scheduler.py` — trading-hours guard, coverage skip |
| Daily official NAV refresh (20:30 CST) | ✅ Done | `scheduler.py` — compares nav_date before overwriting |
| Portfolio CRUD (create, rename, add/remove funds) | ✅ Done | `portfolio_routes.py` |
| Fund search by name / code | ✅ Done | `search.py` — cached 1 hour |
| Portfolio P&L (per-fund cost vs. est_nav) | ✅ Done | `portfolio_routes.py:44` |
| Portfolio value history chart (on-the-fly, bisect) | ✅ Done | `portfolio_routes.py:176` |
| CSI 300 historical chart (Sina source) | ✅ Done | `chart.py:23` — kline was blocked, Sina works |
| CSI 300 intraday chart (direct East Money API) | ✅ Done | `chart.py:63` — bypasses blocked akshare endpoint |
| Fund NAV history chart (multi-period) | ✅ Done | `chart.py:128` |
| Fund intraday chart (snapshot dedup + base_nav fix) | ✅ Done | `chart.py:179` — fixed jump on nav_date refresh |
| Holdings staleness warning (>90 days) | ✅ Done | Frontend: `PortfolioDetail.vue` |
| Stock code normalization (6-digit, zero-padded) | ✅ Done | Fixed in `market_data.py`, `fund.py`, `scheduler.py` |
| Docker Compose deployment | ✅ Done | Healthcheck, volume-mounted SQLite, Caddy HTTPS guide |

### 2.2 Not Yet Implemented

| Feature | Priority | Plan |
|---------|----------|------|
| Portfolio combined holdings overlap analysis | P2 | `docs/plans/2026-02-18-holdings-overlap-analysis.md` |
| Estimate API graceful degradation (`degraded` flag) | P3 | `docs/plans/2026-02-18-engineering-improvements.md` |
| Manual NAV refresh button (frontend) | P3 | Same plan |
| Fund list sorting (by change %, profit %) | P3 | Same plan |

---

## 3. Architecture Assessment

### 3.1 Strengths

**Layered, testable design.** API routes delegate to service classes, services are injected via FastAPI `Depends`, and the cache is a plain in-memory object. This makes unit testing straightforward without mocking the entire framework.

**Async throughout.** FastAPI routes, SQLAlchemy sessions, and DB queries are all `async/await`. APScheduler runs the heavy AKShare calls in thread-pool executors (blocking I/O isolated from the async event loop — confirmed in scheduler logic).

**Sensible cache strategy.** The 7-day TTL on `stock_cache` ensures stock prices survive through weekends and public holidays, so the estimation endpoint can still respond when the market is closed.

**Chart data pipeline resilience.** After discovering that East Money's kline API is blocked from the production server, the code falls back to Sina Finance for historical index data and calls the East Money `trends2` endpoint directly (with browser headers) for intraday data. These workarounds are clearly documented in the code.

**6-digit stock code normalization.** All cache keys and holdings lookups now use zero-padded 6-digit codes (`000001`, `600519`), eliminating the class of cache-miss bugs that caused estimate coverage to be 0.

### 3.2 Weaknesses & Risks

#### W1 — In-memory cache is restart-unsafe
`CacheService` stores everything in a Python dict. A container restart (e.g., after a deploy) clears all stock quotes. The scheduler repopulates cache within 30 seconds on the next trading day, but portfolio snapshots saved immediately after a restart may use stale or missing quotes.

**Risk level:** Low (scheduler recovers quickly; portfolio snapshots fall back to `fund.last_nav`).

#### W2 — AKShare is a single point of failure for all market data
All stock quotes, NAV history, holdings, and fund search flow through AKShare. If AKShare releases a breaking API change, the entire estimation pipeline breaks.

**Risk level:** Medium. AKShare updates irregularly; monitoring is manual (check docker logs).

#### W3 — Scheduler errors are swallowed without retry
`update_stock_quotes()` wraps each fund's holdings fetch in a broad `except Exception: logger.exception(...)` and continues. If AKShare is rate-limiting (HTTP 429), the scheduler silently skips that fund until the next 30s tick.

**Risk level:** Low for transient errors; Medium if AKShare blocks the server IP.

#### W4 — No input validation on portfolio fund values
`POST /api/portfolio/{id}/funds` accepts `shares` and `cost_nav` without range checks. A negative `shares` or `cost_nav=0` produces nonsensical P&L without an error.

**Risk level:** Low (personal tool, no adversarial input expected).

#### W5 — `nav-history` endpoint imports akshare inside the handler
`chart.py:141` does `import akshare as ak` inside the async handler. Python caches module imports after the first call, so this is a one-time cost, not a per-request penalty. However, it's inconsistent with the rest of the codebase (which imports at module level) and slightly obscures the dependency.

**Risk level:** Cosmetic only.

#### W6 — Holdings data lag (quarterly disclosure)
All fund holdings come from quarterly reports. A fund's disclosed holdings may be 1–4 months old. The estimation accuracy degrades proportionally to how much the manager has repositioned since the last report.

**Risk level:** Inherent to the product domain; frontend already warns if holdings are >90 days old.

---

## 4. Code Quality

### 4.1 Test Coverage

The test suite is solid for a project of this size.

| Test module | Layer | What it verifies |
|-------------|-------|-----------------|
| `test_models.py` | ORM | SQLAlchemy model instantiation |
| `test_cache.py` | Service | TTL expiry, set/get/delete |
| `test_estimator.py` | Service | Weighted NAV math (with/without missing quotes) |
| `test_fund_info.py` | Service | Fund & holdings CRUD |
| `test_market_data.py` | Service | AKShare mocking, null handling, code normalization |
| `test_portfolio.py` | Service | Portfolio CRUD |
| `test_api_fund.py` | API | GET fund, estimate, holdings endpoints |
| `test_api_portfolio.py` | API | Portfolio CRUD endpoints |
| `test_api_portfolio_fund_display.py` | API | Fund details in portfolio view |
| `test_api_portfolio_history.py` | API | History period filtering and carry-forward |
| `test_api_search.py` | API | Search & setup endpoints |
| `test_api_nav_refresh.py` | API | NAV refresh mechanics |
| `test_portfolio_snapshot.py` | Task | Daily snapshot save logic |
| `test_integration.py` | E2E | setup → portfolio → estimate full flow |

**Gaps:**
- No tests for `chart.py` endpoints (`get_index_history`, `get_intraday`, `get_index_intraday`, `get_nav_history`).
- No tests for the scheduler's `save_portfolio_snapshots` with multi-fund portfolios.
- No frontend tests (acceptable for small Vue app with no test infrastructure set up).

### 4.2 Error Handling Matrix

| Call site | On failure | Assessment |
|-----------|-----------|-----------|
| `get_stock_quotes()` | Returns `{}` | ✅ Correct |
| `get_fund_holdings()` | Returns `[]` | ✅ Correct |
| `get_fund_nav()` | Returns `None` | ✅ Correct |
| `get_index_history()` | Returns empty arrays | ✅ Correct |
| `get_index_intraday()` | Returns empty arrays | ✅ Correct |
| `get_fund_nav_history()` | Returns `{}` | ✅ Correct |
| DB session errors | Unhandled (propagates to FastAPI 500) | ⚠️ Acceptable |
| Scheduler job exceptions | Logged, job continues | ⚠️ No retry |
| `POST /api/portfolio/{id}/funds` with negative values | Returns 200 with bad data | ❌ Missing validation |

### 4.3 Observed Anti-Patterns

| Anti-pattern | Location | Severity |
|-------------|---------|---------|
| Inline `import` inside async handler | `chart.py:141, 29` | Cosmetic |
| `_nav_history_cache` at module level (not part of `CacheService`) | `market_data.py` | Low — bypasses the unified cache API, makes it harder to clear |
| `is_market_trading_today()` makes a live HTTP call on every estimate request | `market_data.py` | Low — should be cached (e.g., once per day) |
| Timezone naive `datetime.now()` in `chart.py:154` | `chart.py:154` | Low — rest of file uses `_CST`-aware datetimes |

---

## 5. Proposed Optimizations

### 5.1 Quick Wins (< 1 hour each)

**O1 — Cache `is_market_trading_today()` result**
The function calls the East Money trends2 API on every `/estimate` request to check whether the market is open. Cache the result for 5 minutes (or until next trading session start/end) to reduce latency and external calls.

**O2 — Use `CacheService` for `_nav_history_cache`**
`market_data.py` has its own module-level dict `_nav_history_cache`. Migrate it to the shared `CacheService` so the cache has a single eviction path and consistent observability.

**O3 — Add range validation on portfolio fund inputs**
In `portfolio_routes.py:151`, validate `shares > 0` and `cost_nav > 0` before writing to DB. Return HTTP 422 with a clear message.

**O4 — Fix timezone-naive `datetime.now()` in chart.py**
`chart.py:154` uses `datetime.now()` (local time) while `chart.py:190` uses `datetime.now(_CST)`. Standardize to `datetime.now(_CST)` throughout to avoid subtle cutoff bugs during DST transitions.

**O5 — Move inline imports to module level in chart.py**
`import akshare as ak` and `import requests as _requests` inside handlers should be moved to module level for clarity and consistency.

### 5.2 Medium Effort (2–4 hours each)

**O6 — Add `degraded` flag to estimate API (P3-Task1)**
When stock quote fetch fails entirely (empty result from both cache and live fetch), return `est_nav = last_nav`, `est_change_pct = 0.0`, `coverage = 0.0`, `degraded = true` instead of an empty/error response. Frontend can show a grey "—" instead of an error banner.

**O7 — Add manual refresh button for estimates (P3-Task2)**
A "Refresh" button in `PortfolioDetail.vue` that calls `api.getFundEstimate(code)` for all funds without waiting for the 30s auto-refresh. Low-effort frontend change; backend already supports it.

**O8 — Add sorting to portfolio fund list (P3-Task3)**
Clickable column headers on the fund table (sort by est_change_pct, profit_pct, fund_code). Pure frontend change in `PortfolioDetail.vue`.

**O9 — Add tests for chart.py endpoints**
Mock `akshare.stock_zh_index_daily`, `akshare.fund_open_fund_info_em`, and the `requests.get` call in `get_index_intraday`. Cover: empty response, period filtering, deduplication. Estimated 2–3 hours.

### 5.3 Larger Investments (4+ hours)

**O10 — Portfolio combined holdings overlap (P2-A)**
See `docs/plans/2026-02-18-holdings-overlap-analysis.md` for the full spec. In brief: compute each stock's effective weight across the portfolio by scaling fund holdings by fund market-value weight. Surface in a collapsible "Combined Holdings" panel on the portfolio detail page.

**O11 — Persistent cache (Redis or SQLite-backed)**
Replace the in-memory `CacheService` with a Redis instance (add to `docker-compose.yml`) or a simple SQLite cache table. Eliminates the restart-unsafe gap and allows sharing cache between multiple backend replicas if ever scaled.

**O12 — AKShare health monitoring**
Add a background health-check job (e.g., daily at 09:00) that fetches a test quote for a known liquid stock (600519) and logs a prominent warning if it fails. This surfaces AKShare API breakage early rather than through silent estimate failures.

---

## 6. Development Backlog

Ordered by priority and effort. Items carry over from the original roadmap with updated status.

### Tier 1 — Do Next (P3 Engineering Polish)

| ID | Task | Effort | Files |
|----|------|--------|-------|
| B1 | Estimate API degradation (`degraded: true`, no error on market closed) | 2h | `fund.py`, `schemas.py`, `test_api_fund.py` |
| B2 | Manual refresh button on portfolio detail page | 1h | `PortfolioDetail.vue` |
| B3 | Sort portfolio fund list by est_change_pct / profit_pct | 1h | `PortfolioDetail.vue` |
| B4 | Cache `is_market_trading_today()` for 5 minutes | 30m | `market_data.py` |
| B5 | Fix timezone-naive `datetime.now()` in chart.py | 15m | `chart.py:154` |
| B6 | Input validation for `shares > 0`, `cost_nav > 0` | 30m | `portfolio_routes.py` |

### Tier 2 — High Value (P2 Differentiation)

| ID | Task | Effort | Files |
|----|------|--------|-------|
| B7 | Portfolio combined holdings overlap view | 4h | `portfolio_routes.py`, `PortfolioDetail.vue`, new test file |

### Tier 3 — Engineering Hygiene

| ID | Task | Effort | Files |
|----|------|--------|-------|
| B8 | Tests for `chart.py` endpoints | 3h | New `test_api_chart.py` |
| B9 | Migrate `_nav_history_cache` to `CacheService` | 1h | `market_data.py` |
| B10 | Move inline imports to module level in `chart.py` | 15m | `chart.py` |
| B11 | Add scheduler retry for failed stock fetches (exponential backoff) | 2h | `scheduler.py` |

### Tier 4 — Future / Optional

| ID | Task | Effort | Notes |
|----|------|--------|-------|
| B12 | Redis persistent cache | 4h | Only if deploying multiple backend replicas |
| B13 | AKShare health monitoring job | 2h | Nice-to-have for long-running production installs |
| B14 | Fund comparison view (overlay two fund NAV curves) | 4h | Useful for fund selection decisions |
| B15 | Email / push alerts when fund drops >X% | 6h | Requires notification infrastructure |

---

## 7. Recommended Implementation Order

```
Week 1: Quick wins + P3 polish
  Day 1:  B5 (timezone fix) + B10 (inline imports) + B4 (cache is_trading) — 1h total
  Day 2:  B1 (estimate degradation) — 2h
  Day 3:  B2 + B3 (refresh button + sorting) — 2h
  Day 4:  B6 (input validation) + B9 (nav_history_cache) — 1.5h

Week 2: P2 differentiation + test coverage
  Day 5–6: B7 (holdings overlap) — 4h
  Day 7–8: B8 (chart tests) — 3h
  Day 9:   B11 (scheduler retry) — 2h
```

---

## 8. Docs & Maintenance Notes

### 8.1 Documentation Status

| Document | Status | Notes |
|----------|--------|-------|
| `README.md` | ✅ Current | Accurate quick-start and API examples |
| `docs/DEPLOYMENT.md` | ✅ Current | Full Linux deployment guide with HTTPS and backup |
| `docs/ROADMAP.md` | ⚠️ Stale | Reflects Feb 18 state; P0/P1 all shipped. Should be updated to reflect current backlog. |
| `docs/plans/*.md` | — | 8 completed plans archived to `docs/archived/`; 2 active plans remain |

### 8.2 Archived Plans

The following implementation plans have been archived to `docs/archived/` because their features are fully shipped:

- `2026-02-15-fund-monitor-implementation.md` — original MVP implementation
- `2026-02-15-fund-realtime-estimate-design.md` — estimation engine design
- `2026-02-18-portfolio-fund-display.md` — P0-A fund display + P&L (shipped)
- `2026-02-18-fund-search.md` — P0-B fund search (shipped)
- `2026-02-18-portfolio-value-history.md` — P1-A history chart (shipped)
- `2026-02-18-daily-nav-refresh.md` — P1-B NAV refresh scheduler (shipped)
- `2026-02-19-containerization-design.md` — Docker design (shipped)
- `2026-02-19-containerization.md` — containerization implementation (shipped)

### 8.3 Active Plans

These plans remain in `docs/plans/` as they are not yet implemented:

- `2026-02-18-holdings-overlap-analysis.md` — P2-A combined holdings (backlog B7)
- `2026-02-18-engineering-improvements.md` — P3 degradation + refresh + sort (backlog B1-B3)

---

## 9. Key File Reference

| File | Purpose |
|------|---------|
| `backend/app/main.py` | App entry, lifespan, CORS, router mounts |
| `backend/app/config.py` | All configuration (DB URL, cache TTLs, trading hours) |
| `backend/app/api/fund.py` | Fund metadata, estimate, holdings, NAV refresh |
| `backend/app/api/portfolio_routes.py` | Portfolio CRUD, history |
| `backend/app/api/chart.py` | NAV history, intraday, CSI 300 index |
| `backend/app/api/search.py` | Fund search + setup |
| `backend/app/services/estimator.py` | NAV estimation algorithm (core logic) |
| `backend/app/services/market_data.py` | All AKShare integrations |
| `backend/app/services/cache.py` | In-memory TTL cache |
| `backend/app/tasks/scheduler.py` | Background jobs (quotes, snapshots, NAV refresh) |
| `frontend/src/views/PortfolioDetail.vue` | Main portfolio page (702 lines) |
| `frontend/src/components/NavChart.vue` | Fund NAV + index chart |
| `frontend/src/components/PortfolioChart.vue` | Portfolio history chart |
| `frontend/src/api/index.ts` | Typed API client (18 endpoints) |

---

*Generated: 2026-02-28 | Fund Monitor main @ 3ed65a2*
