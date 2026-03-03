# Fund Monitor — Product Roadmap

> Last updated: 2026-03-03
> Based on full codebase review at main @ `3ed65a2` plus B4/B5 fixes and B1/B2/B3/B6 implementation

---

## Current Status

### Completed Features

| Module | Feature | Shipped |
|--------|---------|---------|
| Estimation engine | Weighted-holdings real-time NAV estimate, coverage % | ✅ |
| Scheduler | 30s intraday quote refresh + snapshot persistence | ✅ |
| Scheduler | Daily official NAV refresh at 20:30 CST | ✅ |
| Portfolio CRUD | Create, rename, add/remove funds; cost basis + P&L | ✅ |
| Fund search | Name / code search, cached 1 hour | ✅ |
| Portfolio history chart | On-the-fly nav history, period filtering, carry-forward | ✅ |
| CSI 300 historical chart | Sina Finance source (East Money kline blocked) | ✅ |
| CSI 300 intraday chart | Direct East Money trends2 API with browser headers | ✅ |
| Fund NAV history chart | Multi-period (7d / 30d / ytd / 1y / 3y) | ✅ |
| Fund intraday chart | Snapshot dedup + base_nav anchoring (no jump on refresh) | ✅ |
| Holdings staleness warning | Frontend badge when holdings > 90 days old | ✅ |
| Stock code normalization | 6-digit zero-padded across cache, scheduler, fund API | ✅ |
| Docker Compose deployment | Healthcheck, volume-mounted SQLite, Caddy HTTPS guide | ✅ |
| B4: Cache is_market_trading_today() | 5-minute TTL avoids HTTP call on every /estimate | ✅ |
| B5: Timezone-aware datetime in chart.py | datetime.now() → datetime.now(_CST) (line 154) | ✅ |
| B6: Input validation on fund add | shares > 0, cost_nav > 0 with 400 errors | ✅ |
| B3: Sort portfolio fund list | By est_change_pct / profit_pct, client-side | ✅ |
| B2: Manual refresh button | Portfolio detail page, calls load(), disabled while loading | ✅ |
| B1: Estimate API graceful degradation | degraded: true flag, no error banner when market closed | ✅ |
| B7: Portfolio combined holdings overlap | `GET /combined-holdings` endpoint + collapsible UI with risk badges | ✅ |
| B10: Inline imports moved to module level | `chart.py` imports at module level | ✅ |

---

## Development Backlog

Ordered by priority and effort. Source: `docs/fund-monitor-review.md` (2026-02-28).

### Tier 1 — Engineering Polish (P3)

| ID | Task | Effort | Files | Status |
|----|------|--------|-------|--------|
| B1 | Estimate API graceful degradation (`degraded: true`, no error banner when market closed / quotes unavailable) | 2h | `fund.py`, `schemas.py`, `test_api_fund.py` | ✅ Done |
| B2 | Manual refresh button on portfolio detail page | 1h | `PortfolioDetail.vue` | ✅ Done |
| B3 | Sort portfolio fund list by est_change_pct / profit_pct | 1h | `PortfolioDetail.vue` | ✅ Done |
| B6 | Input validation: `shares > 0`, `cost_nav > 0` on fund add | 30m | `portfolio_routes.py` | ✅ Done |

### Tier 2 — High Value (P2 Differentiation)

| ID | Task | Effort | Files | Status |
|----|------|--------|-------|--------|
| B7 | Portfolio combined holdings overlap view | 4h | `portfolio_routes.py`, `PortfolioDetail.vue`, new test file | ✅ Done |

### Tier 3 — Engineering Hygiene

| ID | Task | Effort | Files |
|----|------|--------|-------|
| B8 | Tests for `chart.py` endpoints | 3h | New `test_api_chart.py` | ✅ Done |
| B9 | Migrate `_nav_history_cache` to shared `CacheService` | 1h | `market_data.py` |
| B10 | Move inline `import akshare` / `import requests` to module level in `chart.py` | 15m | `chart.py` | ✅ Done |
| B8-infra | pytest `asyncio_mode=auto` + conftest.py safeguard (in-memory DB for all async tests) | 1h | `pyproject.toml`, `tests/conftest.py` | ✅ Done |
| B11 | Scheduler retry with exponential backoff for failed stock fetches | 2h | `scheduler.py` |

### Tier 4 — Future / Optional

| ID | Task | Effort | Notes |
|----|------|--------|-------|
| B12 | Redis persistent cache | 4h | Only if deploying multiple backend replicas |
| B13 | AKShare health monitoring job (daily probe + warning log) | 2h | Surface API breakage early |
| B14 | Fund comparison view (overlay two fund NAV curves) | 4h | Useful for fund selection decisions |
| B15 | Email / push alerts when fund drops > X% | 6h | Requires notification infrastructure |

---

## Architecture Notes

- **Backend:** FastAPI + SQLite + akshare + APScheduler
- **Frontend:** Vue 3 Composition API + TypeScript, no UI library
- **Tests:** pytest + pytest-asyncio — all new API endpoints require tests
- **DB migrations:** Add tables in `models/`, auto-created via `Base.metadata.create_all`
- **A-share colour convention:** up = `#ff4444` (red), down = `#00c853` (green)
- **Estimate badge:** all non-official NAVs must show an orange `估` badge

---

## Documentation

| Document | Status |
|----------|--------|
| `README.md` | ✅ Current |
| `docs/DEPLOYMENT.md` | ✅ Current |
| `docs/ROADMAP.md` | ✅ Updated 2026-02-28 |
| `docs/fund-monitor-review.md` | ✅ Full review 2026-02-28 |
| `docs/plans/2026-02-18-holdings-overlap-analysis.md` | Active — B7 not yet implemented |
| `docs/plans/2026-02-18-engineering-improvements.md` | ✅ B1/B2/B3/B6 implemented 2026-03-03 |
| `docs/archived/` | 8 completed implementation plans |
