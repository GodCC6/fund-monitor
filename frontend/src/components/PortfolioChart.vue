<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '../api'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

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
          return `<div style="font-size:12px;color:#666;margin-bottom:4px">${d}</div>
                  <div>组合市值: <b>${val.toFixed(2)}</b></div>
                  <div>收益率: <b style="color:${lineColor}">${sign}${pct.toFixed(2)}%</b></div>`
        },
      },
      grid: { left: 55, right: 16, top: 16, bottom: 40 },
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
        smooth: false,
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
        v-for="p in periods"
        :key="p.key"
        :class="['tab', { active: activePeriod === p.key }]"
        @click="activePeriod = p.key"
      >{{ p.label }}</button>
    </div>
    <div class="chart-container">
      <div v-if="loading" class="chart-overlay">加载中...</div>
      <div v-else-if="empty" class="chart-overlay">
        暂无历史数据
        <span class="hint-text">每个交易日收盘后自动记录</span>
      </div>
      <div ref="chartRef" class="chart-canvas"></div>
    </div>
  </div>
</template>

<style scoped>
.portfolio-chart {
  margin: 16px 0;
}

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
  height: 240px;
}

.chart-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #999;
  font-size: 14px;
  z-index: 1;
  background: #fff;
  gap: 6px;
}

.hint-text {
  font-size: 12px;
  color: #bbb;
}
</style>
