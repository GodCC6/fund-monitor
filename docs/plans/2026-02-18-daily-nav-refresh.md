# Daily NAV Refresh & Holdings Staleness 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 每日20:30自动刷新所有跟踪基金的官方净值，并在前端展示持仓数据的时效性，避免用户使用过期数据做决策。

**Architecture:** 调度器新增 CronTrigger 任务，在20:30调用 `market_data_service.get_fund_nav()` 更新数据库中所有基金的 `last_nav`/`nav_date`。前端根据 `nav_date` 和 `holdings_date` 计算时效，超过3个自然日显示黄色警告。

**Tech Stack:** Python/APScheduler/akshare（后端），Vue3/TypeScript（前端）

---

### Task 1: 调度器添加每日 NAV 刷新任务

**Files:**
- Modify: `backend/app/tasks/scheduler.py`

**Step 1: 在 scheduler.py 中追加刷新函数**

在 `save_portfolio_snapshots` 函数（或 `update_stock_quotes`）之后追加：

```python
async def refresh_all_fund_navs():
    """After market close (~20:30), fetch official NAV for all tracked funds."""
    try:
        async with async_session_factory() as session:
            funds = await fund_info_service.get_all_funds(session)
            updated = 0
            for fund in funds:
                nav_data = market_data_service.get_fund_nav(fund.fund_code)
                if nav_data and nav_data["nav_date"] != fund.nav_date:
                    fund.last_nav = nav_data["nav"]
                    fund.nav_date = nav_data["nav_date"]
                    fund.updated_at = datetime.now().isoformat()
                    updated += 1
            await session.commit()
            logger.info(f"Refreshed official NAV for {updated}/{len(funds)} funds")
    except Exception as e:
        logger.error(f"Failed to refresh fund NAVs: {e}")
```

**Step 2: 在 start_scheduler 中注册新任务**

在 `start_scheduler` 函数中，已有任务注册之后追加：

```python
    scheduler.add_job(
        refresh_all_fund_navs,
        trigger=CronTrigger(hour=20, minute=30, day_of_week="mon-fri"),
        id="refresh_all_fund_navs",
        replace_existing=True,
    )
```

（如果 `CronTrigger` 尚未导入，在文件顶部补上 `from apscheduler.triggers.cron import CronTrigger`）

**Step 3: 验证调度器可正常启动**

```bash
cd /Users/cc/fund-monitor/backend
python -c "
from app.tasks.scheduler import start_scheduler, stop_scheduler
start_scheduler()
jobs = [j.id for j in __import__('app.tasks.scheduler', fromlist=['scheduler']).scheduler.get_jobs()]
print('Jobs:', jobs)
stop_scheduler()
"
```

预期输出包含 `refresh_all_fund_navs`

**Step 4: 提交**

```bash
cd /Users/cc/fund-monitor
git add backend/app/tasks/scheduler.py
git commit -m "feat: add daily 20:30 scheduler task to refresh official fund NAVs"
```

---

### Task 2: 手动触发 NAV 刷新的 API 端点（辅助功能）

用户偶尔需要手动刷新某只基金的净值（如节假日后），提供一个 POST 端点。

**Files:**
- Modify: `backend/app/api/fund.py`
- Create: `backend/tests/test_api_nav_refresh.py`

**Step 1: 编写失败测试**

创建 `backend/tests/test_api_nav_refresh.py`：

```python
"""Tests for manual NAV refresh endpoint."""

import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.models.database import Base, get_db
from app.models.fund import Fund


@pytest_asyncio.fixture
async def db_with_fund():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    async with factory() as s:
        s.add(Fund(fund_code="000001", fund_name="华夏成长", fund_type="混合型",
                   last_nav=1.5, nav_date="2026-02-14"))
        await s.commit()
    yield
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_refresh_nav_updates_db(db_with_fund):
    mock_nav = {"nav": 1.55, "nav_date": "2026-02-18", "acc_nav": 3.1}
    with patch("app.api.fund.market_data_service.get_fund_nav", return_value=mock_nav):
        async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/fund/000001/refresh-nav")
    assert resp.status_code == 200
    data = resp.json()
    assert data["nav"] == 1.55
    assert data["nav_date"] == "2026-02-18"


@pytest.mark.asyncio
async def test_refresh_nav_fund_not_found(db_with_fund):
    async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/fund/999999/refresh-nav")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_refresh_nav_source_unavailable(db_with_fund):
    with patch("app.api.fund.market_data_service.get_fund_nav", return_value=None):
        async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/fund/000001/refresh-nav")
    assert resp.status_code == 503
```

**Step 2: 运行测试，确认失败**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/test_api_nav_refresh.py -v
```

**Step 3: 在 fund.py 中添加端点**

在 `backend/app/api/fund.py` 末尾追加：

```python
@router.post("/{fund_code}/refresh-nav")
async def refresh_nav(fund_code: str, db: AsyncSession = Depends(get_db)):
    """Manually trigger NAV refresh from data source."""
    fund = await fund_info_service.get_fund(db, fund_code)
    if fund is None:
        raise HTTPException(status_code=404, detail="Fund not found")

    nav_data = market_data_service.get_fund_nav(fund_code)
    if nav_data is None:
        raise HTTPException(status_code=503, detail="NAV data source unavailable")

    await fund_info_service.update_nav(db, fund_code, nav_data["nav"], nav_data["nav_date"])
    return {"fund_code": fund_code, "nav": nav_data["nav"], "nav_date": nav_data["nav_date"]}
```

**Step 4: 运行测试**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/test_api_nav_refresh.py -v
```

预期：3 个测试 PASS

**Step 5: 运行全量测试**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/ -v --tb=short
```

**Step 6: 提交**

```bash
cd /Users/cc/fund-monitor
git add backend/app/api/fund.py backend/tests/test_api_nav_refresh.py
git commit -m "feat: add POST /api/fund/{code}/refresh-nav manual NAV refresh endpoint"
```

---

### Task 3: 前端时效性提示

**Files:**
- Modify: `frontend/src/views/FundDetail.vue`
- Modify: `frontend/src/views/PortfolioDetail.vue`

**Step 1: 创建工具函数 — 时效性判断**

在 `FundDetail.vue` 的 `<script setup>` 中追加（也可提取为公共 composable，但目前两个页面各自实现即可）：

```typescript
function navStaleDays(navDate: string | null): number {
  if (!navDate) return 999
  const d = new Date(navDate)
  const now = new Date()
  return Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24))
}

function isNavStale(navDate: string | null): boolean {
  return navStaleDays(navDate) > 3
}
```

**Step 2: 在 FundDetail.vue 中添加净值时效提示**

在基金信息卡片的「最新净值」行（`fund.nav_date` 附近）修改为：

```html
<div v-if="fund.last_nav != null" class="info-row">
  <span class="label">最新净值</span>
  <span>
    {{ fund.last_nav }}
    <span class="nav-date" :class="{ stale: isNavStale(fund.nav_date) }">
      {{ fund.nav_date }}
      <span v-if="isNavStale(fund.nav_date)" class="stale-hint">
        ⚠ 数据已 {{ navStaleDays(fund.nav_date) }} 天未更新
      </span>
    </span>
  </span>
</div>
```

在 `<style scoped>` 中追加：

```css
.nav-date { font-size: 12px; color: #999; margin-left: 6px; }
.nav-date.stale { color: #ff9800; }
.stale-hint { font-size: 11px; margin-left: 4px; }
```

**Step 3: 在 FundDetail.vue 持仓明细区域添加持仓时效提示**

在 `.holdings` 标题行附近追加（`holdings_date` 来自 estimate.details 的首条，或者可以从 holdings API 获取）：

在 `estimate.details` 渲染之前插入：

```html
<div v-if="estimate.details.length > 0" class="holdings">
  <div class="holdings-title-row">
    <h4>持仓明细</h4>
    <!-- 持仓报告日期提示 -->
    <span v-if="estimate.details[0]" class="holdings-report-date">
      <!-- holdings details 中无 report_date，此处显示静态提示 -->
      数据来源：季度报告
    </span>
  </div>
  <!-- ... 已有的 holdings-header 和 holding-row ... -->
</div>
```

**Step 4: 在 PortfolioDetail.vue 组合基金行中高亮过期持仓**

（此步基于 P0-A 已实施，`f.holdings_date` 可用）

找到 `.fund-meta` 中的 `holdings_date` 显示，替换为：

```html
<span
  v-if="f.holdings_date"
  class="holdings-date"
  :class="{ 'holdings-stale': isHoldingsStale(f.holdings_date) }"
>
  持仓截至 {{ f.holdings_date }}
  <span v-if="isHoldingsStale(f.holdings_date)"> ⚠</span>
</span>
```

在 `<script setup>` 追加：

```typescript
function isHoldingsStale(date: string | null): boolean {
  if (!date) return false
  const d = new Date(date)
  const now = new Date()
  const days = Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24))
  return days > 90  // 超过3个月认为过期
}
```

在 `<style scoped>` 追加：

```css
.holdings-stale { color: #ff9800 !important; }
```

**Step 5: 手动验证**

1. 打开任意基金详情，查看净值日期旁是否正确显示时效提示
2. 手动将系统时间改到2026年5月，或者将 `nav_date` 设为旧日期，确认警告触发

**Step 6: 提交**

```bash
cd /Users/cc/fund-monitor
git add frontend/src/views/FundDetail.vue frontend/src/views/PortfolioDetail.vue
git commit -m "feat: show nav staleness warning when data older than 3 days"
```

---

## 验收标准

- [ ] 调度器 jobs 中包含 `refresh_all_fund_navs`（CronTrigger, 20:30 工作日）
- [ ] `POST /api/fund/{code}/refresh-nav` 成功更新数据库并返回最新净值
- [ ] 前端基金详情页，净值超过3天未更新时显示橙色 `⚠ 数据已X天未更新`
- [ ] 持仓数据超过90天（一个季度）时显示橙色 `⚠`
- [ ] 全量测试无回归
