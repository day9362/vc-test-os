<script setup lang="ts">
import { computed } from 'vue'
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
  return {
    animationDuration: 300,
    animationDurationUpdate: 300,
    color: t.chart,
    textStyle: { fontFamily: t.sans, color: t['text-2'] },
    grid: { left: 44, right: 16, top: 24, bottom: 28, containLabel: false },
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
    legend: { textStyle: { color: t['text-2'], fontSize: 11 }, itemWidth: 12, itemHeight: 3, icon: 'rect', top: 0, right: 0 },
    ...o,
    xAxis: mapAxis(o.xAxis),
    yAxis: mapAxis(o.yAxis),
  }
})
</script>

<template>
  <VChart
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
