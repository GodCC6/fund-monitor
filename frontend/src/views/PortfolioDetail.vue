<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type PortfolioDetail, type FundSearchResult } from '../api'

const route = useRoute()
const router = useRouter()
const portfolioId = computed(() => Number(route.params.id))

const portfolio = ref<PortfolioDetail | null>(null)
const loading = ref(false)
const error = ref('')

// Name editing
const isEditingName = ref(false)
const editingName = ref('')
const nameInputRef = ref<HTMLInputElement>()

async function startEditName() {
  editingName.value = portfolio.value?.name ?? ''
  isEditingName.value = true
  await nextTick()
  nameInputRef.value?.focus()
  nameInputRef.value?.select()
}

async function saveName() {
  const name = editingName.value.trim()
  if (!name || name === portfolio.value?.name) {
    isEditingName.value = false
    return
  }
  try {
    await api.renamePortfolio(portfolioId.value, name)
    if (portfolio.value) portfolio.value.name = name
    isEditingName.value = false
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '修改失败'
  }
}

function cancelEditName() {
  isEditingName.value = false
}

// Add fund form
const showAddForm = ref(false)
const addFundCode = ref('')
const addShares = ref<number | undefined>(undefined)
const addCostNav = ref<number | undefined>(undefined)
const addError = ref('')
const addLoading = ref(false)

// Search state
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
  searchTimer = setTimeout(() => doSearch(q), 300)
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

let timer: ReturnType<typeof setInterval> | null = null

async function load() {
  loading.value = true
  error.value = ''
  try {
    portfolio.value = await api.getPortfolio(portfolioId.value)
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

// True when at least one fund has live coverage (real-time estimate active)
const isEstimating = computed(() => portfolio.value?.funds.some(f => f.coverage > 0) ?? false)

function isTradeTime(): boolean {
  const now = new Date()
  const h = now.getHours()
  const m = now.getMinutes()
  const t = h * 60 + m
  return t >= 9 * 60 + 30 && t <= 15 * 60
}

function startAutoRefresh() {
  timer = setInterval(() => {
    if (isTradeTime()) {
      load()
    }
  }, 30000)
}

async function addFund() {
  if (addLoading.value) return
  addError.value = ''
  const code = addFundCode.value.trim()
  if (!code || !addShares.value || !addCostNav.value) {
    addError.value = '请填写完整信息'
    return
  }
  addLoading.value = true
  try {
    // First try to set up the fund (fetch info + holdings from akshare)
    try {
      await api.setupFund(code)
    } catch {
      // Fund may already exist, continue
    }
    await api.addFundToPortfolio(portfolioId.value, code, addShares.value, addCostNav.value)
    addFundCode.value = ''
    addShares.value = undefined
    addCostNav.value = undefined
    showAddForm.value = false
    await load()
  } catch (e: unknown) {
    addError.value = e instanceof Error ? e.message : '添加失败'
  } finally {
    addLoading.value = false
  }
}

async function removeFund(code: string) {
  if (!confirm(`确认删除基金 ${code}？`)) return
  try {
    await api.removeFundFromPortfolio(portfolioId.value, code)
    await load()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '删除失败'
  }
}

function pctClass(val: number): string {
  if (val > 0) return 'up'
  if (val < 0) return 'down'
  return ''
}

function formatPct(val: number): string {
  const sign = val > 0 ? '+' : ''
  return `${sign}${val.toFixed(2)}%`
}

function formatMoney(val: number): string {
  return val.toFixed(2)
}

onMounted(() => {
  load()
  startAutoRefresh()
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="portfolio-detail">
    <div class="back" @click="router.push('/')">← 返回</div>

    <div v-if="portfolio" class="name-row">
      <template v-if="!isEditingName">
        <h2 class="portfolio-name">{{ portfolio.name }}</h2>
        <button class="edit-name-btn" @click="startEditName" title="修改名称">✏️</button>
      </template>
      <template v-else>
        <input
          ref="nameInputRef"
          v-model="editingName"
          class="name-input"
          @keyup.enter="saveName"
          @keyup.escape="cancelEditName"
        />
        <button class="save-name-btn" @click="saveName">保存</button>
        <button class="cancel-name-btn" @click="cancelEditName">取消</button>
      </template>
    </div>

    <p v-if="loading && !portfolio" class="hint">加载中...</p>
    <p v-if="error" class="error">{{ error }}</p>

    <!-- Summary -->
    <div v-if="portfolio" class="summary">
      <div class="summary-item">
        <span class="label">总成本</span>
        <span>{{ formatMoney(portfolio.total_cost) }}</span>
      </div>
      <div class="summary-item">
        <span class="label">估值 <span v-if="isEstimating" class="badge">估</span></span>
        <span>{{ formatMoney(portfolio.total_estimate) }}</span>
      </div>
      <div class="summary-item">
        <span class="label">估算收益</span>
        <span :class="pctClass(portfolio.total_profit)">
          {{ formatMoney(portfolio.total_profit) }}
        </span>
      </div>
      <div class="summary-item">
        <span class="label">估算收益率</span>
        <span :class="pctClass(portfolio.total_profit_pct)">
          {{ formatPct(portfolio.total_profit_pct) }}
        </span>
      </div>
    </div>

    <!-- Fund list -->
    <div v-if="portfolio && portfolio.funds.length > 0" class="fund-list">
      <div v-for="f in portfolio.funds" :key="f.fund_code" class="fund-row">
        <div class="fund-main" @click="router.push(`/fund/${f.fund_code}`)">
          <div class="fund-header">
            <span class="fund-name">{{ f.fund_name }}</span>
            <span class="fund-code-tag">{{ f.fund_code }}</span>
          </div>
          <div class="fund-est">
            <span class="est-nav">{{ f.est_nav.toFixed(4) }}</span>
            <span v-if="f.coverage > 0" class="badge">估</span>
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
    </div>

    <div v-if="portfolio && portfolio.funds.length === 0" class="empty">
      暂无基金，请添加
    </div>

    <!-- Add fund -->
    <div class="add-section">
      <button v-if="!showAddForm" class="add-btn" @click="showAddForm = true">
        + 添加基金
      </button>
      <div v-if="showAddForm" class="add-form">
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
        <input v-model.number="addShares" placeholder="份额" type="number" step="0.01" />
        <input v-model.number="addCostNav" placeholder="成本净值" type="number" step="0.0001" />
        <p v-if="addError" class="error">{{ addError }}</p>
        <div class="add-form-actions">
          <button @click="addFund" :disabled="addLoading">
            {{ addLoading ? '添加中...' : '确认添加' }}
          </button>
          <button class="cancel-btn" :disabled="addLoading" @click="showAddForm = false; clearSearch()">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.back {
  color: #666;
  cursor: pointer;
  margin-bottom: 8px;
  font-size: 14px;
}

.back:hover {
  color: #333;
}

.summary {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.summary-item .label {
  font-size: 12px;
  color: #999;
}

.summary-item span:last-child {
  font-size: 18px;
  font-weight: 600;
}

.badge {
  display: inline-block;
  background: #ff9800;
  color: #fff;
  font-size: 10px;
  padding: 1px 4px;
  border-radius: 3px;
  vertical-align: middle;
}

.up {
  color: #ff4444;
}

.down {
  color: #00c853;
}

.fund-list {
  margin-bottom: 16px;
}

.fund-row {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.fund-main {
  cursor: pointer;
  flex: 1;
}

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

.remove-btn {
  background: none;
  border: 1px solid #ff4444;
  color: #ff4444;
  padding: 4px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}

.add-section {
  margin-top: 8px;
}

.add-btn {
  width: 100%;
  padding: 12px;
  background: #f5f5f5;
  border: 1px dashed #ccc;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  color: #666;
}

.add-form {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.add-form input {
  padding: 8px 12px;
  border: 1px solid #ccc;
  border-radius: 6px;
  font-size: 14px;
}

.add-form-actions {
  display: flex;
  gap: 8px;
}

.add-form-actions button {
  flex: 1;
  padding: 8px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}

.add-form-actions button:first-child {
  background: #1a1a2e;
  color: #fff;
}

.cancel-btn {
  background: #f5f5f5 !important;
  color: #666 !important;
}

.hint {
  color: #999;
  text-align: center;
  padding: 20px;
}

.empty {
  color: #999;
  text-align: center;
  padding: 30px 0;
}

.error {
  color: #ff4444;
  font-size: 13px;
}

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

.name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.portfolio-name {
  margin: 0;
  font-size: 20px;
}

.edit-name-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 14px;
  color: #aaa;
  padding: 2px 4px;
  line-height: 1;
}

.edit-name-btn:hover {
  color: #666;
}

.name-input {
  flex: 1;
  padding: 6px 10px;
  border: 1px solid #1677ff;
  border-radius: 6px;
  font-size: 18px;
  font-weight: 600;
  outline: none;
}

.save-name-btn,
.cancel-name-btn {
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  border: none;
}

.save-name-btn {
  background: #1677ff;
  color: #fff;
}

.cancel-name-btn {
  background: #f5f5f5;
  color: #666;
}

.add-form-actions button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
