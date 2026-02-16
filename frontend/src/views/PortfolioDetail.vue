<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type PortfolioDetail } from '../api'

const route = useRoute()
const router = useRouter()
const portfolioId = computed(() => Number(route.params.id))

const portfolio = ref<PortfolioDetail | null>(null)
const loading = ref(false)
const error = ref('')

// Add fund form
const showAddForm = ref(false)
const addFundCode = ref('')
const addShares = ref<number | undefined>(undefined)
const addCostNav = ref<number | undefined>(undefined)
const addError = ref('')

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
  addError.value = ''
  const code = addFundCode.value.trim()
  if (!code || !addShares.value || !addCostNav.value) {
    addError.value = '请填写完整信息'
    return
  }
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

    <h2 v-if="portfolio">{{ portfolio.name }}</h2>

    <p v-if="loading && !portfolio" class="hint">加载中...</p>
    <p v-if="error" class="error">{{ error }}</p>

    <!-- Summary -->
    <div v-if="portfolio" class="summary">
      <div class="summary-item">
        <span class="label">总成本</span>
        <span>{{ formatMoney(portfolio.total_cost) }}</span>
      </div>
      <div class="summary-item">
        <span class="label">估值 <span class="badge">估</span></span>
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
          <div class="fund-code">{{ f.fund_code }}</div>
          <div class="fund-info">
            <span>份额: {{ f.shares }}</span>
            <span>成本净值: {{ formatMoney(f.cost_nav) }}</span>
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
        <input v-model="addFundCode" placeholder="基金代码 (如 000001)" />
        <input v-model.number="addShares" placeholder="份额" type="number" step="0.01" />
        <input v-model.number="addCostNav" placeholder="成本净值" type="number" step="0.0001" />
        <p v-if="addError" class="error">{{ addError }}</p>
        <div class="add-form-actions">
          <button @click="addFund">确认添加</button>
          <button class="cancel-btn" @click="showAddForm = false">取消</button>
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

.fund-code {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 4px;
}

.fund-info {
  font-size: 12px;
  color: #666;
  display: flex;
  gap: 12px;
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
</style>
