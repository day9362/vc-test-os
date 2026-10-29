<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowUp, BarChart3, Bot, Check, ChevronRight, Database, FileCode2, Loader2, Plus, ShieldCheck, Sparkles, SquareTerminal, User, Wrench, X,
} from 'lucide-vue-next'
import Panel from '@/components/Panel.vue'
import EChart from '@/components/EChart.vue'
import { api, currentToken } from '@/api/http'
import type { BatchStat } from '@/api/types'
import { useAppStore } from '@/stores/app'
import { hms } from '@/utils/format'

const app = useAppStore()
const route = useRoute()
const router = useRouter()

type Block =
  | { type: 'tool'; name: string; args: string; result: string; write?: false }
  | { type: 'table'; id: string; title: string; columns: string[]; rows: string[][]; more: number }
  | { type: 'chart'; id: string; title: string; option: Record<string, any> }
  | { type: 'choices'; id: string; options: { label: string; text: string }[]; chosen: number | null }
  | { type: 'plan'; plan_id: string; name: string; fields: [string, string][] }
  | { type: 'action'; id: string; name: string; desc: string; arguments: Record<string, any>; status: 'pending' | 'done' | 'rejected'; result: string; risk: 'low' | 'high' }
interface Msg { id: number; role: 'user' | 'agent'; text: string; blocks: Block[]; module?: string; tokens?: [number, number]; time: number; live?: boolean }

const CAPS = [
  { key: 'analysis', icon: BarChart3, title: '跨批次分析', module: 'agent.analysis', prompts: ['对比最近 3 个 tb172 批次的良率，找出差异原因', 'M01 的 Rc 为什么一直偏高？', '本班 Temp_T1-T14 不合格是机台问题还是来料问题？'] },
  { key: 'plan', icon: FileCode2, title: '自然语言 → 测试方案', module: 'agent.plan', prompts: ['给 HVP1307G17-1 做一个 3.5W、120g、测 3 分钟的方案', 'tb179 竖放 90 度测 4 分钟，温差上限 4.2'] },
  { key: 'ops', icon: Wrench, title: '设备操作', module: 'agent.ops', prompts: ['把 M01 的 T1 通道补偿 -0.18 ℃', '给 M02 关机后再上电', '停止当前连续生产', '把 M03 的仿真倍率改成 2'] },
]

let mid = 0
const input = ref('')
const busy = ref(false)
const acting = ref('')
const scroller = ref<HTMLElement>()
const viewKey = ref(0)
const scope = ref({ model: '', batches: [] as string[], machines: [] as string[] })
const modelOptions = ref<{ model: string }[]>([])
const batchRows = ref<BatchStat[]>([])
const publishedPlans = ref(0)
const machineCount = ref(0)
const visibleBatches = computed(() => batchRows.value.filter((row) => row.model === scope.value.model))
const scopeHint = computed(() => `发送时带上分析范围：${scope.value.model || '未选型号'} · ${scope.value.batches.length} 个批次`)

function yieldText(row: BatchStat) {
  if (!row.tested) return '—'
  return `${((row.passed / row.tested) * 100).toFixed(1)}%`
}

async function loadScope() {
  const [modelRows, statPage, planRows, machineRows] = await Promise.all([
    api<{ model: string }[]>('/models'),
    api<{ items: BatchStat[] }>('/batch-stats?limit=50'),
    api<{ meta?: { draft?: boolean } }[]>('/plans'),
    api<{ machine_id: string }[]>('/machines'),
  ])
  modelOptions.value = modelRows
  batchRows.value = statPage.items || []
  publishedPlans.value = planRows.filter((row) => row.meta && !row.meta.draft).length
  machineCount.value = machineRows.length
  const preferred = modelOptions.value.find((row) => batchRows.value.some((batch) => batch.model === row.model))
  scope.value.model = preferred?.model || modelOptions.value[0]?.model || ''
  scope.value.batches = visibleBatches.value.slice(0, 3).map((row) => row.batch_id)
}

watch(() => scope.value.model, () => {
  scope.value.batches = visibleBatches.value.slice(0, 3).map((row) => row.batch_id)
})

const scroll = () => nextTick(() => scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' }))
type AgentModule = 'agent.analysis' | 'agent.plan' | 'agent.ops'
const MODULE_TEXT: Record<AgentModule, string> = { 'agent.analysis': '跨批次分析', 'agent.plan': '方案生成', 'agent.ops': '设备操作' }
const MODULE_KEY = 'vc-agent-module'
const SESSION_KEY = 'vc-agent-session'

function readModule(): AgentModule {
  const raw = sessionStorage.getItem(MODULE_KEY)
  return raw === 'agent.plan' || raw === 'agent.ops' || raw === 'agent.analysis' ? raw : 'agent.analysis'
}

const activeModule = ref<AgentModule>(readModule())
interface SessionItem { session_id: string; module: AgentModule; title: string; updated_at: number }
const history = ref<SessionItem[]>([])
const currentId = ref<string | null>(sessionStorage.getItem(SESSION_KEY))
watch(activeModule, (value) => sessionStorage.setItem(MODULE_KEY, value))
watch(currentId, (value) => {
  if (value) sessionStorage.setItem(SESSION_KEY, value)
  else sessionStorage.removeItem(SESSION_KEY)
})
const transcripts = ref<Record<string, Msg[]>>({})
const msgs = computed(() => (currentId.value ? transcripts.value[currentId.value] : []) || [])

function redraw() {
  viewKey.value += 1
  scroll()
}

async function loadHistory(module: AgentModule) {
  history.value = await api<SessionItem[]>(`/agent/sessions?module=${module}`)
}

async function openSession(id: string, force = false) {
  if (busy.value && !force) return
  currentId.value = id
  const body = await api<{ title: string; messages: Msg[] }>(`/agent/sessions/${id}`)
  transcripts.value[id] = (body.messages || []).map((item) => ({
    ...item,
    id: ++mid,
    blocks: item.blocks ?? [],
  }))
  const listed = history.value.find((item) => item.session_id === id)
  if (listed && body.title) listed.title = body.title
  redraw()
}

async function showSession(module: AgentModule, force = false) {
  if (busy.value && !force) return
  activeModule.value = module
  await loadHistory(module)
  const stillHere = history.value.some((item) => item.session_id === currentId.value)
  if (!stillHere) currentId.value = history.value[0]?.session_id ?? null
  if (!currentId.value) {
    redraw()
    return
  }
  await openSession(currentId.value, force)
}

async function send(q = input.value, module?: AgentModule) {
  q = q.trim()
  if (!q || busy.value) return
  const chosen = module ?? activeModule.value
  if (chosen !== activeModule.value) await showSession(chosen)
  input.value = ''
  busy.value = true
  scroll()
  let sid = currentId.value
  try {
    if (!sid || activeModule.value !== chosen) {
      const created = await api<{ session_id: string; title: string }>('/agent/sessions', {
        method: 'POST',
        body: JSON.stringify({ module: chosen }),
      })
      sid = created.session_id
      currentId.value = sid
      activeModule.value = chosen
      transcripts.value[sid] = []
    }
    if (!transcripts.value[sid]) transcripts.value[sid] = []
    transcripts.value[sid].push({ id: ++mid, role: 'user', text: q, blocks: [], time: Date.now() })
    const live: Msg = { id: ++mid, role: 'agent', text: '', blocks: [], module: chosen, time: Date.now(), live: true }
    transcripts.value[sid].push(live)
    scroll()
    await readReply(sid, q, live, chosen, { model: scope.value.model, batches: [...scope.value.batches] })
    await loadHistory(chosen)
  } catch (err) {
    const rows = sid ? transcripts.value[sid] : undefined
    const live = rows?.find((item) => item.live)
    if (live && !live.text && !live.blocks.length) rows?.splice(rows.indexOf(live), 1)
    else if (live) live.live = false
    app.toast({ kind: 'danger', title: 'Agent 没有完成', desc: err instanceof Error ? err.message : '请求失败' })
  } finally {
    busy.value = false
    scroll()
  }
}

function toolLabel(name: string) {
  return name.split('__').pop() || name
}

async function readReply(sid: string, text: string, live: Msg, module: AgentModule, scopeBody: { model: string; batches: string[] }) {
  const token = currentToken()
  if (!token) throw new Error('未登录')
  const res = await fetch(`/api/v1/agent/sessions/${sid}/messages/stream`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, model: scopeBody.model, batches: scopeBody.batches }),
  })
  if (!res.ok || !res.body) {
    let message = `请求失败 ${res.status}`
    try {
      const body = await res.json()
      message = body?.error?.message || message
    } catch { /* 保留状态码 */ }
    throw new Error(message)
  }
  const refresh = loadHistory(module).catch(() => undefined)
  const tools = new Map<string, Extract<Block, { type: 'tool' }>>()
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const chunk = await reader.read()
    if (chunk.done) break
    buffer += decoder.decode(chunk.value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''
    for (const part of parts) {
      const line = part.split('\n').find((item) => item.startsWith('data:'))
      if (!line) continue
      const payload = JSON.parse(line.slice(5)) as {
        type: string
        text?: string
        id?: string
        name?: string
        args?: string
        result?: string
        message?: string | Msg
        action?: Extract<Block, { type: 'action' }>
        table?: Extract<Block, { type: 'table' }>
        chart?: Extract<Block, { type: 'chart' }>
      }
      if (payload.type === 'text' && payload.text) live.text += payload.text
      if (payload.type === 'tool' && payload.id) {
        const block: Extract<Block, { type: 'tool' }> = { type: 'tool', name: payload.name || 'tool', args: payload.args || '', result: '' }
        tools.set(payload.id, block)
        live.blocks.push(block)
      }
      if (payload.type === 'tool_args' && payload.id) {
        const block = tools.get(payload.id)
        if (block) block.args = payload.args || ''
      }
      if (payload.type === 'tool_result' && payload.id) {
        const block = tools.get(payload.id)
        if (block) block.result = payload.result || ''
      }
      if (payload.type === 'action' && payload.action?.id && !live.blocks.some((item) => item.type === 'action' && item.id === payload.action?.id)) {
        live.blocks.push(payload.action)
      }
      const shown = payload.type === 'table' ? payload.table : payload.type === 'chart' ? payload.chart : undefined
      if (shown?.id && !live.blocks.some((item) => 'id' in item && item.id === shown.id)) live.blocks.push(shown)
      if (payload.type === 'done' && payload.message && typeof payload.message !== 'string') {
        live.text = payload.message.text || live.text
        live.blocks = payload.message.blocks || live.blocks
        live.tokens = payload.message.tokens
        live.module = payload.message.module || live.module
        live.time = payload.message.time || live.time
        live.live = false
      }
      if (payload.type === 'error') throw new Error(payload.message && typeof payload.message === 'string' ? payload.message : 'Agent 没有完成')
      scroll()
    }
  }
  live.live = false
  await refresh
}

async function pick(block: Extract<Block, { type: 'choices' }>, index: number) {
  const option = block.options[index]
  if (!currentId.value || !option || busy.value || acting.value || block.chosen != null) return
  acting.value = block.id
  try {
    const saved = await api<Extract<Block, { type: 'choices' }>>(`/agent/sessions/${currentId.value}/choices/${block.id}`, {
      method: 'POST',
      body: JSON.stringify({ index }),
    })
    block.chosen = saved.chosen
  } catch (err) {
    app.toast({ kind: 'danger', title: '没有发出这一句', desc: err instanceof Error ? err.message : '请求失败' })
    acting.value = ''
    return
  }
  acting.value = ''
  await send(option.text)
}

async function approve(b: Extract<Block, { type: 'action' }>) {
  if (!currentId.value || !b.id || acting.value) return
  const ok = await app.confirm({
    title: '执行集群操作',
    desc: b.desc,
    confirmText: '确认执行',
    danger: b.risk === 'high',
    typeToConfirm: b.risk === 'high' ? 'CONFIRM' : undefined,
    checklist: b.risk === 'high' ? ['已核对目标机台与参数', '知悉此操作会写入集群并记录到操作日志'] : undefined,
  })
  if (!ok) return
  await settle(b, 'approve')
}
async function reject(b: Extract<Block, { type: 'action' }>) {
  if (!currentId.value || !b.id || acting.value) return
  await settle(b, 'reject')
}
async function settle(b: Extract<Block, { type: 'action' }>, decision: 'approve' | 'reject') {
  acting.value = b.id
  try {
    const saved = await api<Extract<Block, { type: 'action' }>>(`/agent/sessions/${currentId.value}/actions/${b.id}`, {
      method: 'POST',
      body: JSON.stringify({ decision }),
    })
    Object.assign(b, saved)
    app.toast({ kind: decision === 'approve' ? 'ok' : 'info', title: decision === 'approve' ? '已执行' : '已拒绝该操作', desc: saved.result || b.desc })
  } catch (err) {
    const message = err instanceof Error ? err.message : '请求失败'
    if (decision === 'approve') b.result = message
    app.toast({ kind: 'danger', title: decision === 'approve' ? '没有执行' : '没有拒绝', desc: message })
  } finally {
    acting.value = ''
  }
}

function pendingBlocks(message: Msg) {
  return message.blocks.filter((block): block is Extract<Block, { type: 'action' }> => block.type === 'action' && block.status === 'pending')
}
function hasPending() {
  return msgs.value.some((message) => pendingBlocks(message).length > 0)
}
const sessionTokens = computed(() => msgs.value.reduce((a, m) => a + (m.tokens ? m.tokens[0] + m.tokens[1] : 0), 0))

function toggleBatch(id: string) {
  const s = scope.value.batches
  scope.value.batches = s.includes(id) ? s.filter((x) => x !== id) : [...s, id]
}
function newSession() {
  currentId.value = null
  redraw()
}

async function removeSession(id: string) {
  if (busy.value) return
  const item = history.value.find((row) => row.session_id === id)
  const ok = await app.confirm({
    title: '删除这场对话',
    desc: item?.title || '新对话',
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return
  try {
    await api(`/agent/sessions/${id}`, { method: 'DELETE' })
  } catch (err) {
    app.toast({ kind: 'danger', title: '对话没有删除', desc: err instanceof Error ? err.message : '请求失败' })
    return
  }
  history.value = history.value.filter((row) => row.session_id !== id)
  delete transcripts.value[id]
  if (currentId.value !== id) return
  currentId.value = history.value[0]?.session_id ?? null
  if (currentId.value) await openSession(currentId.value)
  else redraw()
}

onMounted(() => {
  loadScope().catch((err) => app.toast({ kind: 'danger', title: '分析范围没有加载', desc: err instanceof Error ? err.message : '请求失败' }))
  showSession(activeModule.value).catch((err) => app.toast({ kind: 'danger', title: '对话没有读到', desc: err instanceof Error ? err.message : '请求失败' }))
  if (route.query.q) { send(String(route.query.q)); router.replace({ query: {} }) }
})
</script>

<template>
  <div class="agent-page">
    <!-- 左：能力 -->
    <aside class="left">
      <button class="btn btn-primary" style="width: 100%" @click="newSession"><Plus :size="16" />新对话</button>
      <div v-if="history.length" class="history">
        <div v-for="item in history" :key="item.session_id" class="pr hist" :class="{ on: item.session_id === currentId }">
          <button type="button" class="hist-open" :disabled="busy" @click="openSession(item.session_id)">{{ item.title || '新对话' }}</button>
          <button type="button" class="hist-x" :disabled="busy" title="删除" @click="removeSession(item.session_id)"><X :size="12" /></button>
        </div>
      </div>
      <div v-for="c in CAPS" :key="c.key" class="cap" :class="{ active: activeModule === c.module }">
        <h4 @click="showSession(c.module as AgentModule)"><component :is="c.icon" :size="14" />{{ c.title }}<span class="code-label">{{ c.module }}</span></h4>
        <button v-for="p in c.prompts" :key="p" class="pr" :disabled="busy" @click="send(p, c.module as AgentModule)">
          <span>{{ p }}</span><ChevronRight :size="14" />
        </button>
      </div>
      <div class="safe">
        <ShieldCheck :size="16" />
        <p>Agent 通过 cluster MCP 查看和控制仿真测试机。写操作会先出现在右侧，点批准后才会执行，拒绝则不会执行。</p>
      </div>
    </aside>

    <!-- 中：对话 -->
    <section class="center">
      <div class="session-bar">
        <span class="tag primary">{{ MODULE_TEXT[activeModule] }}</span>
        <span class="mono fs-xs muted">{{ history.find((item) => item.session_id === currentId)?.title || '新对话' }}</span>
      </div>
      <div :key="viewKey" ref="scroller" class="msgs">
        <div v-for="m in msgs" :key="m.id" class="msg" :class="m.role">
          <div class="av"><User v-if="m.role === 'user'" :size="16" /><Bot v-else :size="16" /></div>
          <div class="bd">
            <div class="meta">
              <b>{{ m.role === 'user' ? '你' : 'Agent' }}</b>
              <span v-if="m.module" class="tag primary">{{ MODULE_TEXT[m.module] }}</span>
              <span class="num">{{ hms(m.time) }}</span>
              <span v-if="m.tokens" class="num grow" style="text-align: right">{{ m.tokens[0].toLocaleString() }} 入 / {{ m.tokens[1].toLocaleString() }} 出</span>
            </div>
            <template v-for="(b, i) in m.blocks" :key="i">
              <div v-if="b.type === 'tool'" class="tool">
                <Database v-if="b.name.startsWith('sql')" :size="13" /><SquareTerminal v-else :size="13" />
                <span class="mono" :title="b.name">{{ toolLabel(b.name) }}</span>
                <span v-if="b.args" class="mono muted ellipsis grow" :title="b.args">{{ b.args }}</span><span v-else class="grow" />
                <span v-if="b.result" class="mono t-ok">→ {{ b.result }}</span>
                <span v-else-if="m.live" class="mono muted">执行中</span>
              </div>
            </template>
            <template v-for="(b, i) in m.blocks" :key="'d' + i">
              <div v-if="b.type === 'table'" class="card">
                <div class="ch"><Database :size="14" />{{ b.title }}<span class="grow" /><span v-if="b.more" class="mono muted">还有 {{ b.more }} 行</span></div>
                <div class="sheet">
                  <table class="data">
                    <thead><tr><th v-for="column in b.columns" :key="column">{{ column }}</th></tr></thead>
                    <tbody>
                      <tr v-for="(row, rowIndex) in b.rows" :key="rowIndex"><td v-for="(cell, cellIndex) in row" :key="cellIndex" class="mono">{{ cell }}</td></tr>
                    </tbody>
                  </table>
                </div>
              </div>
              <div v-else-if="b.type === 'chart'" class="card">
                <div class="ch"><BarChart3 :size="14" />{{ b.title }}</div>
                <EChart :option="b.option" :height="220" />
              </div>
            </template>
            <div v-if="m.live && !m.text && !m.blocks.length" class="row fs-sm muted"><Loader2 :size="14" class="spin" />正在通过 MCP 操作测试机…</div>
            <p v-if="m.text" class="txt">{{ m.text }}</p>
            <template v-for="(b, i) in m.blocks" :key="'b' + i">
              <div v-if="b.type === 'choices'" class="card">
                <div class="ch">请选择下一步<span class="grow" /><span v-if="b.chosen != null" class="tag ok">已发送</span></div>
                <div class="choices">
                  <button v-for="(option, index) in b.options" :key="option.text" class="btn btn-sm" :class="{ 'btn-primary': b.chosen === index }" :disabled="b.chosen != null || m.live || busy || acting === b.id" @click="pick(b, index)">{{ option.label }}</button>
                </div>
              </div>
              <div v-else-if="b.type === 'plan'" class="card">
                <div class="ch"><FileCode2 :size="14" />方案草稿 <span class="mono muted">{{ b.plan_id }}</span><span class="grow" />
                  <button class="btn btn-sm" @click="router.push('/plans')">在测试方案中打开<ChevronRight :size="14" /></button>
                </div>
                <div class="kv">
                  <div v-for="f in b.fields" :key="f[0]"><span class="mono">{{ f[0] }}</span><b class="num">{{ f[1] }}</b></div>
                </div>
              </div>
              <div v-else-if="b.type === 'action'" class="card act" :class="b.status">
                <div class="ch">
                  <span v-if="b.status === 'pending'" class="hz hazard" />
                  <Wrench :size="14" /><span class="desc grow">{{ b.desc }}</span>
                  <span v-if="b.status === 'pending'" class="tag warn">待确认</span>
                  <span v-else-if="b.status === 'done'" class="tag ok">已执行</span>
                  <span v-else class="tag">已拒绝</span>
                </div>
                <pre class="api"><b>{{ b.name }}</b>
{{ JSON.stringify(b.arguments || {}, null, 2) }}</pre>
                <p v-if="b.result" class="fs-xs" style="padding: 0 10px 8px">{{ b.result }}</p>
                <div v-if="b.status === 'pending'" class="row" style="padding: 0 10px 10px; justify-content: flex-end">
                  <button class="btn btn-sm" :disabled="acting === b.id" @click="reject(b)"><X :size="14" />拒绝</button>
                  <button class="btn btn-sm btn-primary" :disabled="acting === b.id" @click="approve(b)"><Check :size="14" />批准并执行</button>
                </div>
              </div>
            </template>
            <div v-if="m.live && (m.text || m.blocks.length)" class="row fs-sm muted"><Loader2 :size="14" class="spin" />还在继续</div>
          </div>
        </div>
      </div>
      <p class="scope-hint">{{ scopeHint }}</p>
      <div class="composer">
        <textarea v-model="input" class="textarea" rows="2" placeholder="问数据、写方案、操作设备… Enter 发送，Shift+Enter 换行" @keydown.enter.exact.prevent="send()" />
        <button class="btn btn-primary btn-icon" :disabled="busy || !input.trim()" v-tip="'发送'" @click="send()"><ArrowUp :size="18" /></button>
      </div>
    </section>

    <!-- 右：上下文 -->
    <aside class="right">
      <Panel title="分析范围" code="SCOPE" :icon="Sparkles">
        <div class="field">
          <label>型号</label>
          <select v-model="scope.model" class="select">
            <option v-for="m in modelOptions" :key="m.model" :value="m.model">{{ m.model }}</option>
          </select>
        </div>
        <div class="field" style="margin-top: 10px">
          <label>批次（{{ scope.batches.length }}）</label>
          <label v-for="b in visibleBatches" :key="b.batch_id" class="bopt">
            <input type="checkbox" :checked="scope.batches.includes(b.batch_id)" @change="toggleBatch(b.batch_id)" />
            <span class="mono fs-xs grow ellipsis">{{ b.batch_id }}</span>
            <span class="num fs-xs muted">{{ yieldText(b) }}</span>
          </label>
          <p v-if="!visibleBatches.length" class="fs-xs muted">这个型号还没有批次统计</p>
        </div>
        <p class="fs-xs muted" style="margin-top: 8px">方案：{{ publishedPlans }} 个已发布 · 机台：{{ machineCount }} 台</p>
      </Panel>
      <Panel title="待确认操作" code="PENDING" :icon="ShieldCheck" :accent="hasPending() ? 'warn' : undefined" flush>
        <ul class="pend">
          <template v-for="message in msgs" :key="message.id">
            <li v-for="block in pendingBlocks(message)" :key="block.id">
              <span class="mono fs-xs"><b>{{ toolLabel(block.name) }}</b></span>
              <span class="fs-sm pend-desc">{{ block.desc }}</span>
              <div class="row" style="justify-content: flex-end">
                <button class="btn btn-sm btn-ghost" :disabled="acting === block.id" @click="reject(block)">拒绝</button>
                <button class="btn btn-sm btn-primary" :disabled="acting === block.id" @click="approve(block)">批准并执行</button>
              </div>
            </li>
          </template>
          <li v-if="!hasPending()" class="none">没有待确认的操作</li>
        </ul>
      </Panel>
      <div class="usage">
        <span class="code-label">本次对话</span>
        <b class="num">{{ sessionTokens.toLocaleString() }}</b><span class="fs-xs muted">tokens</span>
        <button class="btn btn-ghost btn-sm" @click="router.push('/tokens')">统计<ChevronRight :size="14" /></button>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.agent-page { display: grid; grid-template-columns: 260px minmax(0, 1fr) 300px; height: 100%; min-height: 0; }
@media (max-width: 1360px) { .agent-page { grid-template-columns: 230px minmax(0, 1fr) 260px; } }
.left, .right { padding: 14px; display: flex; flex-direction: column; gap: 12px; overflow: auto; background: var(--c-surface); }
.left { border-right: var(--bw) solid var(--c-border); }
.right { border-left: var(--bw) solid var(--c-border); background: var(--c-bg); }
.cap h4 { display: flex; align-items: center; gap: 6px; font-size: var(--fs-sm); margin-bottom: 6px; cursor: pointer; }
.cap.active h4 { color: var(--c-primary); }
.session-bar { display: flex; align-items: center; gap: 8px; padding: 8px 20px; border-bottom: var(--bw) solid var(--c-border); background: var(--c-surface); }
.cap h4 .code-label { margin-left: auto; font-size: 9px; }
.pr { width: 100%; display: flex; align-items: center; gap: 4px; text-align: left; padding: 6px 8px; margin-bottom: 4px; border: var(--bw) solid var(--c-border); background: var(--c-surface-2); color: var(--c-text-2); font-size: var(--fs-xs); cursor: pointer; line-height: 1.4; }
.pr span { flex: 1; }
.pr:hover:not(:disabled) { border-color: var(--c-primary); color: var(--c-text); }
.pr.on { border-color: var(--c-primary); color: var(--c-text); background: var(--c-primary-weak); }
.history { display: flex; flex-direction: column; max-height: 160px; overflow: auto; }
.hist { padding: 0; }
.hist-open { flex: 1; min-width: 0; text-align: left; padding: 6px 8px; background: transparent; border: 0; color: inherit; font: inherit; cursor: pointer; }
.hist-x { flex: none; width: 22px; border: 0; background: transparent; color: var(--c-text-3); cursor: pointer; }
.hist-x:hover:not(:disabled) { color: var(--c-danger, #b42318); }
.safe { margin-top: auto; display: flex; gap: 8px; padding: 10px; background: var(--c-warn-weak); border-left: 3px solid var(--c-warn); font-size: var(--fs-xs); color: var(--c-text-2); line-height: 1.6; }
.safe svg { flex: none; color: var(--c-warn); }

.center { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
.msgs { flex: 1; overflow: auto; padding: 16px 20px; }
.msg { display: flex; gap: 10px; width: 100%; max-width: 920px; min-width: 0; align-items: flex-start; margin-bottom: 16px; }
.msg:last-child { margin-bottom: 0; }
.msg.user { width: fit-content; max-width: min(640px, 100%); margin-left: auto; flex-direction: row-reverse; }
.av { width: 30px; height: 30px; flex: none; display: grid; place-items: center; background: var(--c-accent); color: #fff; }
.msg.user .av { background: var(--c-surface-3); color: var(--c-text-2); }
.bd { min-width: 0; flex: 1 1 auto; display: flex; flex-direction: column; gap: 8px; }
.bd > * { flex-shrink: 0; }
.msg.user .bd { align-items: flex-end; }
.meta { display: flex; align-items: center; gap: 8px; font-size: var(--fs-xs); color: var(--c-text-3); }
.msg.user .meta { flex-direction: row-reverse; }
.txt { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.75; padding: 10px 12px; background: var(--c-surface); border: var(--bw) solid var(--c-border); max-width: 100%; }
.msg.user .txt { background: var(--c-primary-weak); border-color: color-mix(in srgb, var(--c-primary) 30%, transparent); }
.tool { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 8px; padding: 4px 10px; font-size: var(--fs-xs); background: var(--c-surface-2); border-left: 2px solid var(--c-text-3); min-width: 0; max-width: 100%; overflow: hidden; }
.tool svg { flex: none; color: var(--c-text-3); margin-top: 2px; }
.tool > .mono:first-of-type { white-space: nowrap; }
.tool .t-ok { flex: 1 1 100%; min-width: 0; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 4.8em; overflow: auto; }
.card { border: var(--bw) solid var(--c-border); background: var(--c-surface); max-width: 100%; min-width: 0; }
.ch { display: flex; align-items: flex-start; gap: 6px; padding: 8px 10px; font-weight: 600; font-size: var(--fs-sm); border-bottom: var(--bw) solid var(--c-border); position: relative; min-width: 0; }
.ch .desc { min-width: 0; overflow-wrap: anywhere; line-height: 1.45; }
.sheet { overflow: auto; max-height: 280px; }
.data { width: 100%; border-collapse: collapse; font-size: var(--fs-xs); }
.data th, .data td { padding: 4px 8px; border-bottom: var(--bw) solid var(--c-border); text-align: left; white-space: nowrap; }
.choices { display: flex; flex-wrap: wrap; gap: 8px; padding: 10px; }
.kv { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: var(--c-border); }
.kv div { display: flex; flex-direction: column; padding: 6px 10px; background: var(--c-surface); font-size: var(--fs-xs); color: var(--c-text-3); }
.kv b { color: var(--c-text); font-size: var(--fs-sm); }
.act.pending { border-color: var(--c-warn); }
.act.rejected { opacity: 0.6; }
.hz { position: absolute; left: 0; top: 0; bottom: 0; width: 4px; }
.api { margin: 10px; padding: 8px 10px; background: var(--c-surface-2); border: var(--bw) solid var(--c-border); font-family: var(--font-mono); font-size: 12px; white-space: pre-wrap; }
.api b { color: var(--c-primary); }
.scope-hint { margin: 0; padding: 8px 20px 0; border-top: var(--bw) solid var(--c-border); font-size: var(--fs-xs); color: var(--c-text-3); background: var(--c-surface); }
.composer { display: flex; gap: 8px; align-items: flex-end; padding: 8px 20px 16px; border-top: 0; background: var(--c-surface); }
.composer .textarea { flex: 1; }
.spin {
  display: inline-block;
  flex: none;
  transform-origin: center;
  animation: spin 0.9s linear infinite;
  animation-duration: 0.9s !important;
  animation-iteration-count: infinite !important;
}
@keyframes spin { to { transform: rotate(360deg); } }

.bopt { display: flex; align-items: center; gap: 6px; padding: 4px 0; cursor: pointer; font-weight: 400 !important; }
.bopt input { accent-color: var(--c-primary); }
.pend { list-style: none; margin: 0; padding: 0; }
.pend li { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; border-bottom: var(--bw) solid var(--c-border); min-width: 0; }
.pend-desc { overflow-wrap: anywhere; line-height: 1.45; }
.pend .none { color: var(--c-text-3); font-size: var(--fs-sm); text-align: center; padding: 20px; }
.usage { display: flex; align-items: baseline; gap: 6px; padding: 10px 12px; background: var(--c-surface); border: var(--bw) solid var(--c-border); }
.usage b { font-size: var(--fs-lg); margin-left: auto; }
</style>
