# Portfolio Fund Display 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在组合详情页中展示每只基金的名称、实时估算涨跌、当前市值、个基盈亏，让用户一眼看清各基金状态。

**Architecture:** 后端 `PortfolioFundResponse` schema 扩展新字段，`get_portfolio_detail` 已有计算逻辑但丢弃了结果，直接补全填充即可。前端更新 `PortfolioDetail` 接口和渲染列表。

**Tech Stack:** Python/FastAPI/Pydantic（后端），Vue3/TypeScript（前端）

---

## 现状说明

`backend/app/api/portfolio_routes.py` 的 `get_portfolio_detail` 函数已经计算了每只基金的 `est_nav`、`cost`、`current_value`，但只把 `fund_code/shares/cost_nav` 放进了 `PortfolioFundResponse`，其余数据被丢弃。

`PortfolioDetail.funds` 数组中每个元素只有三个字段，前端只能显示代码+份额，无法显示名称或估值变化。

---

### Task 1: 扩展后端 Schema

**Files:**
- Modify: `backend/app/api/schemas.py`

**Step 1: 阅读现有 PortfolioFundResponse**

打开 `backend/app/api/schemas.py`，找到 `PortfolioFundResponse` 类（第51行）：

```python
class PortfolioFundResponse(BaseModel):
    fund_code: str
    shares: float
    cost_nav: float
```

**Step 2: 替换为扩展版本**

将 `PortfolioFundResponse` 替换为：

```python
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
```

字段说明：
- `est_change_pct`：相对昨日净值的估算涨跌幅（百分比，如 +2.3）
- `coverage`：持仓覆盖率（0~1）
- `holdings_date`：持仓报告日期，如 `"2025-12-31"`
- `profit_pct`：相对持仓成本的收益率（百分比）

**Step 3: 无需单独运行测试**（schema 是纯数据类，下一步的路由测试会覆盖）

**Step 4: 提交**

```bash
cd /Users/cc/fund-monitor
git add backend/app/api/schemas.py
git commit -m "feat: extend PortfolioFundResponse with per-fund P&L fields"
```

---

### Task 2: 更新路由逻辑，填充新字段

**Files:**
- Modify: `backend/app/api/portfolio_routes.py`

**Step 1: 编写失败测试**

创建/追加 `backend/tests/test_api_portfolio_fund_display.py`：

```python
"""Tests for portfolio fund detail display (names, per-fund P&L)."""

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
async def db_with_data():
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
                   last_nav=2.0, nav_date="2026-02-17"))
        s.add(FundHolding(fund_code="000001", stock_code="600519",
                          stock_name="贵州茅台", holding_ratio=0.1, report_date="2025-12-31"))
        s.add(Portfolio(id=1, name="测试组合"))
        s.add(PortfolioFund(portfolio_id=1, fund_code="000001", shares=1000.0, cost_nav=1.8))
        await s.commit()

    yield

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_portfolio_fund_has_name(db_with_data):
    mock_quotes = {"600519": {"price": 1900.0, "change_pct": 2.0, "name": "贵州茅台"}}
    with patch("app.api.portfolio_routes.market_data_service.get_stock_quotes",
               return_value=mock_quotes):
        async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/portfolio/1")
    assert resp.status_code == 200
    fund = resp.json()["funds"][0]
    assert fund["fund_name"] == "华夏成长"


@pytest.mark.asyncio
async def test_portfolio_fund_has_est_change_pct(db_with_data):
    mock_quotes = {"600519": {"price": 1900.0, "change_pct": 2.0, "name": "贵州茅台"}}
    with patch("app.api.portfolio_routes.market_data_service.get_stock_quotes",
               return_value=mock_quotes):
        async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/portfolio/1")
    fund = resp.json()["funds"][0]
    # est_change_pct = 0.1 * 2.0 = 0.2
    assert abs(fund["est_change_pct"] - 0.2) < 0.001
    assert fund["coverage"] == pytest.approx(0.1, abs=0.001)


@pytest.mark.asyncio
async def test_portfolio_fund_profit_pct(db_with_data):
    """profit_pct = (est_nav - cost_nav) / cost_nav * 100"""
    mock_quotes = {"600519": {"price": 1900.0, "change_pct": 0.0, "name": "贵州茅台"}}
    with patch("app.api.portfolio_routes.market_data_service.get_stock_quotes",
               return_value=mock_quotes):
        async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/portfolio/1")
    fund = resp.json()["funds"][0]
    # est_nav ≈ last_nav = 2.0, cost_nav = 1.8
    expected_profit_pct = (2.0 - 1.8) / 1.8 * 100
    assert abs(fund["profit_pct"] - expected_profit_pct) < 0.01


@pytest.mark.asyncio
async def test_portfolio_fund_holdings_date(db_with_data):
    mock_quotes = {}
    with patch("app.api.portfolio_routes.market_data_service.get_stock_quotes",
               return_value=mock_quotes):
        async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/portfolio/1")
    fund = resp.json()["funds"][0]
    assert fund["holdings_date"] == "2025-12-31"
```

**Step 2: 运行测试，确认失败**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/test_api_portfolio_fund_display.py -v
```

预期：4 个测试 FAIL（`fund_name` 字段不存在）

**Step 3: 更新路由逻辑**

修改 `backend/app/api/portfolio_routes.py` 中的 `get_portfolio_detail`。

将现有循环替换为（完整新版本）：

```python
@router.get("/{portfolio_id}", response_model=PortfolioDetailResponse)
async def get_portfolio_detail(portfolio_id: int, db: AsyncSession = Depends(get_db)):
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    pf_list = await portfolio_service.get_portfolio_funds(db, portfolio_id)

    total_cost = 0.0
    total_estimate = 0.0
    funds_response = []

    for pf in pf_list:
        fund = await fund_info_service.get_fund(db, pf.fund_code)
        last_nav = fund.last_nav if fund and fund.last_nav else 0.0
        fund_name = fund.fund_name if fund else pf.fund_code
        est_nav = last_nav
        est_change_pct = 0.0
        coverage = 0.0
        holdings_date: str | None = None

        # Try real-time estimate
        if fund and fund.last_nav:
            holdings = await fund_info_service.get_holdings(db, pf.fund_code)
            if holdings:
                holdings_date = holdings[0].report_date
                stock_codes = [h.stock_code for h in holdings]
                quotes = market_data_service.get_stock_quotes(stock_codes)
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
```

**Step 4: 运行测试，确认通过**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/test_api_portfolio_fund_display.py -v
```

预期：4 个测试 PASS

**Step 5: 运行全量测试，确认没有回归**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/ -v --tb=short
```

**Step 6: 提交**

```bash
cd /Users/cc/fund-monitor
git add backend/app/api/portfolio_routes.py backend/tests/test_api_portfolio_fund_display.py
git commit -m "feat: populate per-fund name, est_change_pct, profit in portfolio detail"
```

---

### Task 3: 前端更新接口类型和组合基金列表渲染

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/views/PortfolioDetail.vue`

**Step 1: 更新 api/index.ts 中的 PortfolioDetail 接口**

找到 `PortfolioDetail` 接口中的 `funds` 数组类型，替换为：

```typescript
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
```

**Step 2: 更新 PortfolioDetail.vue 的基金列表渲染**

找到 `.fund-list` 内的 `v-for` 循环，将 fund-row 内容替换为包含名称和估值的新布局：

```html
<div v-for="f in portfolio.funds" :key="f.fund_code" class="fund-row">
  <div class="fund-main" @click="router.push(`/fund/${f.fund_code}`)">
    <div class="fund-header">
      <span class="fund-name">{{ f.fund_name }}</span>
      <span class="fund-code-tag">{{ f.fund_code }}</span>
    </div>
    <div class="fund-est">
      <span class="est-nav">{{ f.est_nav.toFixed(4) }}</span>
      <span class="badge">估</span>
      <span :class="pctClass(f.est_change_pct)" class="est-pct">
        {{ formatPct(f.est_change_pct) }}
      </span>
    </div>
    <div class="fund-pl">
      <span class="pl-label">持仓收益</span>
      <span :class="pctClass(f.profit)" class="pl-value">
        {{ f.profit >= 0 ? '+' : '' }}{{ f.profit.toFixed(2) }}
      </span>
      <span :class="pctClass(f.profit_pct)" class="pl-pct">
        ({{ formatPct(f.profit_pct) }})
      </span>
    </div>
    <div class="fund-meta">
      <span>份额 {{ f.shares }}</span>
      <span>成本 {{ f.cost_nav.toFixed(4) }}</span>
      <span v-if="f.holdings_date" class="holdings-date">
        持仓截至 {{ f.holdings_date }}
      </span>
    </div>
  </div>
  <button class="remove-btn" @click.stop="removeFund(f.fund_code)">删除</button>
</div>
```

**Step 3: 在 `<style scoped>` 中添加新样式**

在现有 `.fund-row` 和 `.fund-main` 样式后追加：

```css
.fund-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.fund-name {
  font-size: 15px;
  font-weight: 600;
}

.fund-code-tag {
  font-size: 11px;
  color: #999;
  background: #f5f5f5;
  padding: 1px 6px;
  border-radius: 3px;
}

.fund-est {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.est-nav {
  font-size: 18px;
  font-weight: 600;
  color: #1a1a2e;
}

.est-pct {
  font-size: 14px;
  font-weight: 500;
}

.fund-pl {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  font-size: 13px;
}

.pl-label {
  color: #999;
  font-size: 12px;
}

.pl-value {
  font-weight: 500;
}

.pl-pct {
  font-size: 12px;
}

.fund-meta {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: #aaa;
}

.holdings-date {
  color: #bbb;
}
```

**Step 4: 手动验证**

启动后端和前端，打开组合详情页，确认每只基金行：
- 显示基金名称（而非仅代码）
- 显示估算净值 + 涨跌幅
- 显示持仓收益金额和收益率
- 显示持仓报告截止日期

**Step 5: 提交**

```bash
cd /Users/cc/fund-monitor
git add frontend/src/api/index.ts frontend/src/views/PortfolioDetail.vue
git commit -m "feat: display fund name, estimate, and per-fund P&L in portfolio detail"
```

---

## 验收标准

- [ ] 组合详情API响应中每个基金对象包含 `fund_name`、`est_change_pct`、`profit`、`profit_pct`、`holdings_date`
- [ ] 前端组合详情页每行基金显示名称、估算净值、今日涨跌、持仓收益
- [ ] 持仓覆盖率 < 30% 时，持仓日期显示为浅灰色警示
- [ ] 所有新测试通过，全量后端测试无回归
