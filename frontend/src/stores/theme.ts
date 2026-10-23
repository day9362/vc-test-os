import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export type ThemeId = 'steel' | 'signal' | 'graphite'

export interface ThemeMeta {
  id: ThemeId
  name: string
  en: string
  desc: string
  swatches: string[]
}

export const THEMES: ThemeMeta[] = [
  {
    id: 'steel',
    name: '钢蓝',
    en: 'STEEL',
    desc: '冷灰底 + 工业蓝，标准控制台',
    swatches: ['#e9edf1', '#ffffff', '#1b4f9c', '#10161d'],
  },
  {
    id: 'signal',
    name: '信号橙',
    en: 'SIGNAL',
    desc: '暖白底 + 安全橙，车间大屏高辨识',
    swatches: ['#eeebe4', '#fffefb', '#c2410c', '#1a1814'],
  },
  {
    id: 'graphite',
    name: '石墨青',
    en: 'GRAPHITE',
    desc: '灰绿底 + 石墨青，长时间值守低疲劳',
    swatches: ['#e7ebea', '#fbfcfc', '#0b6b63', '#26302d'],
  },
]

const KEY = 'vc-theme'

export const useThemeStore = defineStore('theme', () => {
  const initial = (document.documentElement.dataset.theme as ThemeId) || 'steel'
  const theme = ref<ThemeId>(initial)
  /** 每次切换自增，供图表等非 CSS 渲染的组件感知主题变化 */
  const revision = ref(0)

  watch(theme, (t) => {
    document.documentElement.dataset.theme = t
    try {
      localStorage.setItem(KEY, t)
    } catch {
      /* 隐私模式下忽略 */
    }
    revision.value++
  })

  function set(t: ThemeId) {
    theme.value = t
  }
  function cycle() {
    const i = THEMES.findIndex((x) => x.id === theme.value)
    theme.value = THEMES[(i + 1) % THEMES.length].id
  }

  return { theme, revision, set, cycle }
})
