<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type FundInfo, type FundEstimate } from '../api'
import NavChart from '../components/NavChart.vue'

const route = useRoute()
const router = useRouter()
const fundCode = computed(() => route.params.code as string)

const fund = ref<FundInfo | null>(null)
const estimate = ref<FundEstimate | null>(null)
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [fundData, estData] = await Promise.all([
      api.getFund(fundCode.value),
      api.getFundEstimate(fundCode.value),
    ])
    fund.value = fundData
    estimate.value = estData
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

function pctClass(val: number): string {
  if (val > 0) return 'up'
  if (val < 0) return 'down'
  return ''
}

function navStaleDays(navDate: string | null): number {
  if (!navDate) return 999
  const d = new Date(navDate)
  const now = new Date()
  return Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24))
}

function isNavStale(navDate: string | null): boolean {
  return navStaleDays(navDate) > 3
}

const refreshing = ref(false)
async function refreshNav() {
  if (!fund.value || refreshing.value) return
  refreshing.value = true
  try {
    const result = await api.refreshFundNav(fundCode.value)
    if (fund.value) {
      fund.value.last_nav = result.nav
      fund.value.nav_date = result.nav_date
    }
  } catch {
    // silently ignore
  } finally {
    refreshing.value = false
  }
}

function formatPct(val: number): string {
  const sign = val > 0 ? '+' : ''
  return `${sign}${val.toFixed(2)}%`
}

onMounted(load)
</script>

<template>
  <div class="fund-detail">
    <div class="back" @click="router.back()">← 返回</div>

    <p v-if="loading" class="hint">加载中...</p>
    <p v-if="error" class="error">{{ error }}</p>

    <!-- Fund Info -->
    <div v-if="fund" class="info-card">
      <h2>{{ fund.fund_name }}</h2>
      <div class="info-row">
        <span class="label">代码</span>
        <span>{{ fund.fund_code }}</span>
      </div>
      <div class="info-row">
        <span class="label">类型</span>
        <span>{{ fund.fund_type }}</span>
      </div>
      <div v-if="fund.last_nav != null" class="info-row">
        <span class="label">最新净值</span>
        <span class="nav-value-row">
          {{ fund.last_nav }}
          <span class="nav-date" :class="{ stale: isNavStale(fund.nav_date) }">
            {{ fund.nav_date }}
            <span v-if="isNavStale(fund.nav_date)" class="stale-hint">
              ⚠ 已 {{ navStaleDays(fund.nav_date) }} 天未更新
            </span>
          </span>
          <button class="refresh-nav-btn" :disabled="refreshing" @click.stop="refreshNav">
            {{ refreshing ? '刷新中...' : '刷新' }}
          </button>
        </span>
      </div>
    </div>

    <!-- Estimate -->
    <div v-if="estimate" class="estimate-card">
      <div class="estimate-header">
        <h3>实时估值 <span v-if="estimate.coverage > 0" class="badge">估</span></h3>
      </div>
      <div class="estimate-summary">
        <div class="est-item">
          <span class="label">估算净值</span>
          <span class="est-value">{{ estimate.est_nav.toFixed(4) }}</span>
        </div>
        <div class="est-item">
          <span class="label">估算涨跌</span>
          <span class="est-value" :class="pctClass(estimate.est_change_pct)">
            {{ formatPct(estimate.est_change_pct) }}
          </span>
        </div>
        <div class="est-item">
          <span class="label">参考净值{{ fund?.nav_date ? `（${fund.nav_date}）` : '' }}</span>
          <span>{{ estimate.last_nav.toFixed(4) }}</span>
        </div>
        <div class="est-item">
          <span class="label">持仓覆盖</span>
          <span>{{ (estimate.coverage * 100).toFixed(1) }}%</span>
        </div>
      </div>

      <!-- NAV Chart -->
      <NavChart :fund-code="fundCode" />

      <!-- Holdings breakdown -->
      <div v-if="estimate.details.length > 0" class="holdings">
        <h4>持仓明细</h4>
        <div class="holdings-header">
          <span>股票</span>
          <span>占比</span>
          <span>现价</span>
          <span>涨跌</span>
          <span>贡献</span>
        </div>
        <div
          v-for="d in estimate.details"
          :key="d.stock_code"
          class="holding-row"
        >
          <span class="stock-name" :title="d.stock_code">{{ d.stock_name }}</span>
          <span>{{ (d.holding_ratio * 100).toFixed(1) }}%</span>
          <span>{{ d.price.toFixed(2) }}</span>
          <span :class="pctClass(d.change_pct)">{{ formatPct(d.change_pct) }}</span>
          <span :class="pctClass(d.contribution)">{{ d.contribution > 0 ? '+' : '' }}{{ d.contribution.toFixed(4) }}</span>
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

.info-card {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}

.info-card h2 {
  margin: 0 0 12px 0;
  font-size: 18px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  font-size: 14px;
  border-bottom: 1px solid #f5f5f5;
}

.label {
  color: #999;
  font-size: 12px;
}

.estimate-card {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 16px;
}

.estimate-header h3 {
  margin: 0 0 12px 0;
  font-size: 16px;
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

.estimate-summary {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 16px;
}

.est-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.est-value {
  font-size: 20px;
  font-weight: 600;
}

.up {
  color: #ff4444;
}

.down {
  color: #00c853;
}

.holdings {
  border-top: 1px solid #e8e8e8;
  padding-top: 12px;
}

.holdings h4 {
  margin: 0 0 8px 0;
  font-size: 14px;
}

.holdings-header {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr 1fr;
  font-size: 11px;
  color: #999;
  padding: 6px 0;
  border-bottom: 1px solid #f0f0f0;
}

.holding-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr 1fr;
  font-size: 13px;
  padding: 8px 0;
  border-bottom: 1px solid #f8f8f8;
}

.stock-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hint {
  color: #999;
  text-align: center;
  padding: 20px;
}

.error {
  color: #ff4444;
  text-align: center;
}

.nav-value-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.nav-date {
  font-size: 12px;
  color: #999;
}

.nav-date.stale {
  color: #ff9800;
}

.stale-hint {
  font-size: 11px;
}

.refresh-nav-btn {
  font-size: 11px;
  padding: 2px 8px;
  border: 1px solid #d9d9d9;
  border-radius: 4px;
  background: #fafafa;
  color: #666;
  cursor: pointer;
}

.refresh-nav-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
