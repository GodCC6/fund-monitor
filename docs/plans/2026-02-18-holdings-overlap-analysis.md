# Holdings Overlap Analysis 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 分析投资组合内各基金的持仓重叠情况，计算每只股票在整个组合层面的真实权重，帮助用户发现隐性集中风险（如：两只基金都重仓茅台，合并后实际暴露远超单基金数字）。

**Architecture:** 后端新增 `GET /api/portfolio/{id}/combined-holdings` 端点。算法：以每只基金的当前市值为权重，将各基金的持仓比例换算为组合层面的绝对权重，按股票合并汇总。前端在组合详情页新增「合并持仓」折叠区块。

**Tech Stack:** Python/FastAPI（后端），Vue3/TypeScript（前端）

---

## 算法说明

```
对于组合中每只基金 i：
  fund_weight_i = (shares_i × est_nav_i) / total_portfolio_value

对于基金 i 的每条持仓记录 j（holding_ratio_ij）：
  combined_weight_ij = holding_ratio_ij × fund_weight_i

对相同 stock_code 的 combined_weight 求和，即为该股票在整个组合中的真实权重。
```

覆盖率说明：若某基金无行情数据（est_nav = last_nav），使用 last_nav 作为保守估计。

---

### Task 1: 后端合并持仓计算端点

**Files:**
- Modify: `backend/app/api/portfolio_routes.py`
- Create: `backend/tests/test_api_combined_holdings.py`

**Step 1: 编写失败测试**

创建 `backend/tests/test_api_combined_holdings.py`：

```python
"""Tests for portfolio combined holdings overlap endpoint."""

import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.models.database import Base, get_db
from app.models.fund import Fund, FundHolding
from app.models.portfolio import Portfolio, PortfolioFund


@pytest_asyncio.fixture
async def db_two_funds():
    """Two funds both holding 茅台, one also holding 五粮液."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = override

    async with factory() as s:
        # Fund A: 70% 茅台, 20% 五粮液
        s.add(Fund(fund_code="000001", fund_name="基金A", fund_type="股票型",
                   last_nav=2.0, nav_date="2026-02-17"))
        s.add(FundHolding(fund_code="000001", stock_code="600519",
                          stock_name="贵州茅台", holding_ratio=0.07, report_date="2025-12-31"))
        s.add(FundHolding(fund_code="000001", stock_code="000858",
                          stock_name="五粮液", holding_ratio=0.02, report_date="2025-12-31"))

        # Fund B: 60% 茅台
        s.add(Fund(fund_code="000002", fund_name="基金B", fund_type="股票型",
                   last_nav=1.5, nav_date="2026-02-17"))
        s.add(FundHolding(fund_code="000002", stock_code="600519",
                          stock_name="贵州茅台", holding_ratio=0.06, report_date="2025-12-31"))

        # Portfolio: 1000 share of A (value=2000), 2000 shares of B (value=3000)
        s.add(Portfolio(id=1, name="测试组合"))
        s.add(PortfolioFund(portfolio_id=1, fund_code="000001", shares=1000.0, cost_nav=1.8))
        s.add(PortfolioFund(portfolio_id=1, fund_code="000002", shares=2000.0, cost_nav=1.4))
        await s.commit()

    yield

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_combined_holdings_endpoint_exists(db_two_funds):
    async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/1/combined-holdings")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_combined_holdings_merges_same_stock(db_two_funds):
    """茅台 should appear once with combined weight from both funds."""
    async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/1/combined-holdings")
    holdings = resp.json()["holdings"]
    codes = [h["stock_code"] for h in holdings]
    assert codes.count("600519") == 1  # 合并为一条


@pytest.mark.asyncio
async def test_combined_holdings_weight_calculation(db_two_funds):
    """
    Portfolio total value = 1000*2.0 + 2000*1.5 = 5000
    Fund A weight = 2000/5000 = 0.4
    Fund B weight = 3000/5000 = 0.6
    茅台 combined = 0.07*0.4 + 0.06*0.6 = 0.028 + 0.036 = 0.064
    五粮液 combined = 0.02*0.4 = 0.008
    """
    async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/1/combined-holdings")
    holdings = {h["stock_code"]: h for h in resp.json()["holdings"]}
    assert abs(holdings["600519"]["combined_weight"] - 0.064) < 0.001
    assert abs(holdings["000858"]["combined_weight"] - 0.008) < 0.001


@pytest.mark.asyncio
async def test_combined_holdings_sorted_by_weight(db_two_funds):
    """Holdings should be sorted by combined_weight descending."""
    async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/1/combined-holdings")
    weights = [h["combined_weight"] for h in resp.json()["holdings"]]
    assert weights == sorted(weights, reverse=True)


@pytest.mark.asyncio
async def test_combined_holdings_not_found():
    async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/portfolio/999/combined-holdings")
    assert resp.status_code == 404
```

**Step 2: 运行测试，确认失败**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/test_api_combined_holdings.py -v
```

预期：FAIL（路由不存在）

**Step 3: 在 portfolio_routes.py 中实现端点**

在文件末尾追加：

```python
@router.get("/{portfolio_id}/combined-holdings")
async def get_combined_holdings(portfolio_id: int, db: AsyncSession = Depends(get_db)):
    """Aggregate holdings across all funds weighted by portfolio allocation.

    Returns stocks sorted by combined_weight descending, with contributions
    per fund for each stock.
    """
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    pf_list = await portfolio_service.get_portfolio_funds(db, portfolio_id)

    # Step 1: Compute fund market values
    fund_values: dict[str, float] = {}
    for pf in pf_list:
        fund = await fund_info_service.get_fund(db, pf.fund_code)
        nav = fund.last_nav if fund and fund.last_nav else 0.0
        fund_values[pf.fund_code] = pf.shares * nav

    total_value = sum(fund_values.values())
    if total_value <= 0:
        return {"holdings": [], "total_value": 0, "coverage": 0}

    # Step 2: For each fund, weight its holdings by fund's share of portfolio
    # stock_code -> {stock_name, combined_weight, by_fund: [{fund_code, fund_name, weight}]}
    combined: dict[str, dict] = {}

    for pf in pf_list:
        fund = await fund_info_service.get_fund(db, pf.fund_code)
        fund_weight = fund_values[pf.fund_code] / total_value
        holdings = await fund_info_service.get_holdings(db, pf.fund_code)

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

    # Step 3: Sort by combined_weight descending, round
    result = sorted(combined.values(), key=lambda x: x["combined_weight"], reverse=True)
    for item in result:
        item["combined_weight"] = round(item["combined_weight"], 4)

    total_coverage = sum(h["combined_weight"] for h in result)

    return {
        "holdings": result,
        "total_value": round(total_value, 2),
        "coverage": round(total_coverage, 4),
    }
```

**Step 4: 运行测试**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/test_api_combined_holdings.py -v
```

预期：5 个测试 PASS

**Step 5: 运行全量测试**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/ -v --tb=short
```

**Step 6: 提交**

```bash
cd /Users/cc/fund-monitor
git add backend/app/api/portfolio_routes.py backend/tests/test_api_combined_holdings.py
git commit -m "feat: add combined-holdings endpoint for portfolio overlap analysis"
```

---

### Task 2: 前端合并持仓展示

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/views/PortfolioDetail.vue`

**Step 1: 在 api/index.ts 中添加接口**

```typescript
export interface CombinedHolding {
  stock_code: string
  stock_name: string
  combined_weight: number
  by_fund: Array<{
    fund_code: string
    fund_name: string
    fund_weight: number
    holding_ratio: number
    contribution: number
  }>
}

export interface CombinedHoldingsData {
  holdings: CombinedHolding[]
  total_value: number
  coverage: number
}

// 在 api 对象中追加：
getCombinedHoldings: (id: number) =>
  request<CombinedHoldingsData>(`/api/portfolio/${id}/combined-holdings`),
```

**Step 2: 在 PortfolioDetail.vue 中添加合并持仓区块**

在 `<script setup>` 中追加状态：

```typescript
const combinedHoldings = ref<CombinedHoldingsData | null>(null)
const showCombined = ref(false)
const combinedLoading = ref(false)

async function loadCombinedHoldings() {
  if (combinedHoldings.value) {
    showCombined.value = !showCombined.value
    return
  }
  combinedLoading.value = true
  try {
    combinedHoldings.value = await api.getCombinedHoldings(portfolioId.value)
    showCombined.value = true
  } catch {
    // silently fail
  } finally {
    combinedLoading.value = false
  }
}
```

在模板中，基金列表之后、添加基金区块之前插入：

```html
<!-- Combined Holdings Analysis -->
<div class="combined-section">
  <button class="combined-toggle" @click="loadCombinedHoldings">
    <span>合并持仓分析</span>
    <span v-if="combinedLoading">加载中...</span>
    <span v-else>{{ showCombined ? '▲' : '▼' }}</span>
  </button>

  <div v-if="showCombined && combinedHoldings" class="combined-body">
    <div class="combined-meta">
      覆盖率 {{ (combinedHoldings.coverage * 100).toFixed(1) }}%
      · 组合总市值 {{ combinedHoldings.total_value.toFixed(2) }}
    </div>
    <div class="combined-header">
      <span>股票</span>
      <span>合并权重</span>
      <span>风险提示</span>
    </div>
    <div
      v-for="h in combinedHoldings.holdings"
      :key="h.stock_code"
      class="combined-row"
    >
      <span class="c-name">{{ h.stock_name }}<small>{{ h.stock_code }}</small></span>
      <span class="c-weight">{{ (h.combined_weight * 100).toFixed(2) }}%</span>
      <span class="c-risk">
        <span v-if="h.combined_weight > 0.05" class="risk-high">集中</span>
        <span v-else-if="h.combined_weight > 0.03" class="risk-mid">偏重</span>
      </span>
    </div>
    <div class="combined-hint">
      权重 > 5% 标记为「集中」，可能带来集中风险
    </div>
  </div>
</div>
```

在 `<style scoped>` 末尾追加：

```css
.combined-section {
  margin-bottom: 16px;
}

.combined-toggle {
  width: 100%;
  padding: 12px 16px;
  background: #f8f8f8;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  color: #333;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.combined-body {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-top: none;
  border-radius: 0 0 8px 8px;
  padding: 12px 16px;
}

.combined-meta {
  font-size: 12px;
  color: #999;
  margin-bottom: 10px;
}

.combined-header {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  font-size: 11px;
  color: #999;
  padding: 4px 0;
  border-bottom: 1px solid #f0f0f0;
}

.combined-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  padding: 8px 0;
  font-size: 13px;
  border-bottom: 1px solid #f8f8f8;
  align-items: center;
}

.c-name {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.c-name small {
  font-size: 11px;
  color: #bbb;
}

.c-weight {
  font-weight: 500;
}

.risk-high {
  font-size: 11px;
  background: #fff3e0;
  color: #e65100;
  padding: 2px 6px;
  border-radius: 3px;
}

.risk-mid {
  font-size: 11px;
  background: #fff8e1;
  color: #f57f17;
  padding: 2px 6px;
  border-radius: 3px;
}

.combined-hint {
  font-size: 11px;
  color: #bbb;
  margin-top: 8px;
}
```

**Step 3: 手动验证**

打开组合详情页，点击「合并持仓分析」按钮，展开后应显示：
- 各股票的合并权重
- 权重 > 5% 的标注「集中」
- 覆盖率和组合总市值

**Step 4: 提交**

```bash
cd /Users/cc/fund-monitor
git add frontend/src/api/index.ts frontend/src/views/PortfolioDetail.vue
git commit -m "feat: add combined holdings overlap analysis in portfolio detail"
```

---

## 验收标准

- [ ] 两只基金同时持有的股票在结果中合并为一条，权重正确相加
- [ ] 结果按 `combined_weight` 降序排列
- [ ] 权重计算：以各基金当前市值（shares × last_nav）为权重因子
- [ ] 前端「合并持仓」折叠展示，首次点击触发请求，后续切换仅显示/隐藏
- [ ] 权重 > 5% 显示「集中」橙色标签
