<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
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

function axisData(axis: any): string[] {
  const one = Array.isArray(axis) ? axis[0] : axis
  return Array.isArray(one?.data) ? one.data.map((item: unknown) => String(item)) : []
}

function axisName(axis: any): string {
  const one = Array.isArray(axis) ? axis[0] : axis
  return String(one?.name || '')
}

function seriesAt(option: any, index: number) {
  const series = option?.series
  return Array.isArray(series) ? series[index] || {} : {}
}

function rawValue(row: any): unknown {
  const data = row?.data
  if (data && typeof data === 'object' && !Array.isArray(data) && 'value' in data) return data.value
  return row?.value
}

function formatNumber(value: unknown, unit: string): string {
  if (value == null || value === '-' || value === '') return '—'
  const number = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(number)) return String(value)
  if (unit === '片') return `${Math.round(number)} 片`
  if (unit === '%') return `${number.toFixed(2)} %`
  const text = number.toFixed(2)
  return unit ? `${text} ${unit}` : text
}

function rowUnit(row: any, option: any, fallback: string): string {
  const data = row?.data
  if (data && typeof data === 'object' && !Array.isArray(data) && data.unit) return String(data.unit)
  const series = seriesAt(option, row.seriesIndex ?? 0)
  if (series.unit) return String(series.unit)
  return fallback
}

function rowRole(row: any, option: any, fallback: string): string {
  const series = seriesAt(option, row.seriesIndex ?? 0)
  const role = String(series.role || fallback || '')
  const name = String(row.seriesName || series.name || '')
  if (!role || name === role || name.includes(role)) return ''
  return role
}

function boxValues(value: unknown): unknown[] {
  const rows = Array.isArray(value) ? value : []
  return rows.length >= 6 ? rows.slice(1, 6) : rows.slice(0, 5)
}

function scatterOnly(option: any): boolean {
  const series = option?.series
  return Array.isArray(series) && series.length > 0 && series.every((item: any) => item?.type === 'scatter')
}

function chartScope(option: any): string {
  const saved = option?.tip?.scope
  if (saved) return String(saved)
  const series = Array.isArray(option?.series) ? option.series : []
  if (series.some((item: any) => item?.type === 'heatmap')) return '分机台槽'
  const labels = [...axisData(option?.xAxis), ...axisData(option?.yAxis)]
  if (labels.some((label) => /M\d+/i.test(label) && /槽\d+/.test(label))) return '分机台槽'
  if (labels.some((label) => /^第\d+片$/.test(label))) return '整批'
  if (labels.some((label) => /^Temp_/i.test(label))) return '整批'
  const xName = axisName(option?.xAxis)
  if (xName === '批次') return '分批次'
  if (xName === '机台') return '分机台'
  if (xName === '槽位') return '分机台槽'
  return ''
}

function joinHead(parts: string[]): string {
  return parts.filter((part, index) => part && parts.indexOf(part) === index).join(' · ')
}

function formatTip(params: unknown, option: any): string {
  const rows = (Array.isArray(params) ? params : [params]).filter(Boolean) as any[]
  const visible = rows.filter((row) => {
    const data = row?.data
    if (data && typeof data === 'object' && !Array.isArray(data) && data.spanBase) return false
    const value = rawValue(row)
    return value != null && value !== '-'
  })
  if (!visible.length) return ''
  const tip = option.tip || {}
  const first = visible[0]
  const kind = String(first.seriesType || seriesAt(option, first.seriesIndex ?? 0).type || '')
  const scope = chartScope(option)
  const namedUnit = axisName(option.yAxis)
  const unitFallback = String(tip.unit || (['℃', 'W', '片', 'g', 's', '%', '℃/W'].includes(namedUnit) ? namedUnit : ''))
  const roleFallback = String(tip.role || (kind === 'heatmap' ? '均值' : ''))
  if (kind === 'heatmap') {
    const xs = axisData(option.xAxis)
    const ys = axisData(option.yAxis)
    const xIndex = Array.isArray(first.value) ? Number(first.value[0]) : 0
    const head = joinHead([xs[xIndex] || first.name || '', scope])
    const lines = visible.map((row) => {
      const value = Array.isArray(row.value) && row.value.length >= 3 ? row.value : (Array.isArray(row.data) ? row.data : [])
      const machine = ys[Number(value[1])] || ''
      const measure = String(row.seriesName || '')
      const unit = rowUnit(row, option, unitFallback || (/^(Temp_|室温)/.test(measure) ? '℃' : ''))
      return [machine, measure, rowRole(row, option, roleFallback), formatNumber(value[2], unit)].filter(Boolean).join(' ')
    })
    return [head, ...lines].filter(Boolean).join('<br/>')
  }
  if (kind === 'boxplot') {
    const category = String(first.axisValue || first.name || '')
    const seriesName = String(first.seriesName || '')
    const measure = /^Temp_|^室温|^power/i.test(seriesName) ? seriesName : ''
    const head = joinHead([category, measure !== category ? measure : '', /M\d+/i.test(category) && /槽\d+/.test(category) ? '' : scope])
    const parts = Array.isArray(tip.parts) && tip.parts.length ? tip.parts : ['最小值', '下四分位', '中位数', '上四分位', '最大值']
    const lines: string[] = []
    for (const row of visible) {
      const values = boxValues(Array.isArray(row.value) ? row.value : row.data)
      const unit = rowUnit(row, option, unitFallback || '℃')
      const prefix = visible.length > 1 && row.seriesName ? `${row.seriesName} ` : ''
      parts.forEach((name: string, index: number) => lines.push(`${prefix}${name} ${formatNumber(values[index], unit)}`))
      const low = Number(values[0])
      const high = Number(values[4])
      if (Number.isFinite(low) && Number.isFinite(high)) lines.push(`${prefix}极差 ${formatNumber(high - low, unit)}`)
    }
    return [head, ...lines].join('<br/>')
  }
  if (kind === 'candlestick') {
    const head = String(first.axisValue || first.name || '')
    const lines: string[] = []
    for (const row of visible) {
      const values = Array.isArray(row.value) ? row.value : []
      const unit = rowUnit(row, option, unitFallback)
      const prefix = row.seriesName ? `${row.seriesName} ` : ''
      lines.push(`${prefix}最小值 ${formatNumber(values[2], unit)}`)
      lines.push(`${prefix}均值 ${formatNumber(values[0], unit)}`)
      lines.push(`${prefix}最大值 ${formatNumber(values[3], unit)}`)
    }
    return [head, ...lines].join('<br/>')
  }
  if (kind === 'scatter') {
    const xName = axisName(option.xAxis) || '横轴'
    const yName = axisName(option.yAxis) || '纵轴'
    return visible.map((row) => {
      const value = Array.isArray(row.value) ? row.value : [row.axisValue, rawValue(row)]
      const unit = rowUnit(row, option, unitFallback)
      const who = row.seriesName && row.seriesName !== yName ? String(row.seriesName) : ''
      return [`${who} ${xName} ${value[0]}`.trim(), `${rowRole(row, option, roleFallback)} ${yName} ${formatNumber(value[1], unit)}`.trim()].join('<br/>')
    }).join('<br/><br/>')
  }
  const head = String(first.axisValue ?? first.name ?? '')
  const lines = visible.map((row) => {
    const unit = rowUnit(row, option, unitFallback)
    const data = row.data
    if (data && typeof data === 'object' && !Array.isArray(data) && data.minimum != null && data.maximum != null) {
      return [row.marker || '', row.seriesName || '', `最小 ${formatNumber(data.minimum, unit)}`, `最大 ${formatNumber(data.maximum, unit)}`, `极差 ${formatNumber(data.value, unit)}`].filter(Boolean).join(' ')
    }
    return [row.marker || '', row.seriesName || '', rowRole(row, option, roleFallback), formatNumber(rawValue(row), unit)].filter(Boolean).join(' ')
  })
  return [joinHead([head, scope]), ...lines].filter(Boolean).join('<br/>')
}

function echartsOf() {
  const target = chart.value as any
  if (!target) return null
  if (typeof target.setOption === 'function' && typeof target.getZr === 'function') return target
  if (typeof target.chart?.setOption === 'function') return target.chart
  return null
}

function bindTip() {
  const instance = echartsOf()
  if (!instance) return
  instance.setOption({
    tooltip: {
      trigger: scatterOnly(props.option) ? 'item' : 'axis',
      confine: true,
      formatter: (params: unknown) => formatTip(params, props.option),
    },
  })
}

onMounted(() => { nextTick(bindTip) })
watch(() => props.option, () => { nextTick(bindTip) }, { deep: true })

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
  const incoming = o.tooltip && typeof o.tooltip === 'object' ? o.tooltip : {}
  const tooltip = {
    backgroundColor: t.surface,
    borderColor: t['border-strong'],
    borderWidth: 1,
    padding: [6, 10],
    textStyle: { color: t.text, fontSize: 12, fontFamily: t.mono },
    axisPointer: { lineStyle: { color: t['text-3'], type: 'dashed' }, crossStyle: { color: t['text-3'] } },
    extraCssText: 'border-radius:2px;box-shadow:0 6px 16px -6px rgba(0,0,0,.25);',
    ...incoming,
    trigger: incoming.trigger || (scatterOnly(o) ? 'item' : 'axis'),
    formatter: typeof incoming.formatter === 'function' ? incoming.formatter : (params: unknown) => formatTip(params, o),
  }
  return {
    animationDuration: 300,
    animationDurationUpdate: 300,
    color: t.chart,
    textStyle: { fontFamily: t.sans, color: t['text-2'] },
    ...o,
    tooltip,
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
