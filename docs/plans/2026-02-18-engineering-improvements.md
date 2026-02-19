# Engineering Improvements 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 三项工程质量改进：(1) 估值API在行情获取失败时降级返回基于昨日净值的保守数据；(2) 添加手动刷新按钮；(3) 组合中基金列表支持按涨跌幅/收益率排序。

**Architecture:** 这三项改动独立，可按任意顺序实施。每项改动范围均在1-2个文件内。

**Tech Stack:** Python/FastAPI（后端改进1），Vue3（前端改进2、3）

---

### Task 1: 估值 API 降级处理

**背景:** 当前 `GET /api/fund/{code}/estimate` 在行情拉取失败时直接报错。实际上可以返回 `est_nav = last_nav`、`est_change_pct = 0`、`coverage = 0` 作为保守降级响应，并附带降级标志 `degraded: true`，让前端可以显示提示而非错误页面。

**Files:**
- Modify: `backend/app/api/fund.py`
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/tests/test_api_fund.py`

**Step 1: 更新 FundEstimateResponse schema 添加 degraded 字段**

在 `backend/app/api/schemas.py` 的 `FundEstimateResponse` 中追加：

```python
class FundEstimateResponse(BaseModel):
    fund_code: str
    fund_name: str
    est_nav: float
    est_change_pct: float
    last_nav: float
    coverage: float
    details: list[dict]
    degraded: bool = False  # True when live quotes unavailable, using last_nav as estimate
```

**Step 2: 编写降级测试**

在 `backend/tests/test_api_fund.py` 末尾追加（在已有 fixture 之后）：

```python
@pytest.mark.asyncio
async def test_estimate_degrades_when_no_quotes(db_session):
    """When market data returns empty, return degraded estimate based on last_nav."""
    with patch(
        "app.api.fund.market_data_service.get_stock_quotes",
        return_value={},  # 行情服务返回空
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/fund/000001/estimate")
    assert resp.status_code == 200  # 不报错，降级响应
    data = resp.json()
    assert data["degraded"] is True
    assert data["est_nav"] == data["last_nav"]  # 降级时等于昨日净值
    assert data["est_change_pct"] == 0.0
    assert data["coverage"] == 0.0
    assert data["details"] == []
```

**Step 3: 运行测试，确认失败**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/test_api_fund.py::test_estimate_degrades_when_no_quotes -v
```

预期：FAIL（当前逻辑遇到空 quotes 会报 400 或返回非降级数据）

**Step 4: 更新 fund.py 中的 get_estimate 端点**

将 `backend/app/api/fund.py` 中的 `get_estimate` 函数替换为：

```python
@router.get("/{fund_code}/estimate", response_model=FundEstimateResponse)
async def get_estimate(fund_code: str, db: AsyncSession = Depends(get_db)):
    fund = await fund_info_service.get_fund(db, fund_code)
    if fund is None:
        raise HTTPException(status_code=404, detail="Fund not found")
    if fund.last_nav is None:
        raise HTTPException(status_code=400, detail="Fund NAV not available")

    holdings = await fund_info_service.get_holdings(db, fund_code)

    # Degraded response: no holdings data
    if not holdings:
        return FundEstimateResponse(
            fund_code=fund.fund_code,
            fund_name=fund.fund_name,
            est_nav=fund.last_nav,
            est_change_pct=0.0,
            last_nav=fund.last_nav,
            coverage=0.0,
            details=[],
            degraded=True,
        )

    stock_codes = [h.stock_code for h in holdings]
    stock_quotes = market_data_service.get_stock_quotes(stock_codes)

    # Degraded response: quotes unavailable
    if not stock_quotes:
        return FundEstimateResponse(
            fund_code=fund.fund_code,
            fund_name=fund.fund_name,
            est_nav=fund.last_nav,
            est_change_pct=0.0,
            last_nav=fund.last_nav,
            coverage=0.0,
            details=[],
            degraded=True,
        )

    holdings_data = [
        {
            "stock_code": h.stock_code,
            "stock_name": h.stock_name,
            "holding_ratio": h.holding_ratio,
        }
        for h in holdings
    ]
    estimate = fund_estimator.calculate_estimate(holdings_data, stock_quotes, fund.last_nav)

    return FundEstimateResponse(
        fund_code=fund.fund_code,
        fund_name=fund.fund_name,
        degraded=False,
        **estimate,
    )
```

**Step 5: 运行所有基金 API 测试**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/test_api_fund.py -v
```

预期：全部通过（含新增降级测试）

**Step 6: 运行全量测试**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/ -v --tb=short
```

**Step 7: 更新前端，降级时显示提示**

在 `frontend/src/views/FundDetail.vue` 的估值卡片标题行（`<h3>实时估值 <span class="badge">估</span></h3>`）后追加：

```html
<div v-if="estimate?.degraded" class="degraded-hint">
  ⚠ 行情数据暂时不可用，以昨日净值显示
</div>
```

在 `<style scoped>` 追加：

```css
.degraded-hint {
  font-size: 12px;
  color: #ff9800;
  background: #fff8e1;
  padding: 6px 10px;
  border-radius: 4px;
  margin-bottom: 12px;
}
```

同时在 `api/index.ts` 的 `FundEstimate` 接口追加：

```typescript
degraded: boolean
```

**Step 8: 提交**

```bash
cd /Users/cc/fund-monitor
git add backend/app/api/fund.py backend/app/api/schemas.py \
        backend/tests/test_api_fund.py \
        frontend/src/views/FundDetail.vue frontend/src/api/index.ts
git commit -m "feat: graceful degradation for estimate API when quotes unavailable"
```

---

### Task 2: 手动刷新按钮

**背景:** 非交易时段 auto-refresh 不触发，用户无法主动更新数据。添加刷新按钮（组合详情和基金详情页均需要）。

**Files:**
- Modify: `frontend/src/views/PortfolioDetail.vue`
- Modify: `frontend/src/views/FundDetail.vue`

**Step 1: 在 PortfolioDetail.vue 添加刷新按钮**

在组合名称 `<h2>` 旁边添加刷新按钮（改为 flex 布局）：

将：
```html
<h2 v-if="portfolio">{{ portfolio.name }}</h2>
```

替换为：

```html
<div v-if="portfolio" class="page-header">
  <h2>{{ portfolio.name }}</h2>
  <button class="refresh-btn" :class="{ spinning: loading }" @click="load" :disabled="loading">
    ↻
  </button>
</div>
```

在 `<style scoped>` 追加：

```css
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.page-header h2 {
  margin: 0;
}

.refresh-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid #e8e8e8;
  background: #fff;
  cursor: pointer;
  font-size: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #666;
  transition: transform 0.4s;
}

.refresh-btn:disabled {
  color: #ccc;
  cursor: not-allowed;
}

.refresh-btn.spinning {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
```

**Step 2: 在 FundDetail.vue 添加刷新按钮**

将 `<div class="back" @click="router.back()">← 返回</div>` 替换为：

```html
<div class="nav-bar">
  <div class="back" @click="router.back()">← 返回</div>
  <button class="refresh-btn" :class="{ spinning: loading }" @click="load" :disabled="loading">
    ↻
  </button>
</div>
```

在 `<style scoped>` 追加（样式与 PortfolioDetail 相同的 `.refresh-btn` 和 `@keyframes spin`）：

```css
.nav-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.refresh-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid #e8e8e8;
  background: #fff;
  cursor: pointer;
  font-size: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #666;
}

.refresh-btn:disabled { color: #ccc; cursor: not-allowed; }
.refresh-btn.spinning { animation: spin 0.8s linear infinite; }

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
```

**Step 3: 手动验证**

打开组合详情页，确认右上角出现刷新按钮，点击后旋转并重新加载数据。

**Step 4: 提交**

```bash
cd /Users/cc/fund-monitor
git add frontend/src/views/PortfolioDetail.vue frontend/src/views/FundDetail.vue
git commit -m "feat: add manual refresh button to portfolio and fund detail pages"
```

---

### Task 3: 基金列表排序

**背景:** 组合中基金数量多时，希望能快速按「今日涨跌」或「持仓收益率」排序，找到最好/最差的基金。

**Files:**
- Modify: `frontend/src/views/PortfolioDetail.vue`

（此 Task 依赖 P0-A 已完成，`f.est_change_pct` 和 `f.profit_pct` 字段可用）

**Step 1: 在 script setup 中添加排序状态**

```typescript
type SortKey = 'none' | 'est_change_pct' | 'profit_pct' | 'current_value'
const sortKey = ref<SortKey>('none')
const sortDir = ref<'desc' | 'asc'>('desc')

const sortedFunds = computed(() => {
  if (!portfolio.value) return []
  const funds = [...portfolio.value.funds]
  if (sortKey.value === 'none') return funds
  return funds.sort((a, b) => {
    const va = a[sortKey.value as keyof typeof a] as number
    const vb = b[sortKey.value as keyof typeof b] as number
    return sortDir.value === 'desc' ? vb - va : va - vb
  })
})

function toggleSort(key: SortKey) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortKey.value = key
    sortDir.value = 'desc'
  }
}
```

**Step 2: 在基金列表顶部添加排序工具栏**

在 `.fund-list` div 的 `v-if` 块上方（但在内部）插入：

```html
<div v-if="portfolio && portfolio.funds.length > 0" class="fund-list">
  <!-- 排序工具栏 -->
  <div class="sort-bar">
    <span class="sort-label">排序：</span>
    <button
      v-for="opt in [
        { key: 'none', label: '默认' },
        { key: 'est_change_pct', label: '今日涨跌' },
        { key: 'profit_pct', label: '持仓收益' },
        { key: 'current_value', label: '市值' },
      ]"
      :key="opt.key"
      :class="['sort-btn', { active: sortKey === opt.key }]"
      @click="toggleSort(opt.key as SortKey)"
    >
      {{ opt.label }}
      <span v-if="sortKey === opt.key">{{ sortDir === 'desc' ? '↓' : '↑' }}</span>
    </button>
  </div>

  <!-- 基金行改为用 sortedFunds -->
  <div v-for="f in sortedFunds" :key="f.fund_code" class="fund-row">
    <!-- ... 已有的内容不变 ... -->
  </div>
</div>
```

注意：将原来 `v-for="f in portfolio.funds"` 改为 `v-for="f in sortedFunds"`。

在 `<style scoped>` 追加：

```css
.sort-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 0;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.sort-label {
  font-size: 12px;
  color: #999;
}

.sort-btn {
  font-size: 12px;
  padding: 4px 10px;
  border: 1px solid #e0e0e0;
  border-radius: 12px;
  background: #fff;
  cursor: pointer;
  color: #666;
}

.sort-btn.active {
  background: #1a1a2e;
  color: #fff;
  border-color: #1a1a2e;
}
```

**Step 3: 手动验证**

打开组合详情，点击「今日涨跌」按钮，基金列表按涨跌幅从高到低排列。再次点击切换为从低到高。点击「默认」恢复原始顺序。

**Step 4: 提交**

```bash
cd /Users/cc/fund-monitor
git add frontend/src/views/PortfolioDetail.vue
git commit -m "feat: add sort controls for fund list in portfolio detail"
```

---

## 验收标准

**Task 1 (降级处理):**
- [ ] 行情数据为空时，estimate API 返回 200 + `degraded: true` + `est_nav == last_nav`
- [ ] 前端在 `degraded` 时显示橙色提示条
- [ ] 原有正常行情路径不受影响

**Task 2 (手动刷新):**
- [ ] 组合详情和基金详情页均有刷新按钮
- [ ] 刷新中按钮旋转，完成后停止
- [ ] 加载中按钮禁用，防止重复点击

**Task 3 (基金排序):**
- [ ] 支持按「今日涨跌」「持仓收益」「市值」三种键排序
- [ ] 再次点击同一键切换升降序
- [ ] 「默认」恢复原始添加顺序
- [ ] 依赖 P0-A 完成后方可实施（需要 `est_change_pct`/`profit_pct` 字段）
