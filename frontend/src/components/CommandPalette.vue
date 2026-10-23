<script setup lang="ts">
import { computed, nextTick, ref, watch, type Component } from 'vue'
import { useRouter } from 'vue-router'
import { Activity, Boxes, CornerDownLeft, FileCode2, Palette, Search, Server, Sparkles } from 'lucide-vue-next'
import { NAV } from '@/router'
import { api } from '@/api/http'
import { useAppStore } from '@/stores/app'
import { useLiveStore } from '@/stores/live'
import { THEMES, useThemeStore } from '@/stores/theme'
import { plans, MACHINE_STATUS_TEXT } from '@/mock/cluster'

interface Cmd { id: string; group: string; label: string; hint?: string; icon: Component; run: () => void }
interface Hit { id: string; text: string }

const app = useAppStore()
const live = useLiveStore()
const theme = useThemeStore()
const router = useRouter()
const q = ref('')
const active = ref(0)
const input = ref<HTMLInputElement>()
const listEl = ref<HTMLElement>()
const remote = ref<Cmd[]>([])
let searchTimer = 0

const all = computed<Cmd[]>(() => [
  ...NAV.map((n) => ({ id: n.path, group: '页面', label: n.title, hint: n.code, icon: n.icon, run: () => router.push(n.path) })),
  ...live.machines.map((m) => ({ id: m.machine_id, group: '机台', label: `${m.machine_id} · ${m.serial}`, hint: m.comm_status === 'DISCONNECTED' ? '通信断开' : MACHINE_STATUS_TEXT[m.status], icon: Server, run: () => router.push({ path: '/devices', query: { m: m.machine_id } }) })),
  ...live.batchStats.map((b) => ({ id: b.batch_id, group: '批次', label: `${b.batch_id} · ${b.model}`, hint: `${((b.passed / Math.max(1, b.tested)) * 100).toFixed(1)}%`, icon: Boxes, run: () => router.push({ path: '/report', query: { b: b.batch_id } }) })),
  ...plans.map((p) => ({ id: p.plan_id, group: '测试方案', label: `${p.name}`, hint: p.version ? `v${p.version}` : '草稿', icon: FileCode2, run: () => router.push({ path: '/plans', query: { p: p.plan_id } }) })),
  ...THEMES.map((t) => ({ id: `theme-${t.id}`, group: '主题', label: `切换主题：${t.name}`, hint: t.en, icon: Palette, run: () => theme.set(t.id) })),
])

function hitCmds(rows: Hit[], group: string, icon: Component, run: (hit: Hit) => void): Cmd[] {
  return rows.map((hit) => ({ id: `${group}-${hit.id}`, group, label: hit.text, hint: hit.id, icon, run: () => run(hit) }))
}

async function pullSearch(term: string) {
  if (!term) {
    remote.value = []
    return
  }
  try {
    const body = await api<{ machines?: Hit[]; batches?: Hit[]; plans?: Hit[]; runs?: Hit[] }>(`/search?q=${encodeURIComponent(term)}&limit=8`)
    remote.value = [
      ...hitCmds(body.machines || [], '机台', Server, (hit) => router.push({ path: '/devices', query: { m: hit.id } })),
      ...hitCmds(body.batches || [], '批次', Boxes, (hit) => router.push({ path: '/report', query: { b: hit.id } })),
      ...hitCmds(body.plans || [], '测试方案', FileCode2, (hit) => router.push({ path: '/plans', query: { p: hit.id } })),
      ...hitCmds(body.runs || [], '测试记录', Activity, (hit) => router.push({ path: '/testing', query: { tab: 'runs', r: hit.id } })),
    ]
  } catch {
    remote.value = []
  }
}

const results = computed<Cmd[]>(() => {
  const k = q.value.trim().toLowerCase()
  if (!k) return all.value.filter((item) => item.group === '页面')
  const local = remote.value.length
    ? all.value.filter((item) => (item.group === '页面' || item.group === '主题') && (item.label + item.id + item.group).toLowerCase().includes(k))
    : all.value.filter((item) => (item.label + item.id + item.group).toLowerCase().includes(k))
  const seen = new Set(remote.value.map((item) => item.hint))
  const merged = [...remote.value, ...local.filter((item) => !seen.has(item.id))]
  merged.push({ id: 'ask', group: 'AI 分析', label: `向分析 Agent 提问：“${q.value.trim()}”`, icon: Sparkles, run: () => router.push({ path: '/agent', query: { q: q.value.trim() } }) })
  return merged.slice(0, 20)
})

watch(results, () => (active.value = 0))
watch(q, (term) => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => { void pullSearch(term.trim()) }, 180)
})
watch(
  () => app.paletteOpen,
  async (v) => {
    if (v) {
      q.value = ''
      remote.value = []
      await nextTick()
      input.value?.focus()
    }
  },
)

function exec(c?: Cmd) {
  if (!c) return
  c.run()
  app.paletteOpen = false
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') { app.paletteOpen = false; return }
  if (!results.value.length) return
  if (e.key === 'ArrowDown') { e.preventDefault(); active.value = (active.value + 1) % results.value.length; scroll() }
  else if (e.key === 'ArrowUp') { e.preventDefault(); active.value = (active.value - 1 + results.value.length) % results.value.length; scroll() }
  else if (e.key === 'Enter') { e.preventDefault(); exec(results.value[active.value]) }
}
function scroll() {
  nextTick(() => listEl.value?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' }))
}
</script>

<template>
  <Transition name="fade">
    <div v-if="app.paletteOpen" class="mask" @mousedown.self="app.paletteOpen = false">
      <div class="pal" role="dialog" aria-modal="true" aria-label="命令面板">
        <div class="in">
          <Search :size="18" class="muted" />
          <input
            ref="input"
            v-model="q"
            class="grow"
            placeholder="跳转页面、查找机台 / 批次 / 方案，或输入问题交给 Agent…"
            role="combobox"
            aria-expanded="true"
            aria-controls="pal-list"
            @keydown="onKey"
          />
          <span class="kbd">Esc</span>
        </div>
        <ul id="pal-list" ref="listEl" class="list" role="listbox">
          <template v-for="(c, i) in results" :key="c.id">
            <li v-if="i === 0 || results[i - 1].group !== c.group" class="grp code-label" role="presentation">{{ c.group }}</li>
            <li
              role="option"
              :aria-selected="i === active"
              class="opt"
              :class="{ ai: c.id === 'ask' }"
              @mousemove="active = i"
              @click="exec(c)"
            >
              <component :is="c.icon" :size="16" />
              <span class="grow ellipsis">{{ c.label }}</span>
              <span v-if="c.hint" class="mono fs-xs muted">{{ c.hint }}</span>
              <CornerDownLeft v-if="i === active" :size="14" class="muted" />
            </li>
          </template>
          <li v-if="!results.length" class="none">无匹配结果</li>
        </ul>
        <div class="ft">
          <span><span class="kbd">↑</span><span class="kbd">↓</span> 选择</span>
          <span><span class="kbd">Enter</span> 执行</span>
          <span class="grow" />
          <span class="muted">支持自然语言：例如“对比 M03 与 M07 本周 Rc”</span>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.mask { position: fixed; inset: 0; z-index: 90; background: rgba(12, 16, 20, 0.32); display: flex; justify-content: center; padding-top: 12vh; }
.pal { width: min(640px, 92vw); height: fit-content; background: var(--c-surface); border: var(--bw) solid var(--c-border-strong); border-top: 3px solid var(--c-primary); box-shadow: var(--shadow-pop); }
.in { display: flex; align-items: center; gap: 10px; height: 52px; padding: 0 14px; border-bottom: var(--bw) solid var(--c-border); }
.in input { border: 0; outline: 0; background: transparent; font-size: var(--fs-lg); }
.list { list-style: none; margin: 0; padding: 6px; max-height: 50vh; overflow: auto; }
.grp { padding: 8px 8px 4px; font-size: 10px; }
.opt { display: flex; align-items: center; gap: 10px; height: 36px; padding: 0 10px; cursor: pointer; color: var(--c-text-2); }
.opt[aria-selected='true'] { background: var(--c-primary-weak); color: var(--c-text); box-shadow: inset 3px 0 0 var(--c-primary); }
.opt.ai { color: var(--c-primary); font-weight: 600; }
.none { padding: 24px; text-align: center; color: var(--c-text-3); }
.ft { display: flex; align-items: center; gap: 14px; padding: 8px 12px; border-top: var(--bw) solid var(--c-border); background: var(--c-surface-2); font-size: var(--fs-xs); color: var(--c-text-2); }
.ft .kbd { margin-right: 3px; }
.fade-enter-active, .fade-leave-active { transition: opacity 120ms var(--ease); }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
