<script setup lang="ts">
import { computed, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, HeatmapChart, LineChart, PieChart, ScatterChart, BoxplotChart } from 'echarts/charts'
import {
  DataZoomComponent, GridComponent, LegendComponent, MarkAreaComponent, MarkLineComponent, MarkPointComponent,
  TooltipComponent, VisualMapComponent,
} from 'echarts/components'
import { useTokens } from '@/composables/useTokens'
import { useThemeStore } from '@/stores/theme'

use([
  CanvasRenderer, BarChart, LineChart, ScatterChart, HeatmapChart, PieChart, BoxplotChart,
  GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, MarkAreaComponent, MarkPointComponent,
  VisualMapComponent, DataZoomComponent,
])

const props = withDefaults(defineProps<{ option: Record<string, any>; height?: number | string }>(), { height: 240 })
const tk = useTokens()
const theme = useThemeStore()

function liftCumulative(axis: any) {
  if (!Array.isArray(axis) || axis.length < 2) return axis
  return axis.map((item: any, index: number) => (index > 0 && item?.max === 100 ? { ...item, max: 120 } : item))
}

const chart = ref<{ getDataURL?: (opts: { type: string; pixelRatio: number; backgroundColor: string }) => string; chart?: { getDataURL?: (opts: { type: string; pixelRatio: number; backgroundColor: string }) => string } } | null>(null)
function image() {
  const target = chart.value
  const api = typeof target?.getDataURL === 'function' ? target : target?.chart
  return api?.getDataURL?.({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' }) ?? ''
}
defineExpose({ image })

const merged = computed(() => {
  const t = tk.value
  const axis = (a: any) => ({
    axisLine: { lineStyle: { color: t['border-strong'] } },
    axisTick: { show: false },
    axisLabel: { color: t['text-3'], fontFamily: t.mono, fontSize: 10 },
    splitLine: { lineStyle: { color: t.border, type: [3, 3] } },
    nameTextStyle: { color: t['text-3'], fontSize: 10 },
    ...a,
  })
  const o = props.option
  const mapAxis = (x: any) => (x === undefined ? undefined : Array.isArray(x) ? x.map(axis) : axis(x))
  const dual = Array.isArray(o.yAxis)
  const grid = { left: 48, right: dual ? 72 : 18, top: dual ? 40 : 28, bottom: 40, containLabel: true }
  const legend = {
    textStyle: { color: t['text-2'], fontSize: 11 },
    itemWidth: 12,
    itemHeight: 3,
    icon: 'rect',
    top: 0,
    ...(dual ? { left: 0 } : { right: 0 }),
  }
  const yAxis = mapAxis(o.yAxis)
  return {
    animationDuration: 300,
    animationDurationUpdate: 300,
    color: t.chart,
    textStyle: { fontFamily: t.sans, color: t['text-2'] },
    tooltip: {
      trigger: 'axis',
      backgroundColor: t.surface,
      borderColor: t['border-strong'],
      borderWidth: 1,
      padding: [6, 10],
      textStyle: { color: t.text, fontSize: 12, fontFamily: t.mono },
      axisPointer: { lineStyle: { color: t['text-3'], type: 'dashed' }, crossStyle: { color: t['text-3'] } },
      extraCssText: 'border-radius:2px;box-shadow:0 6px 16px -6px rgba(0,0,0,.25);',
    },
    ...o,
    grid: o.grid || grid,
    legend: o.legend || legend,
    xAxis: mapAxis(o.xAxis),
    yAxis: liftCumulative(yAxis),
  }
})
</script>

<template>
  <VChart
    ref="chart"
    :key="theme.revision"
    class="chart"
    :option="merged"
    autoresize
    :style="{ height: typeof props.height === 'number' ? `${props.height}px` : props.height }"
  />
</template>

<style scoped>
.chart { width: 100%; }
</style>
