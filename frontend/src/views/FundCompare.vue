<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api, type FundSearchResult } from '../api'

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, CanvasRenderer])

const router = useRouter()

const periods = [
  { key: '7d', label: '7日' },
  { key: '30d', label: '30日' },
  { key: 'ytd', label: '今年' },
  { key: '1y', label: '1年' },
  { key: '3y', label: '3年' },
]

const activePeriod = ref('30d')
const loading = ref(false)
const empty = ref(false)
const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

// Selected funds list: {code, name}
interface SelectedFund { code: string; name: string }
const selectedFunds = ref<SelectedFund[]>([])

// Search
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
  if (selectedFunds.value.some(f => f.code === result.fund_code)) return
  selectedFunds.value.push({ code: result.fund_code, name: result.fund_name })
  searchQuery.value = ''
  searchResults.value = []
  loadChart()
}

function removeFund(code: string) {
  selectedFunds.value = selectedFunds.value.filter(f => f.code !== code)
  loadChart()
}

// ECharts colour palette (distinct colours for up to 8 funds)
const COLORS = ['#1677ff', '#ff4444', '#00c853', '#ff9800', '#9c27b0', '#00bcd4', '#795548', '#607d8b']

function initChart() {
  if (chartRef.value && !chart) {
    chart = echarts.init(chartRef.value)
  }
}

async function loadChart() {
  if (selectedFunds.value.length === 0) {
    if (chart) chart.clear()
    empty.value = true
    return
  }

  loading.value = true
  empty.value = false

  try {
    const results = await Promise.all(
      selectedFunds.value.map(f => api.getNavHistory(f.code, activePeriod.value))
    )

    // Check if any fund has data
    const anyData = results.some(r => r.dates.length > 0)
    if (!anyData) {
      empty.value = true
      if (chart) chart.clear()
      return
    }

    // Build a merged date set (union of all dates), sorted
    const allDates = [...new Set(results.flatMap(r => r.dates))].sort()

    // For each fund, build a map of date -> nav, then carry-forward to fill allDates
    const series = results.map((r, idx) => {
      const navMap = new Map<string, number>()
      for (let i = 0; i < r.dates.length; i++) {
        navMap.set(r.dates[i]!, r.navs[i]!)
      }

      // Carry-forward fill
      const navs: number[] = []
      let last = 0
      let base = 0
      let hasBase = false
      for (const d of allDates) {
        if (navMap.has(d)) {
          last = navMap.get(d)!
          if (!hasBase) {
            base = last
            hasBase = true
          }
        }
        navs.push(hasBase ? last : 0)
      }

      // Normalize to % change from first available value
      const pcts = navs.map(v => base !== 0 ? (v / base - 1) * 100 : 0)
      const fund = selectedFunds.value[idx]!
      const color = COLORS[idx % COLORS.length]!

      return {
        name: `${fund.name} (${fund.code})`,
        type: 'line' as const,
        data: pcts,
        smooth: false,
        symbol: 'none',
        lineStyle: { color, width: 2 },
      }
    })

    await nextTick()
    initChart()
    if (!chart) return

    chart.setOption({
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          const d = params[0]?.axisValue || ''
          let html = `<div style="font-size:12px;color:#666;margin-bottom:4px">${d}</div>`
          for (const p of params) {
            const dot = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color};margin-right:4px"></span>`
            const sign = p.data >= 0 ? '+' : ''
            html += `<div>${dot}${p.seriesName}: <b>${sign}${p.data.toFixed(2)}%</b></div>`
          }
          return html
        },
      },
      legend: {
        data: series.map(s => s.name),
        top: 0,
        textStyle: { fontSize: 11 },
        type: 'scroll',
      },
      grid: { left: 55, right: 16, top: 40, bottom: 50 },
      xAxis: {
        type: 'category',
        data: allDates,
        axisLabel: { fontSize: 11, color: '#999', rotate: 30 },
        axisLine: { lineStyle: { color: '#e8e8e8' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: { fontSize: 11, color: '#999', formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#f5f5f5' } },
      },
      dataZoom: [{ type: 'inside', start: 0, end: 100 }],
      series,
    }, true)

    chart.resize()
  } catch {
    empty.value = true
  } finally {
    loading.value = false
  }
}

watch(activePeriod, loadChart)

function handleResize() { chart?.resize() }

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
  chart = null
  if (searchTimer) clearTimeout(searchTimer)
})
</script>

<template>
  <div class="compare-page">
    <div class="back" @click="router.push('/')">← 返回</div>
    <h2 class="page-title">基金对比</h2>
    <p class="page-hint">选择 2 个或以上基金，对比标准化净值走势（均以首日为基准归一化）</p>

    <!-- Fund search -->
    <div class="search-section">
      <div class="search-wrapper">
        <input
          v-model="searchQuery"
          placeholder="搜索基金名称或代码添加对比"
          @focus="doSearch(searchQuery)"
        />
        <div v-if="searchResults.length > 0" class="search-dropdown">
          <div
            v-for="r in searchResults"
            :key="r.fund_code"
            class="search-item"
            :class="{ disabled: selectedFunds.some(f => f.code === r.fund_code) }"
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
    </div>

    <!-- Selected fund chips -->
    <div v-if="selectedFunds.length > 0" class="chips">
      <div v-for="(f, i) in selectedFunds" :key="f.code" class="chip" :style="{ borderColor: COLORS[i % COLORS.length] }">
        <span class="chip-dot" :style="{ background: COLORS[i % COLORS.length] }"></span>
        <span class="chip-name">{{ f.name }}</span>
        <span class="chip-code">{{ f.code }}</span>
        <button class="chip-remove" @click="removeFund(f.code)">×</button>
      </div>
    </div>

    <!-- Period tabs -->
    <div v-if="selectedFunds.length >= 2" class="period-tabs">
      <button
        v-for="p in periods"
        :key="p.key"
        :class="['tab', { active: activePeriod === p.key }]"
        @click="activePeriod = p.key"
      >{{ p.label }}</button>
    </div>

    <!-- Chart -->
    <div class="chart-container">
      <div v-if="loading" class="chart-overlay">加载中...</div>
      <div v-else-if="selectedFunds.length < 2" class="chart-overlay">
        请选择至少 2 个基金进行对比
      </div>
      <div v-else-if="empty" class="chart-overlay">暂无数据</div>
      <div ref="chartRef" class="chart-canvas"></div>
    </div>
  </div>
</template>

<style scoped>
.compare-page {
  padding: 16px;
  max-width: 900px;
  margin: 0 auto;
}

.back {
  color: #666;
  cursor: pointer;
  margin-bottom: 8px;
  font-size: 14px;
}

.back:hover {
  color: #333;
}

.page-title {
  margin: 0 0 6px;
  font-size: 20px;
}

.page-hint {
  font-size: 13px;
  color: #999;
  margin: 0 0 16px;
}

.search-section {
  margin-bottom: 12px;
}

.search-wrapper {
  position: relative;
}

.search-wrapper input {
  width: 100%;
  box-sizing: border-box;
  padding: 10px 14px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
}

.search-wrapper input:focus {
  border-color: #1677ff;
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

.search-item.disabled {
  opacity: 0.4;
  cursor: default;
}

.si-name {
  font-weight: 500;
}

.si-meta {
  font-size: 12px;
  color: #999;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 1.5px solid #e8e8e8;
  border-radius: 20px;
  background: #fff;
  font-size: 13px;
}

.chip-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.chip-name {
  font-weight: 500;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip-code {
  color: #999;
  font-size: 11px;
}

.chip-remove {
  background: none;
  border: none;
  cursor: pointer;
  color: #bbb;
  font-size: 16px;
  line-height: 1;
  padding: 0;
  margin-left: 2px;
}

.chip-remove:hover {
  color: #ff4444;
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
  transition: all 0.2s;
}

.tab:last-child {
  border-right: none;
}

.tab.active {
  background: #1677ff;
  color: #fff;
}

.chart-container {
  position: relative;
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  overflow: hidden;
}

.chart-canvas {
  width: 100%;
  height: 360px;
}

.chart-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #999;
  font-size: 14px;
  z-index: 1;
  background: #fff;
}
</style>
