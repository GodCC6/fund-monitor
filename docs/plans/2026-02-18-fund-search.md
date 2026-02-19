# Fund Search 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在添加基金时支持按名称或代码搜索，消除手填6位代码的摩擦。

**Architecture:** 后端新增 `GET /api/fund/search?q=xxx` 端点，使用 akshare `fund_name_em()` 全量表做模糊匹配（带内存缓存，避免重复请求大数据集）。前端在添加基金表单中加入搜索输入框 + 防抖 + 下拉结果列表。

**Tech Stack:** Python/FastAPI/akshare（后端），Vue3/TypeScript（前端）

---

## 背景

`market_data_service.get_fund_basic_info()` 已经调用 `ak.fund_name_em()`，返回全量基金名称表（约 10000 条）。问题是每次都重新拉取，需要加缓存。搜索端点对这个数据集做前缀/包含匹配即可。

---

### Task 1: 后端搜索端点

**Files:**
- Modify: `backend/app/api/search.py`
- Create: `backend/tests/test_api_search.py`

**Step 1: 编写失败测试**

创建 `backend/tests/test_api_search.py`：

```python
"""Tests for fund search endpoint."""

import pytest
import pandas as pd
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models.database import get_db
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.models.database import Base
import pytest_asyncio


@pytest_asyncio.fixture
async def empty_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield
    app.dependency_overrides.clear()
    await engine.dispose()


MOCK_FUND_TABLE = pd.DataFrame({
    "基金代码": ["000001", "000002", "110022", "270002"],
    "基金简称": ["华夏成长混合", "华夏优势增长", "易方达消费行业", "广发稳健增长"],
    "基金类型": ["混合型", "股票型", "股票型", "混合型"],
})


@pytest.mark.asyncio
async def test_search_by_name(empty_db):
    with patch("app.api.search.ak.fund_name_em", return_value=MOCK_FUND_TABLE):
        async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/search?q=华夏")
    assert resp.status_code == 200
    results = resp.json()
    codes = [r["fund_code"] for r in results]
    assert "000001" in codes
    assert "000002" in codes
    assert "110022" not in codes  # 不含"华夏"


@pytest.mark.asyncio
async def test_search_by_code(empty_db):
    with patch("app.api.search.ak.fund_name_em", return_value=MOCK_FUND_TABLE):
        async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/search?q=1100")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["fund_code"] == "110022"


@pytest.mark.asyncio
async def test_search_returns_max_20(empty_db):
    """Results capped at 20 to avoid huge payloads."""
    big_table = pd.DataFrame({
        "基金代码": [f"{i:06d}" for i in range(100)],
        "基金简称": [f"测试基金{i}" for i in range(100)],
        "基金类型": ["混合型"] * 100,
    })
    with patch("app.api.search.ak.fund_name_em", return_value=big_table):
        async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/search?q=测试")
    assert len(resp.json()) <= 20


@pytest.mark.asyncio
async def test_search_empty_query_returns_empty(empty_db):
    async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/fund/search?q=")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_search_no_results(empty_db):
    with patch("app.api.search.ak.fund_name_em", return_value=MOCK_FUND_TABLE):
        async with AsyncClient(ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/search?q=不存在的基金名称XYZ")
    assert resp.status_code == 200
    assert resp.json() == []
```

**Step 2: 运行测试，确认失败**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/test_api_search.py -v
```

预期：FAIL（`/api/fund/search` 路由不存在）

**Step 3: 在 search.py 中实现搜索端点**

在 `backend/app/api/search.py` 末尾追加（在 `setup_fund` 函数之后）：

```python
import akshare as ak
import time
from typing import Any

# Simple in-process cache for fund name table (refreshed every hour)
_fund_name_cache: dict[str, Any] = {"data": None, "ts": 0}
_FUND_NAME_CACHE_TTL = 3600  # 1 hour


def _get_fund_name_table():
    """Return cached fund name DataFrame, refresh if stale."""
    now = time.time()
    if _fund_name_cache["data"] is None or now - _fund_name_cache["ts"] > _FUND_NAME_CACHE_TTL:
        _fund_name_cache["data"] = ak.fund_name_em()
        _fund_name_cache["ts"] = now
    return _fund_name_cache["data"]


@router.get("/fund/search")
async def search_funds(q: str = ""):
    """Search funds by name or code prefix.

    Returns up to 20 matches: [{fund_code, fund_name, fund_type}].
    """
    q = q.strip()
    if not q:
        return []

    try:
        df = _get_fund_name_table()
        q_lower = q.lower()
        mask = (
            df["基金代码"].str.startswith(q)
            | df["基金简称"].str.contains(q, case=False, na=False)
        )
        matched = df[mask].head(20)
        return [
            {
                "fund_code": str(row["基金代码"]),
                "fund_name": str(row["基金简称"]),
                "fund_type": str(row["基金类型"]),
            }
            for _, row in matched.iterrows()
        ]
    except Exception as e:
        logger.error(f"Fund search failed: {e}")
        return []
```

注意：`search.py` 顶部已有 `from fastapi import APIRouter, Depends, HTTPException` 和 `from sqlalchemy.ext.asyncio import AsyncSession` 等导入，需要在文件顶部追加：

```python
import akshare as ak
import time
from typing import Any
import logging

logger = logging.getLogger(__name__)
```

如果文件顶部已有 `logger`，只追加 `akshare`、`time`、`Any` 的导入。

**Step 4: 运行测试，确认通过**

```bash
cd /Users/cc/fund-monitor/backend
python -m pytest tests/test_api_search.py -v
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
git add backend/app/api/search.py backend/tests/test_api_search.py
git commit -m "feat: add fund search endpoint with in-process name table cache"
```

---

### Task 2: 前端搜索 UI

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/views/PortfolioDetail.vue`

**Step 1: 在 api/index.ts 中添加搜索接口**

在 `api` 对象中追加：

```typescript
export interface FundSearchResult {
  fund_code: string
  fund_name: string
  fund_type: string
}

// 在 api 对象中追加：
searchFunds: (q: string) => request<FundSearchResult[]>(`/api/fund/search?q=${encodeURIComponent(q)}`),
```

**Step 2: 在 PortfolioDetail.vue 中改造添加基金表单**

当前添加基金表单（`showAddForm` 部分）只有三个纯文本输入框。改造如下：

在 `<script setup>` 顶部追加导入和新响应式变量：

```typescript
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { api, type PortfolioDetail, type FundSearchResult } from '../api'

// 搜索相关状态（添加到现有 script setup 中）
const searchQuery = ref('')
const searchResults = ref<FundSearchResult[]>([])
const searchLoading = ref(false)
let searchTimer: ReturnType<typeof setTimeout> | null = null

async function doSearch(q: string) {
  if (!q.trim()) {
    searchResults.value = []
    return
  }
  searchLoading.value = true
  try {
    searchResults.value = await api.searchFunds(q)
  } catch {
    searchResults.value = []
  } finally {
    searchLoading.value = false
  }
}

watch(searchQuery, (q) => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => doSearch(q), 300)  // 300ms 防抖
})

function selectFund(result: FundSearchResult) {
  addFundCode.value = result.fund_code
  searchQuery.value = result.fund_name + ' (' + result.fund_code + ')'
  searchResults.value = []
}

function clearSearch() {
  searchQuery.value = ''
  addFundCode.value = ''
  searchResults.value = []
}
```

在添加基金的 `<div class="add-form">` 中，替换 `addFundCode` 相关输入为：

```html
<!-- 搜索框 -->
<div class="search-wrapper">
  <input
    v-model="searchQuery"
    placeholder="输入基金名称或代码搜索"
    @focus="doSearch(searchQuery)"
  />
  <button v-if="searchQuery" class="clear-btn" @click="clearSearch">×</button>
  <!-- 搜索结果下拉 -->
  <div v-if="searchResults.length > 0" class="search-dropdown">
    <div
      v-for="r in searchResults"
      :key="r.fund_code"
      class="search-item"
      @click="selectFund(r)"
    >
      <span class="si-name">{{ r.fund_name }}</span>
      <span class="si-meta">{{ r.fund_code }} · {{ r.fund_type }}</span>
    </div>
  </div>
  <div v-if="searchLoading" class="search-dropdown">
    <div class="search-item">搜索中...</div>
  </div>
</div>
<!-- 已选中的基金代码展示（只读） -->
<div v-if="addFundCode" class="selected-fund">
  已选：{{ addFundCode }}
</div>
```

在 `<style scoped>` 末尾追加：

```css
.search-wrapper {
  position: relative;
}

.search-wrapper input {
  width: 100%;
  box-sizing: border-box;
}

.clear-btn {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  cursor: pointer;
  color: #aaa;
  font-size: 16px;
  padding: 0;
  line-height: 1;
}

.search-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  z-index: 100;
  max-height: 240px;
  overflow-y: auto;
}

.search-item {
  padding: 10px 12px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 14px;
  border-bottom: 1px solid #f5f5f5;
}

.search-item:hover {
  background: #f9f9f9;
}

.si-name {
  font-weight: 500;
}

.si-meta {
  font-size: 12px;
  color: #999;
}

.selected-fund {
  font-size: 13px;
  color: #1677ff;
  padding: 4px 0;
}
```

**Step 3: 手动验证**

1. 打开组合详情页，点击「添加基金」
2. 输入「华夏」，等待300ms后下拉出现搜索结果
3. 点击某个结果，代码自动填入
4. 继续填写份额和成本净值，点击确认添加

**Step 4: 提交**

```bash
cd /Users/cc/fund-monitor
git add frontend/src/api/index.ts frontend/src/views/PortfolioDetail.vue
git commit -m "feat: add fund name search with debounce to add-fund form"
```

---

## 验收标准

- [ ] `GET /api/fund/search?q=华夏` 返回包含"华夏"的基金列表（≤20条）
- [ ] `GET /api/fund/search?q=000001` 返回代码以 000001 开头的基金
- [ ] 搜索结果缓存1小时，同一进程内不重复拉取全量数据
- [ ] 前端防抖延迟 300ms，输入停止后才发请求
- [ ] 点击搜索结果自动填入代码
- [ ] 空 `q` 参数返回空数组
