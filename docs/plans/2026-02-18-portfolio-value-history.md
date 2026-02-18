# Portfolio Value History 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为每个投资组合绘制历史净值曲线（可选周期 7d/30d/ytd），让用户直观回顾组合总体表现趋势。

**Architecture:** 后端新增 `PortfolioSnapshot` 模型（每日收盘后存一条组合总估值），调度器在15:05触发快照写入，新增 `GET /api/portfolio/{id}/history?period=30d` 端点。前端新增 `PortfolioChart.vue` 组件，嵌入组合详情页。

**Tech Stack:** Python/FastAPI/SQLAlchemy/APScheduler（后端），Vue3/ECharts（前端）

---

### Task 1: 新增 PortfolioSnapshot 数据模型

**Files:**
- Modify: `backend/app/models/portfolio.py`
- Create: `backend/tests/test_portfolio_snapshot.py`

**Step 1: 编写失败测试**

创建 `backend/tests/test_portfolio_snapshot.py`：

```python
"""Tests for PortfolioSnapshot model."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.models.database import Base
from app.models.portfolio import Portfolio, PortfolioSnapshot


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_portfolio_snapshot(db):
    p = Portfolio(name="测试组合")
    db.add(p)
    await db.commit()

    snap = PortfolioSnapshot(
        portfolio_id=p.id,
        snapshot_date="2026-02-18",
        total_value=15000.0,
        total_cost=12000.0,
    )
    db.add(snap)
    await db.commit()

    assert snap.id is not None
    assert snap.total_value == 15000.0


@pytest.mark.asyncio
async def test_snapshot_profit_pct_computed(db):
    p = Portfolio(name="测试组合")
    db.add(p)
    await db.commit()

    snap = PortfolioSnapshot(
        portfolio_id=p.id,
        snapshot_date="2026-02-18",
        total_value=13200.0,
        total_cost=12000.0,
    )
    db.add(snap)
    await db.commit()

    # profit_pct = (13200 - 12000) / 12000 * 100 = 10.0
    assert abs(snap.profit_pct - 10.0) < 0.001
```

**Step 2: 运行测试，确认失败**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/test_portfolio_snapshot.py -v
```

预期：FAIL（`PortfolioSnapshot` 不存在）

**Step 3: 在 portfolio.py 中添加 PortfolioSnapshot 模型**

在 `backend/app/models/portfolio.py` 末尾追加：

```python
class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, index=True)
    snapshot_date: Mapped[str] = mapped_column(String(10), index=True)  # "YYYY-MM-DD"
    total_value: Mapped[float] = mapped_column(Float)
    total_cost: Mapped[float] = mapped_column(Float)

    @property
    def profit_pct(self) -> float:
        if self.total_cost <= 0:
            return 0.0
        return (self.total_value - self.total_cost) / self.total_cost * 100
```

**Step 4: 运行测试，确认通过**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/test_portfolio_snapshot.py -v
```

预期：2 个测试 PASS

**Step 5: 提交**

```bash
cd /Users/cc/fund-monitor
git add backend/app/models/portfolio.py backend/tests/test_portfolio_snapshot.py
git commit -m "feat: add PortfolioSnapshot model for daily portfolio value history"
```

---

### Task 2: 调度器中添加每日组合快照任务

**Files:**
- Modify: `backend/app/tasks/scheduler.py`

**Step 1: 在 scheduler.py 中添加快照任务**

在 `update_stock_quotes` 函数后追加：

```python
async def save_portfolio_snapshots():
    """At market close (15:05), save daily portfolio value snapshots."""
    try:
        async with async_session_factory() as session:
            from app.services.portfolio import portfolio_service
            from app.models.portfolio import PortfolioSnapshot
            from sqlalchemy import select

            portfolios = await portfolio_service.list_portfolios(session)
            today = datetime.now().strftime("%Y-%m-%d")

            for portfolio in portfolios:
                pf_list = await portfolio_service.get_portfolio_funds(session, portfolio.id)
                total_cost = 0.0
                total_value = 0.0

                for pf in pf_list:
                    fund = await fund_info_service.get_fund(session, pf.fund_code)
                    if not fund or not fund.last_nav:
                        continue

                    est_nav = fund.last_nav
                    holdings = await fund_info_service.get_holdings(session, pf.fund_code)
                    if holdings:
                        stock_codes = [h.stock_code for h in holdings]
                        quotes = {
                            k: stock_cache.get(f"stock:{k}")
                            for k in stock_codes
                            if stock_cache.get(f"stock:{k}") is not None
                        }
                        if quotes:
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

                    total_cost += pf.shares * pf.cost_nav
                    total_value += pf.shares * est_nav

                # Upsert: delete existing snapshot for today, then insert
                await session.execute(
                    __import__("sqlalchemy", fromlist=["delete"]).delete(PortfolioSnapshot).where(
                        PortfolioSnapshot.portfolio_id == portfolio.id,
                        PortfolioSnapshot.snapshot_date == today,
                    )
                )
                snapshot = PortfolioSnapshot(
                    portfolio_id=portfolio.id,
                    snapshot_date=today,
                    total_value=round(total_value, 2),
                    total_cost=round(total_cost, 2),
                )
                session.add(snapshot)

            await session.commit()
            logger.info(f"Saved portfolio snapshots for {len(portfolios)} portfolios")
    except Exception as e:
        logger.error(f"Failed to save portfolio snapshots: {e}")
```

在 `start_scheduler` 中注册新任务（追加在 `scheduler.add_job(update_stock_quotes...)` 之后）：

```python
    # Daily portfolio snapshot at market close
    from apscheduler.triggers.cron import CronTrigger
    scheduler.add_job(
        save_portfolio_snapshots,
        trigger=CronTrigger(hour=15, minute=5, day_of_week="mon-fri"),
        id="save_portfolio_snapshots",
        replace_existing=True,
    )
```

**Step 2: 验证调度器启动无报错**

```bash
cd /Users/cc/fund-monitor/backend
python -c "from app.tasks.scheduler import start_scheduler, stop_scheduler; start_scheduler(); stop_scheduler(); print('OK')"
```

预期：打印 `OK`，无异常

**Step 3: 提交**

```bash
cd /Users/cc/fund-monitor
git add backend/app/tasks/scheduler.py
git commit -m "feat: add daily portfolio snapshot task at market close (15:05)"
```

---

### Task 3: 组合历史查询 API

**Files:**
- Modify: `backend/app/api/portfolio_routes.py`
- Create: `backend/tests/test_api_portfolio_history.py`

**Step 1: 编写失败测试**

创建 `backend/tests/test_api_portfolio_history.py`：

```python
"""Tests for portfolio history endpoint."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.models.database import Base, get_db
from app.models.portfolio import Portfolio, PortfolioSnapshot


@pytest_asyncio.fixture
async def db_with_snapshots():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = override

    async with factory() as s:
        s.add(Portfolio(id=1, name="测试组合"))
        # 添加5天的快照
        for i, (date, val, cost) in enumerate([
            ("2026-02-10", 12100.0, 12000.0),
            ("2026-02-11", 12200.0, 12000.0),
            ("2026-02-12", 12050.0, 12000.0),
            ("2026-02-17", 12300.0, 12000.0),
            ("2026-02-18", 12500.0, 12000.0),
        ]):
            s.add(PortfolioSnapshot(portfolio_id=1, snapshot_date=date,
                                    total_value=val, total_cost=cost))
        await s.commit()

    yield

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_portfolio_history(db_with_snapshots):
    async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/1/history?period=30d")
    assert resp.status_code == 200
    data = resp.json()
    assert "dates" in data
    assert "values" in data
    assert "profit_pcts" in data
    assert len(data["dates"]) == 5


@pytest.mark.asyncio
async def test_portfolio_history_sorted_asc(db_with_snapshots):
    async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/1/history?period=30d")
    dates = resp.json()["dates"]
    assert dates == sorted(dates)


@pytest.mark.asyncio
async def test_portfolio_history_not_found():
    async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/999/history")
    assert resp.status_code == 404
```

**Step 2: 运行测试，确认失败**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/test_api_portfolio_history.py -v
```

预期：FAIL（路由不存在）

**Step 3: 在 portfolio_routes.py 中添加历史端点**

在文件末尾（`remove_fund_from_portfolio` 之后）追加：

```python
from datetime import datetime, timedelta
from sqlalchemy import select as sa_select


@router.get("/{portfolio_id}/history")
async def get_portfolio_history(
    portfolio_id: int,
    period: str = "30d",
    db: AsyncSession = Depends(get_db),
):
    """Get daily portfolio value snapshots for chart display."""
    from app.models.portfolio import PortfolioSnapshot

    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    today = datetime.now()
    period_map = {
        "7d": today - timedelta(days=7),
        "30d": today - timedelta(days=30),
        "ytd": datetime(today.year, 1, 1),
        "1y": today - timedelta(days=365),
    }
    cutoff = period_map.get(period, today - timedelta(days=30))
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    result = await db.execute(
        sa_select(PortfolioSnapshot)
        .where(
            PortfolioSnapshot.portfolio_id == portfolio_id,
            PortfolioSnapshot.snapshot_date >= cutoff_str,
        )
        .order_by(PortfolioSnapshot.snapshot_date)
    )
    snapshots = result.scalars().all()

    return {
        "dates": [s.snapshot_date for s in snapshots],
        "values": [s.total_value for s in snapshots],
        "costs": [s.total_cost for s in snapshots],
        "profit_pcts": [round(s.profit_pct, 4) for s in snapshots],
    }
```

**Step 4: 运行测试，确认通过**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/test_api_portfolio_history.py -v
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
git add backend/app/api/portfolio_routes.py backend/tests/test_api_portfolio_history.py
git commit -m "feat: add portfolio history endpoint for daily value snapshots"
```

---

### Task 4: 前端 PortfolioChart 组件

**Files:**
- Create: `frontend/src/components/PortfolioChart.vue`
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/views/PortfolioDetail.vue`

**Step 1: 在 api/index.ts 中添加历史接口**

```typescript
export interface PortfolioHistoryData {
  dates: string[]
  values: number[]
  costs: number[]
  profit_pcts: number[]
}

// 在 api 对象中追加：
getPortfolioHistory: (id: number, period: string) =>
  request<PortfolioHistoryData>(`/api/portfolio/${id}/history?period=${period}`),
```

**Step 2: 创建 PortfolioChart.vue**

创建 `frontend/src/components/PortfolioChart.vue`：

```vue
<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '../api'

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{ portfolioId: number }>()

const periods = [
  { key: '7d', label: '7日' },
  { key: '30d', label: '30日' },
  { key: 'ytd', label: '今年' },
  { key: '1y', label: '1年' },
]

const activePeriod = ref('30d')
const loading = ref(false)
const empty = ref(false)
const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function initChart() {
  if (chartRef.value && !chart) {
    chart = echarts.init(chartRef.value)
  }
}

async function loadData() {
  loading.value = true
  empty.value = false
  try {
    const data = await api.getPortfolioHistory(props.portfolioId, activePeriod.value)
    if (data.dates.length === 0) {
      empty.value = true
      return
    }

    await nextTick()
    initChart()
    if (!chart) return

    const lastProfitPct = data.profit_pcts[data.profit_pcts.length - 1] ?? 0
    const lineColor = lastProfitPct >= 0 ? '#ff4444' : '#00c853'
    const areaColor = lastProfitPct >= 0 ? 'rgba(255,68,68,0.08)' : 'rgba(0,200,83,0.08)'

    chart.setOption({
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          const d = params[0]?.axisValue || ''
          const i = params[0]?.dataIndex ?? 0
          const val = data.values[i] ?? 0
          const pct = data.profit_pcts[i] ?? 0
          const sign = pct >= 0 ? '+' : ''
          return `<div style="font-size:12px;color:#666">${d}</div>
                  <div>组合市值: <b>${val.toFixed(2)}</b></div>
                  <div>收益率: <b style="color:${lineColor}">${sign}${pct.toFixed(2)}%</b></div>`
        },
      },
      grid: { left: 60, right: 16, top: 20, bottom: 40 },
      xAxis: {
        type: 'category',
        data: data.dates,
        axisLabel: { fontSize: 11, color: '#999', rotate: 30 },
        axisLine: { lineStyle: { color: '#e8e8e8' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: { fontSize: 11, color: '#999', formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#f5f5f5' } },
      },
      series: [{
        name: '组合收益率',
        type: 'line',
        data: data.profit_pcts,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: lineColor, width: 2 },
        areaStyle: { color: areaColor },
      }],
    }, true)

    chart.resize()
  } catch {
    empty.value = true
  } finally {
    loading.value = false
  }
}

function handleResize() { chart?.resize() }

watch(activePeriod, loadData)
watch(() => props.portfolioId, loadData)

onMounted(() => {
  window.addEventListener('resize', handleResize)
  loadData()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="portfolio-chart">
    <div class="chart-title">组合净值走势</div>
    <div class="period-tabs">
      <button
        v-for="p in periods" :key="p.key"
        :class="['tab', { active: activePeriod === p.key }]"
        @click="activePeriod = p.key"
      >{{ p.label }}</button>
    </div>
    <div class="chart-container">
      <div v-if="loading" class="chart-overlay">加载中...</div>
      <div v-else-if="empty" class="chart-overlay">
        暂无历史数据<br>
        <span class="hint-text">每个交易日收盘后自动记录</span>
      </div>
      <div ref="chartRef" class="chart-canvas"></div>
    </div>
  </div>
</template>

<style scoped>
.portfolio-chart { margin: 16px 0; }

.chart-title {
  font-size: 14px;
  font-weight: 600;
  color: #333;
  margin-bottom: 8px;
}

.period-tabs {
  display: flex;
  gap: 0;
  margin-bottom: 12px;
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  overflow: hidden;
}

.tab {
  flex: 1;
  padding: 7px 0;
  background: #fff;
  border: none;
  border-right: 1px solid #e8e8e8;
  cursor: pointer;
  font-size: 13px;
  color: #666;
}
.tab:last-child { border-right: none; }
.tab.active { background: #1677ff; color: #fff; }

.chart-container {
  position: relative;
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  overflow: hidden;
}

.chart-canvas { width: 100%; height: 240px; }

.chart-overlay {
  position: absolute; inset: 0;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  color: #999; font-size: 14px; z-index: 1;
  background: #fff; gap: 6px;
}

.hint-text { font-size: 12px; color: #bbb; }
</style>
```

**Step 3: 在 PortfolioDetail.vue 中嵌入图表**

在 `<script setup>` 顶部追加导入：

```typescript
import PortfolioChart from '../components/PortfolioChart.vue'
```

在模板中 `.summary` div 之后、`.fund-list` 之前插入：

```html
<!-- Portfolio value history chart -->
<PortfolioChart v-if="portfolio" :portfolio-id="portfolioId" />
```

**Step 4: 手动验证**

在组合详情页顶部应出现「组合净值走势」图表区域。由于今天可能没有快照数据，图表显示「暂无历史数据」是正常的。可以手动调用一次快照接口验证：

```bash
# 直接 POST 触发快照（测试用）
curl -X POST http://localhost:8000/api/portfolio/1/snapshot-now 2>/dev/null || echo "endpoint not needed"
```

**Step 5: 提交**

```bash
cd /Users/cc/fund-monitor
git add frontend/src/components/PortfolioChart.vue \
        frontend/src/api/index.ts \
        frontend/src/views/PortfolioDetail.vue
git commit -m "feat: add PortfolioChart component with daily value history"
```

---

## 验收标准

- [ ] `PortfolioSnapshot` 表自动创建，可正常写入和查询
- [ ] 调度器在收盘时间（15:05）触发 `save_portfolio_snapshots`
- [ ] `GET /api/portfolio/{id}/history` 按 period 过滤返回快照数据
- [ ] 组合详情页顶部展示折线图，纵轴为收益率百分比
- [ ] 无数据时显示友好提示（"每个交易日收盘后自动记录"）
