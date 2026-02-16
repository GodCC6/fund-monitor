<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '../api'

echarts.use([LineChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

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

async function loadData() {
  loading.value = true
  empty.value = false

  try {
    let xData: string[] = []
    let yData: number[] = []

    if (activePeriod.value === '1d') {
      const data = await api.getIntraday(props.fundCode)
      xData = data.times
      yData = data.navs
    } else {
      const data = await api.getNavHistory(props.fundCode, activePeriod.value)
      xData = data.dates
      yData = data.navs
    }

    if (xData.length === 0) {
      empty.value = true
      if (chart) chart.clear()
      return
    }

    await nextTick()
    initChart()
    if (!chart) return

    const isGain = (yData[yData.length - 1] ?? 0) >= (yData[0] ?? 0)
    const color = isGain ? '#ff4444' : '#00c853'
    const areaColor = isGain ? 'rgba(255,68,68,0.12)' : 'rgba(0,200,83,0.12)'

    chart.setOption({
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          const p = params[0]
          return `${p.axisValue}<br/>净值: <b>${p.data.toFixed(4)}</b>`
        },
      },
      grid: {
        left: 60,
        right: 16,
        top: 16,
        bottom: activePeriod.value === '1d' ? 30 : 50,
      },
      xAxis: {
        type: 'category',
        data: xData,
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
        scale: true,
        splitLine: { lineStyle: { color: '#f5f5f5' } },
        axisLabel: { fontSize: 11, color: '#999' },
      },
      dataZoom: activePeriod.value === '1d' ? [] : [
        { type: 'inside', start: 0, end: 100 },
      ],
      series: [
        {
          type: 'line',
          data: yData,
          smooth: true,
          symbol: 'none',
          lineStyle: { color, width: 2 },
          areaStyle: { color: areaColor },
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
