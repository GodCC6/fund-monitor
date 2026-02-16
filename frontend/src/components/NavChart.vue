<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '../api'

echarts.use([LineChart, GridComponent, TooltipComponent, DataZoomComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{ fundCode: string }>()

const periods = [
  { key: '1d', label: '当日' },
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

function initChart() {
  if (chartRef.value && !chart) {
    chart = echarts.init(chartRef.value)
  }
}

function disposeChart() {
  if (chart) {
    chart.dispose()
    chart = null
  }
}

interface ChartData {
  xData: string[]
  fundNavs: number[]
  indexValues: number[]
  indexName: string
}

async function loadData() {
  loading.value = true
  empty.value = false

  try {
    let chartData: ChartData

    if (activePeriod.value === '1d') {
      const [fundData, indexData] = await Promise.all([
        api.getIntraday(props.fundCode),
        api.getIndexIntraday(),
      ])

      // Use index times as X axis, map fund snapshots to nearest minute
      const fundMap = new Map<string, number>()
      for (let i = 0; i < fundData.times.length; i++) {
        const t = fundData.times[i]!
        fundMap.set(t, fundData.navs[i]!)
      }

      const xData: string[] = []
      const fundNavs: number[] = []
      const indexValues: number[] = []
      let lastFundNav = fundData.last_nav

      for (let i = 0; i < indexData.times.length; i++) {
        const t = indexData.times[i]!
        xData.push(t)
        indexValues.push(indexData.values[i]!)
        if (fundMap.has(t)) {
          lastFundNav = fundMap.get(t)!
        }
        fundNavs.push(lastFundNav)
      }

      if (fundData.times.length === 0 && indexData.times.length === 0) {
        empty.value = true
        if (chart) chart.clear()
        loading.value = false
        return
      }

      chartData = { xData, fundNavs, indexValues, indexName: indexData.name }
    } else {
      const [fundData, indexData] = await Promise.all([
        api.getNavHistory(props.fundCode, activePeriod.value),
        api.getIndexHistory(activePeriod.value),
      ])

      if (fundData.dates.length === 0) {
        empty.value = true
        if (chart) chart.clear()
        loading.value = false
        return
      }

      // Align dates — use fund dates as base, find matching index values
      const indexMap = new Map<string, number>()
      for (let i = 0; i < indexData.dates.length; i++) {
        indexMap.set(indexData.dates[i]!, indexData.values[i]!)
      }

      const xData: string[] = []
      const fundNavs: number[] = []
      const indexValues: number[] = []
      let lastIndex = indexData.values.length > 0 ? indexData.values[0]! : 0

      for (let i = 0; i < fundData.dates.length; i++) {
        const d = fundData.dates[i]!
        xData.push(d)
        fundNavs.push(fundData.navs[i]!)
        if (indexMap.has(d)) {
          lastIndex = indexMap.get(d)!
        }
        indexValues.push(lastIndex)
      }

      chartData = { xData, fundNavs, indexValues, indexName: indexData.name }
    }

    await nextTick()
    initChart()
    if (!chart) return

    // Normalize to percentage change from start
    const fundBase = chartData.fundNavs[0] ?? 1
    const indexBase = chartData.indexValues[0] ?? 1
    const fundPcts = chartData.fundNavs.map(v => fundBase !== 0 ? (v / fundBase - 1) * 100 : 0)
    const indexPcts = chartData.indexValues.map(v => indexBase !== 0 ? (v / indexBase - 1) * 100 : 0)

    const lastFundPct = fundPcts[fundPcts.length - 1] ?? 0
    const isGain = lastFundPct >= 0
    const fundColor = isGain ? '#ff4444' : '#00c853'
    const fundAreaColor = isGain ? 'rgba(255,68,68,0.08)' : 'rgba(0,200,83,0.08)'
    const indexColor = '#1677ff'

    chart.setOption({
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          const time = params[0]?.axisValue || ''
          let html = `<div style="font-size:12px;color:#666;margin-bottom:4px">${time}</div>`
          for (const p of params) {
            const dot = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color};margin-right:4px"></span>`
            if (p.seriesIndex === 0) {
              const nav = chartData.fundNavs[p.dataIndex] ?? 0
              html += `<div>${dot}基金净值: ${nav.toFixed(4)} (${p.data >= 0 ? '+' : ''}${p.data.toFixed(2)}%)</div>`
            } else {
              const val = chartData.indexValues[p.dataIndex] ?? 0
              html += `<div>${dot}${chartData.indexName}: ${val.toFixed(2)} (${p.data >= 0 ? '+' : ''}${p.data.toFixed(2)}%)</div>`
            }
          }
          return html
        },
      },
      legend: {
        data: ['基金净值', chartData.indexName],
        top: 0,
        textStyle: { fontSize: 12 },
      },
      grid: {
        left: 50,
        right: 16,
        top: 30,
        bottom: activePeriod.value === '1d' ? 30 : 50,
      },
      xAxis: {
        type: 'category',
        data: chartData.xData,
        axisLabel: {
          fontSize: 11,
          color: '#999',
          rotate: activePeriod.value === '1d' ? 0 : 30,
        },
        axisLine: { lineStyle: { color: '#e8e8e8' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          fontSize: 11,
          color: '#999',
          formatter: '{value}%',
        },
        splitLine: { lineStyle: { color: '#f5f5f5' } },
      },
      dataZoom: activePeriod.value === '1d' ? [] : [
        { type: 'inside', start: 0, end: 100 },
      ],
      series: [
        {
          name: '基金净值',
          type: 'line',
          data: fundPcts,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: fundColor, width: 2 },
          areaStyle: { color: fundAreaColor },
        },
        {
          name: chartData.indexName,
          type: 'line',
          data: indexPcts,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: indexColor, width: 1.5, type: 'dashed' },
        },
      ],
    }, true)

    chart.resize()
  } catch (e) {
    empty.value = true
  } finally {
    loading.value = false
  }
}

function handleResize() {
  chart?.resize()
}

watch(activePeriod, loadData)
watch(() => props.fundCode, loadData)

onMounted(() => {
  window.addEventListener('resize', handleResize)
  loadData()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  disposeChart()
})
</script>

<template>
  <div class="nav-chart">
    <div class="period-tabs">
      <button
        v-for="p in periods"
        :key="p.key"
        :class="['tab', { active: activePeriod === p.key }]"
        @click="activePeriod = p.key"
      >
        {{ p.label }}
      </button>
    </div>
    <div class="chart-container">
      <div v-if="loading" class="chart-overlay">加载中...</div>
      <div v-else-if="empty" class="chart-overlay">暂无数据</div>
      <div ref="chartRef" class="chart-canvas"></div>
    </div>
  </div>
</template>

<style scoped>
.nav-chart {
  margin: 16px 0;
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
  padding: 8px 0;
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

.tab:hover {
  background: #f9f9f9;
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
  height: 300px;
}

.chart-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #999;
  font-size: 14px;
  z-index: 1;
  background: #fff;
}
</style>
