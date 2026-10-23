import { computed } from 'vue'
import { useThemeStore } from '@/stores/theme'

const NAMES = [
  'bg', 'surface', 'surface-2', 'surface-3', 'border', 'border-strong', 'text', 'text-2', 'text-3',
  'primary', 'primary-weak', 'accent', 'ok', 'ok-weak', 'warn', 'warn-weak', 'danger', 'danger-weak', 'info', 'idle',
] as const

type Key = (typeof NAMES)[number]
export type Tokens = Record<Key, string> & { chart: string[]; mono: string; sans: string }

/** 读取当前主题的 CSS 变量，主题切换后自动重新计算（用于 ECharts 等 canvas 渲染） */
export function useTokens() {
  const theme = useThemeStore()
  return computed<Tokens>(() => {
    void theme.revision
    const cs = getComputedStyle(document.documentElement)
    const v = (n: string) => cs.getPropertyValue(n).trim()
    const t = {} as Tokens
    NAMES.forEach((n) => ((t as any)[n] = v(`--c-${n}`)))
    t.chart = [1, 2, 3, 4, 5, 6].map((i) => v(`--chart-${i}`))
    t.mono = v('--font-mono')
    t.sans = v('--font-sans')
    return t
  })
}
