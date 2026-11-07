<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowUp, BarChart3, Bot, Check, ChevronRight, Database, Download, Eye, FileCode2, Loader2, Plus, ShieldCheck, Sparkles, User, Wrench, X,
} from 'lucide-vue-next'
import Panel from '@/components/Panel.vue'
import EChart from '@/components/EChart.vue'
import { api, apiDownload, currentToken, saveBlob } from '@/api/http'
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
  | { type: 'records'; id: string; items: RecordLink[]; more: number }
  | { type: 'plan'; plan_id: string; name: string; fields: [string, string][] }
  | { type: 'action'; id: string; name: string; desc: string; arguments: Record<string, any>; status: 'pending' | 'done' | 'rejected' | 'expired'; result: string; risk: 'low' | 'medium' | 'high'; effects?: string[] }
interface RecordLink { run_id: string; serial_number: string; batch_id: string; ended_at: number; label: string }
interface RecordView { columns: string[]; rows: string[][]; chart: Record<string, any> | null; note: string }
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
const asking = ref('')
const viewing = ref('')
const recordViews = ref<Record<string, RecordView>>({})
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
  const signal = AbortSignal.timeout(20_000)
  const [modelRes, statRes, planRes, machineRes] = await Promise.allSettled([
    api<{ model: string }[]>('/models', { signal }),
    api<{ items: BatchStat[] }>('/batch-stats?limit=50', { signal }),
    api<{ meta?: { draft?: boolean } }[]>('/plans', { signal }),
    api<{ machine_id: string }[]>('/machines', { signal }),
  ])
  if (modelRes.status === 'fulfilled') modelOptions.value = modelRes.value
  if (statRes.status === 'fulfilled') batchRows.value = statRes.value.items || []
  if (planRes.status === 'fulfilled') publishedPlans.value = planRes.value.filter((row) => row.meta && !row.meta.draft).length
  if (machineRes.status === 'fulfilled') machineCount.value = machineRes.value.length
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
const promptsOpen = ref(false)

function pickPrompt(text: string, module: AgentModule) {
  promptsOpen.value = false
  void send(text, module)
}
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

function shownText(message: Msg) {
  if (message.role !== 'agent') return message.text
  let text = message.text.replace(/(?:^|\n)\s*查询过程\s*[：:]?[\s\S]*$/, '')
  const actions = message.blocks.filter((block): block is Extract<Block, { type: 'action' }> => block.type === 'action')
  for (const action of actions) {
    if (action.desc) text = text.split(action.desc).join('')
    for (const effect of action.effects || []) text = text.split(effect).join('')
  }
  text = text
    .replace(/需要你在页面上批准[：:]?/g, '')
    .replace(/请到右侧[「"']?待确认操作[」"']?点批准或拒绝[。．]?/g, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/[：:]\s*(?=[。．]|$)/g, '')
    .replace(/([。．])\1+/g, '$1')
    .trim()
  if (!actions.length) return text
  if (!text) return '请在卡片上批准或拒绝。批准后我会继续下一步。'
  if (/批准|拒绝|确认/.test(text)) return text
  return `${text.replace(/[。．]?$/, '。')}请在卡片上批准或拒绝。`
}

function hasAction(message: Msg) {
  return message.blocks.some((block) => block.type === 'action')
}

function actionTitle(name: string) {
  if (name.includes('plan')) return '方案操作'
  if (name.includes('board')) return '板子操作'
  if (name.includes('alarm')) return '告警操作'
  if (name.includes('report')) return '报告操作'
  if (name.includes('quality')) return '质量操作'
  return '设备操作'
}

const RISK_TEXT = { low: '低风险', medium: '中风险', high: '高风险' } as const

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

function toolArgs(raw: string): Record<string, unknown> {
  if (!raw.trim()) return {}
  try {
    const value = JSON.parse(raw)
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
  } catch {
    return {}
  }
}

function listed(value: unknown) {
  if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean).join('、')
  if (value === undefined || value === null || value === '') return ''
  return String(value)
}

function toolStory(block: Extract<Block, { type: 'tool' }>) {
  const args = toolArgs(block.args)
  const machines = listed(args.machine_ids) || listed(args.machine_id)
  const slot = args.slot_index === undefined || args.slot_index === null || args.slot_index === '' ? '' : `${args.slot_index} 号槽`
  const place = [machines, slot].filter(Boolean).join(' ')
  const serial = listed(args.serial_number)
  const plan = listed(args.plan_id)
  const version = args.version ?? args.plan_version
  const planText = [plan, version ? `v${version}` : ''].filter(Boolean).join(' ')
  const count = listed(args.count)
  const model = listed(args.model)
  const stories: Record<string, string> = {
    overview: '查看整线现在的情况',
    machines: '查看机台列表',
    machine: place ? `查看 ${place} 现在的状态` : '查看一台机现在的状态',
    slot: place ? `查看 ${place} 测到哪了` : '查看一个槽测到哪了',
    production: '查看当前连续生产',
    search: args.q ? `按「${args.q}」查找` : '按关键字查找',
    sim_catalog: '查看可以切换的仿真场景和故障',
    calibration: machines ? `查看 ${machines} 的通道补偿` : '查看通道补偿',
    calibration_history: machines ? `查看 ${machines} 的补偿修改记录` : '查看补偿修改记录',
    plan_history: machines ? `查看 ${machines} 用过的方案` : '查看机台用过的方案',
    audit: '查看操作记录',
    power_on: machines ? `给 ${machines} 上电` : '给机台上电',
    power_off: machines ? `给 ${machines} 关机` : '给机台关机',
    reset: machines ? `复位 ${machines}` : '复位全部在线机台',
    maintenance: machines ? (args.on === false ? `让 ${machines} 退出维修` : `让 ${machines} 进入维修`) : '切换维修模式',
    slot_load: `把 ${serial || '板'} 装到 ${place || '槽上'}，先不开测`,
    slot_start: place ? `对 ${place} 开测` : '对已装板的槽开测',
    slot_test: `把 ${serial || '板'} 装到 ${place || '槽上'}并开测`,
    slot_abort: place ? `中止 ${place}` : '中止槽位测试',
    slot_clear_error: place ? `清除 ${place} 的错误` : '清除槽位错误',
    dispatch: `把方案${planText ? ` ${planText}` : ''}装到 ${machines || '机台'}，先不开测`,
    production_precheck: '检查连续生产能不能开始',
    production_start: machines ? `在 ${machines} 上开始连续生产` : '开始连续生产',
    production_stop: args.batch_id ? `停止批次 ${args.batch_id} 的连续生产` : '停止当前连续生产',
    sim_speed: machines ? `把 ${machines} 的仿真倍率改为 ${listed(args.speed) || '新倍率'}` : '修改仿真倍率',
    sim_scenario: `给 ${machines || '机台'} 切换仿真场景${args.name ? `「${args.name}」` : ''}`,
    sim_fault: `给 ${machines || '机台'} 注入故障${args.kind ? ` ${args.kind}` : ''}`,
    suggest_compensation: machines ? `为 ${machines} 提交补偿建议` : '提交补偿建议',
    apply_compensation: machines ? `把补偿写入 ${machines}` : '写入通道补偿',
    plans: '查看已有方案',
    plan: plan ? `查看方案 ${planText}` : '查看方案内容',
    from_text: '把这段测试要求整理成方案草稿',
    validate: '校验方案参数',
    save_draft: plan ? `保存方案草稿 ${plan}` : '保存方案草稿',
    delete_draft: plan ? `删除草稿 ${plan}` : '删除方案草稿',
    publish: plan ? `发布方案 ${planText}` : '发布方案',
    boards: '查看待测板',
    board: serial ? `查看板 ${serial}` : '查看一片板',
    batches: model ? `查看 ${model} 的批次` : '查看批次',
    batch: args.batch_id ? `查看批次 ${args.batch_id}` : '查看一个批次',
    models: '查看型号',
    defect_kinds: '查看缺陷种类',
    create_batch: count || model ? `生成${count ? ` ${count} 片` : ''}${model ? ` ${model}` : ''}待测板` : '生成一批待测板',
    requeue: serial ? `把标准样品 ${serial} 放回待测` : '把标准样品放回待测',
    runs: '查看测试记录',
    run: args.run_id ? `查看记录 ${args.run_id}` : '查看一条测试记录',
    ground_truth: '核对这条记录的仿真真值',
    compare: '对比这几个批次的良率',
    trend: '查看产量和良率趋势',
    export: '导出生产结果表',
    alarms: '查看告警',
    attribution: '查看这条告警的原因',
    ack: '确认告警',
    unack: '取消确认告警',
    ack_all: '确认全部未处理告警',
    rerun_attribution: '重新分析这条告警的原因',
    report_summary: '生成批次报告结论',
    report_figure: '按描述生成图表',
    report_export: '导出 PDF 报告',
  }
  const action = String(args.action || '')
  return stories[action] || '正在查询'
}

function toolBlocks(message: Msg) {
  return message.blocks.flatMap((block, index) => (block.type === 'tool' ? [{ block, index }] : []))
}

function stepTitle(message: Msg) {
  const rows = toolBlocks(message)
  const done = rows.filter((item) => item.block.result).length
  if (message.live && done < rows.length) return done ? `正在进行，已完成 ${done} 个步骤` : '正在进行'
  return `已完成 ${rows.length} 个步骤`
}

const openTools = ref<Record<string, boolean>>({})
const closedSteps = ref<Record<number, boolean>>({})

function stepsShown(messageId: number) {
  return !closedSteps.value[messageId]
}

function toggleSteps(messageId: number) {
  closedSteps.value = { ...closedSteps.value, [messageId]: !closedSteps.value[messageId] }
}

function toolKey(messageId: number, index: number) {
  return `${messageId}:${index}`
}

function toggleTool(messageId: number, index: number) {
  const key = toolKey(messageId, index)
  openTools.value = { ...openTools.value, [key]: !openTools.value[key] }
}

function prettyJson(raw: string) {
  const text = raw.trim()
  if (!text) return ''
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text
  }
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
        records?: Extract<Block, { type: 'records' }>
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
      const shown = payload.type === 'table' ? payload.table : payload.type === 'chart' ? payload.chart : payload.type === 'records' ? payload.records : undefined
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
  if (!currentId.value || !b.id || acting.value || isExpired(b)) return
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
  if (!currentId.value || !b.id || acting.value || isExpired(b)) return
  await settle(b, 'reject')
}
async function settle(b: Extract<Block, { type: 'action' }>, decision: 'approve' | 'reject') {
  acting.value = b.id
  try {
    // 批准会串 MCP→后端→集群；集群偶发超时可达数十秒。给明确上限，避免按钮一直转圈像卡死。
    const saved = await api<Extract<Block, { type: 'action' }>>(`/agent/sessions/${currentId.value}/actions/${b.id}`, {
      method: 'POST',
      body: JSON.stringify({ decision }),
      signal: AbortSignal.timeout(90_000),
    })
    Object.assign(b, saved)
    app.toast({ kind: decision === 'approve' ? 'ok' : 'info', title: decision === 'approve' ? '已执行' : '已拒绝该操作', desc: saved.result || b.desc })
  } catch (err) {
    const timedOut = err instanceof DOMException && err.name === 'TimeoutError'
    const message = timedOut ? '执行超时，集群可能正忙，请稍后重试' : err instanceof Error ? err.message : '请求失败'
    if (decision === 'approve') b.result = message
    if (approvalExpired(message)) b.status = 'expired'
    app.toast({ kind: 'danger', title: approvalExpired(message) ? '批准已失效' : decision === 'approve' ? '没有执行' : '没有拒绝', desc: message })
  } finally {
    acting.value = ''
  }
}

function approvalExpired(text: string) {
  return text.includes('已经过期或已经执行过')
}
function recordKey(blockId: string, item: RecordLink) {
  return `${blockId}:${item.run_id || item.batch_id}`
}

function jumpRecord(item: RecordLink) {
  const query: Record<string, string> = { tab: 'runs' }
  if (item.run_id) query.r = item.run_id
  if (item.serial_number) query.q = item.serial_number
  if (item.batch_id) query.batch = item.batch_id
  router.push({ path: '/testing', query })
}

async function viewRecord(blockId: string, item: RecordLink) {
  const key = recordKey(blockId, item)
  if (viewing.value === key) {
    viewing.value = ''
    return
  }
  viewing.value = key
  if (recordViews.value[key]) return
  try {
    if (item.run_id) {
      const run = await api<Record<string, any>>(`/runs/${encodeURIComponent(item.run_id)}`)
      const samples = await api<{ points?: { t_s: number; T0: number; T1: number; Ta: number; power_w?: number }[]; duration_s?: number }>(`/runs/${encodeURIComponent(item.run_id)}/samples`)
      const points = samples.points || []
      recordViews.value[key] = {
        note: `${run.serial_number || item.run_id} · ${run.passed === true ? 'pass' : run.passed === false ? 'fail' : run.status || ''} · 采样 ${points.length} 点${samples.duration_s ? ` · 方案时长 ${samples.duration_s}s` : ''}`,
        columns: ['序列号', '批次', '机台', '判定', '不合格项', '热阻', 'T0-T1'],
        rows: [[
          String(run.serial_number || '—'),
          String(run.batch_id || '—'),
          `${run.machine_id || '—'}#${run.slot_index ?? '—'}`,
          run.passed === true ? 'pass' : run.passed === false ? 'fail' : String(run.status || '—'),
          (run.fail_items || []).join(';') || '—',
          run.rc == null ? '—' : String(run.rc),
          run.dt01 == null ? '—' : String(run.dt01),
        ]],
        chart: points.length ? {
          grid: { left: 40, right: 12, top: 28, bottom: 24 },
          legend: { data: ['T0', 'T1', 'Ta'] },
          xAxis: { type: 'category', data: points.map((point) => `${point.t_s.toFixed(1)}s`) },
          yAxis: { type: 'value', name: '℃', scale: true },
          series: [
            { name: 'T0', type: 'line', data: points.map((point) => point.T0), showSymbol: false },
            { name: 'T1', type: 'line', data: points.map((point) => point.T1), showSymbol: false },
            { name: 'Ta', type: 'line', data: points.map((point) => point.Ta), showSymbol: false },
          ],
        } : null,
      }
    } else if (item.batch_id) {
      const page = await api<{ items: Record<string, any>[] }>(`/runs?batch_id=${encodeURIComponent(item.batch_id)}&limit=50`)
      recordViews.value[key] = {
        note: `${item.batch_id} · ${page.items.length} 片`,
        columns: ['序列号', '机台', '判定', '热阻'],
        rows: page.items.map((run) => [
          String(run.serial_number || run.run_id),
          `${run.machine_id}#${run.slot_index}`,
          run.passed === true ? 'pass' : run.passed === false ? 'fail' : String(run.status || '—'),
          run.rc == null ? '—' : String(run.rc),
        ]),
        chart: null,
      }
    }
  } catch (err) {
    viewing.value = ''
    app.toast({ kind: 'danger', title: '没有打开测试数据', desc: err instanceof Error ? err.message : '没有打开测试数据' })
  }
}

async function exportRecord(item: RecordLink, kind: 'raw' | 'batch') {
  asking.value = ''
  const path = kind === 'raw'
    ? (item.run_id ? `/export/raw?run_id=${encodeURIComponent(item.run_id)}` : `/export/raw?batch_id=${encodeURIComponent(item.batch_id)}`)
    : `/export/production.csv?group=batch&batch_id=${encodeURIComponent(item.batch_id)}`
  if (kind === 'batch' && !item.batch_id) {
    app.toast({ kind: 'danger', title: '这片记录没有批次' })
    return
  }
  if (kind === 'raw' && !item.run_id && !item.batch_id) return
  try {
    const file = await apiDownload(path)
    saveBlob(file.blob, file.filename)
    app.toast({ kind: 'ok', title: kind === 'raw' ? '已导出过程数据' : '已导出本批结果', desc: file.filename })
  } catch (err) {
    app.toast({ kind: 'danger', title: '导出失败', desc: err instanceof Error ? err.message : '导出失败' })
  }
}

function isExpired(block: Extract<Block, { type: 'action' }>) {
  return block.status === 'expired' || (block.status === 'pending' && approvalExpired(block.result || ''))
}
function pendingBlocks(message: Msg) {
  return message.blocks.filter((block): block is Extract<Block, { type: 'action' }> => block.type === 'action' && block.status === 'pending' && !isExpired(block))
}
function reviewBlocks(message: Msg) {
  return message.blocks.filter((block): block is Extract<Block, { type: 'action' }> => block.type === 'action' && (block.status === 'pending' || block.status === 'expired' || isExpired(block)))
}
function hasPending() {
  return msgs.value.some((message) => pendingBlocks(message).length > 0)
}
function hasReview() {
  return msgs.value.some((message) => reviewBlocks(message).length > 0)
}
const located = ref('')
function locateAction(id: string) {
  const node = scroller.value?.querySelector(`[data-action-id="${CSS.escape(id)}"]`)
  if (!(node instanceof HTMLElement)) return
  node.scrollIntoView({ behavior: 'smooth', block: 'center' })
  located.value = id
  window.setTimeout(() => {
    if (located.value === id) located.value = ''
  }, 1600)
}
const sessionTokenIn = computed(() => msgs.value.reduce((a, m) => a + (m.tokens?.[0] || 0), 0))
const sessionTokenOut = computed(() => msgs.value.reduce((a, m) => a + (m.tokens?.[1] || 0), 0))
const sessionTokens = computed(() => sessionTokenIn.value + sessionTokenOut.value)

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
      <div class="history">
        <p v-if="!history.length" class="fs-xs muted">还没有对话</p>
        <div v-for="item in history" :key="item.session_id" class="pr hist" :class="{ on: item.session_id === currentId }">
          <button type="button" class="hist-open" :disabled="busy" @click="openSession(item.session_id)">{{ item.title || '新对话' }}</button>
          <button type="button" class="hist-x" :disabled="busy" title="删除" @click="removeSession(item.session_id)"><X :size="12" /></button>
        </div>
      </div>
      <div class="safe">
        <ShieldCheck :size="16" />
        <p>Agent 通过 cluster MCP 查看和控制仿真测试机。写操作会列在右侧，点一下可定位到对话里的卡片，在卡片上批准后才会执行。</p>
      </div>
    </aside>

    <!-- 中：对话 -->
    <section class="center">
      <div class="prompts">
        <button type="button" class="prompts-h" @click="promptsOpen = !promptsOpen">
          <ChevronRight :size="14" :class="{ 'turn-down': promptsOpen }" />
          <span>{{ promptsOpen ? '收起提示' : '展开提示' }}</span>
          <span v-if="!promptsOpen" class="prompts-hint">跨批次分析、测试方案、设备操作</span>
        </button>
        <div v-if="promptsOpen" class="prompts-body">
          <div v-for="c in CAPS" :key="c.key" class="cap" :class="{ active: activeModule === c.module }">
            <h4 @click="showSession(c.module as AgentModule)"><component :is="c.icon" :size="14" />{{ c.title }}</h4>
            <div class="chips">
              <button v-for="p in c.prompts" :key="p" class="pr" :disabled="busy" @click="pickPrompt(p, c.module as AgentModule)">
                <span>{{ p }}</span><ChevronRight :size="14" />
              </button>
            </div>
          </div>
        </div>
      </div>
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
            <div v-if="toolBlocks(m).length" class="steps">
              <button type="button" class="steps-h" @click="toggleSteps(m.id)">
                <ChevronRight :size="14" :class="{ 'turn-down': stepsShown(m.id) }" />{{ stepTitle(m) }}
              </button>
              <ul v-if="stepsShown(m.id)">
                <li v-for="item in toolBlocks(m)" :key="item.index">
                  <span>{{ toolStory(item.block) }}</span>
                  <span v-if="!item.block.result && m.live" class="muted">进行中</span>
                  <button v-if="item.block.args || item.block.result" class="btn btn-ghost btn-sm" type="button" @click="toggleTool(m.id, item.index)">
                    {{ openTools[toolKey(m.id, item.index)] ? '收起' : '查看返回' }}
                  </button>
                  <pre v-if="openTools[toolKey(m.id, item.index)]" class="tool-json">{{ [prettyJson(item.block.args), prettyJson(item.block.result)].filter(Boolean).join('\n\n') }}</pre>
                </li>
              </ul>
            </div>
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
              <div v-else-if="b.type === 'records'" class="card">
                <div class="ch"><Database :size="14" />测试数据<span class="grow" /><span v-if="b.more" class="mono muted">还有 {{ b.more }} 片，用跳转去记录里选</span></div>
                <div v-for="item in b.items" :key="item.run_id || item.batch_id" class="rec">
                  <span class="mono grow">{{ item.label }}</span>
                  <button class="btn btn-sm" @click="viewRecord(b.id, item)"><Eye :size="14" />查看</button>
                  <button class="btn btn-sm" @click="jumpRecord(item)"><ChevronRight :size="14" />跳转</button>
                  <button class="btn btn-sm" @click="asking = asking === recordKey(b.id, item) ? '' : recordKey(b.id, item)"><Download :size="14" />导出</button>
                  <div v-if="asking === recordKey(b.id, item)" class="ask">
                    <span class="fs-xs muted">{{ item.run_id ? '过程数据是这一片的采样。本批数据是这一批每片一行的结果。' : '过程数据按片分成多个文件。本批数据是这一批每片一行的结果。' }}</span>
                    <button class="btn btn-sm btn-primary" @click="exportRecord(item, 'raw')">过程数据</button>
                    <button class="btn btn-sm" :disabled="!item.batch_id" @click="exportRecord(item, 'batch')">本批数据</button>
                  </div>
                  <div v-if="viewing === recordKey(b.id, item) && recordViews[recordKey(b.id, item)]" class="seen">
                    <p class="fs-xs muted">{{ recordViews[recordKey(b.id, item)].note }}</p>
                    <div class="sheet">
                      <table class="data">
                        <thead><tr><th v-for="column in recordViews[recordKey(b.id, item)].columns" :key="column">{{ column }}</th></tr></thead>
                        <tbody>
                          <tr v-for="(row, rowIndex) in recordViews[recordKey(b.id, item)].rows" :key="rowIndex"><td v-for="(cell, cellIndex) in row" :key="cellIndex" class="mono">{{ cell }}</td></tr>
                        </tbody>
                      </table>
                    </div>
                    <EChart v-if="recordViews[recordKey(b.id, item)].chart" :option="recordViews[recordKey(b.id, item)].chart" :height="200" />
                  </div>
                </div>
              </div>
            </template>
            <div v-if="m.live && !m.text && !m.blocks.length" class="row fs-sm muted"><Loader2 :size="14" class="spin" />正在通过 MCP 操作测试机…</div>
            <p v-if="shownText(m) && !hasAction(m)" class="txt">{{ shownText(m) }}</p>
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
              <div v-else-if="b.type === 'action'" class="card act" :data-action-id="b.id" :class="[b.status, { expired: isExpired(b), located: located === b.id }]">
                <div class="ch">
                  <span v-if="b.status === 'pending' && !isExpired(b)" class="hz hazard" />
                  <Wrench :size="14" /><span>{{ actionTitle(b.name) }}</span>
                  <span class="tag">{{ RISK_TEXT[b.risk] || '中风险' }}</span>
                  <span class="grow" />
                  <span v-if="isExpired(b)" class="tag">失效</span>
                  <span v-else-if="b.status === 'pending'" class="tag warn">待确认</span>
                  <span v-else-if="b.status === 'done'" class="tag ok">已执行</span>
                  <span v-else class="tag">已拒绝</span>
                </div>
                <p class="act-sentence">{{ b.desc }}</p>
                <ul v-if="b.effects?.length" class="act-effects">
                  <li v-for="effect in b.effects" :key="effect">{{ effect }}</li>
                </ul>
                <p v-if="b.result" class="fs-xs act-result">{{ b.result }}</p>
                <div v-if="b.status === 'pending' || isExpired(b)" class="row act-actions">
                  <button class="btn btn-sm" :disabled="isExpired(b) || acting === b.id" @click="reject(b)"><X :size="14" />拒绝</button>
                  <button class="btn btn-sm btn-primary" :disabled="isExpired(b) || acting === b.id" @click="approve(b)"><Check :size="14" />批准并执行</button>
                </div>
              </div>
            </template>
            <p v-if="shownText(m) && hasAction(m)" class="txt">{{ shownText(m) }}</p>
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
            <li v-for="block in reviewBlocks(message)" :key="block.id">
              <button type="button" class="pend-jump" :class="{ expired: isExpired(block) }" @click="locateAction(block.id)">
                <span class="fs-xs"><span v-if="isExpired(block)" class="tag">失效</span><span v-else class="tag warn">待确认</span></span>
                <span class="fs-sm pend-desc">{{ block.desc }}</span>
              </button>
            </li>
          </template>
          <li v-if="!hasReview()" class="none">没有待确认的操作</li>
        </ul>
      </Panel>
      <div class="usage">
        <span class="code-label">本次对话</span>
        <b class="num">{{ sessionTokens.toLocaleString() }}</b>
        <span class="fs-xs muted">tokens</span>
        <span v-if="sessionTokens" class="fs-xs muted num">{{ sessionTokenIn.toLocaleString() }} 入 / {{ sessionTokenOut.toLocaleString() }} 出</span>
        <button class="btn btn-ghost btn-sm" @click="router.push('/tokens')">统计<ChevronRight :size="14" /></button>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.agent-page { display: grid; grid-template-columns: 260px minmax(0, 1fr) 300px; height: 100%; min-height: 0; }
@media (max-width: 1360px) { .agent-page { grid-template-columns: 230px minmax(0, 1fr) 260px; } }
.left, .right { padding: 14px; display: flex; flex-direction: column; gap: 12px; min-height: 0; background: var(--c-surface); }
.left { border-right: var(--bw) solid var(--c-border); overflow: hidden; }
.right { border-left: var(--bw) solid var(--c-border); background: var(--c-bg); overflow: auto; }
.prompts { display: flex; flex-direction: column; border-bottom: var(--bw) solid var(--c-border); background: var(--c-surface); }
.prompts-h { display: flex; align-items: center; gap: 6px; width: 100%; padding: 8px 16px; border: 0; background: transparent; color: var(--c-text-2); font-size: var(--fs-sm); cursor: pointer; text-align: left; }
.prompts-h:hover { color: var(--c-text); }
.prompts-hint { color: var(--c-text-3); font-size: var(--fs-xs); font-weight: 400; }
.prompts-body { display: flex; flex-direction: column; gap: 8px; padding: 0 16px 10px; background: var(--c-bg); }
.prompts .cap { min-width: 0; }
.prompts .chips { display: flex; flex-wrap: wrap; gap: 6px; }
.prompts .pr { width: auto; max-width: 100%; margin: 0; }
.cap h4 { display: flex; align-items: center; gap: 6px; font-size: var(--fs-sm); margin-bottom: 6px; cursor: pointer; }
.cap.active h4 { color: var(--c-primary); }
.session-bar { display: flex; align-items: center; gap: 8px; padding: 8px 20px; border-bottom: var(--bw) solid var(--c-border); background: var(--c-surface); }
.pr { width: 100%; display: flex; align-items: center; gap: 4px; text-align: left; padding: 6px 8px; margin-bottom: 4px; border: var(--bw) solid var(--c-border); background: var(--c-surface-2); color: var(--c-text-2); font-size: var(--fs-xs); cursor: pointer; line-height: 1.4; }
.pr span { flex: 1; }
.pr:hover:not(:disabled) { border-color: var(--c-primary); color: var(--c-text); }
.pr.on { border-color: var(--c-primary); color: var(--c-text); background: var(--c-primary-weak); }
.history { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow: auto; }
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
.steps { background: var(--c-surface-2); border-left: 2px solid var(--c-border); max-width: 100%; min-width: 0; }
.steps-h { display: flex; align-items: center; gap: 6px; width: 100%; padding: 6px 10px; border: 0; background: transparent; color: var(--c-text-2); font-size: var(--fs-xs); cursor: pointer; text-align: left; }
.steps ul { list-style: none; margin: 0; padding: 0 10px 8px 28px; display: flex; flex-direction: column; gap: 6px; }
.steps li { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: var(--fs-xs); color: var(--c-text); line-height: 1.5; }
.steps li > span:first-child { position: relative; }
.steps li > span:first-child::before { content: ''; position: absolute; left: -14px; top: 0.55em; width: 5px; height: 5px; border-radius: 50%; background: var(--c-text-3); }
.steps .btn { margin-left: auto; }
.tool-json { flex: 1 1 100%; margin: 0; max-height: 240px; overflow: auto; padding: 8px 10px; background: var(--c-surface); border: var(--bw) solid var(--c-border); font-family: var(--font-mono); font-size: 12px; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }
.turn-down { transform: rotate(90deg); }
.card { border: var(--bw) solid var(--c-border); background: var(--c-surface); max-width: 100%; min-width: 0; }
.ch { display: flex; align-items: flex-start; gap: 6px; padding: 8px 10px; font-weight: 600; font-size: var(--fs-sm); border-bottom: var(--bw) solid var(--c-border); position: relative; min-width: 0; }
.ch .desc { min-width: 0; overflow-wrap: anywhere; line-height: 1.45; }
.sheet { overflow: auto; max-height: 280px; }
.data { width: 100%; border-collapse: collapse; font-size: var(--fs-xs); }
.data th, .data td { padding: 4px 8px; border-bottom: var(--bw) solid var(--c-border); text-align: left; white-space: nowrap; }
.choices { display: flex; flex-wrap: wrap; gap: 8px; padding: 10px; }
.rec { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 8px 10px; border-bottom: var(--bw) solid var(--c-border); }
.rec .ask, .rec .seen { flex: 1 0 100%; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.rec .seen { flex-direction: column; align-items: stretch; }
.kv { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: var(--c-border); }
.kv div { display: flex; flex-direction: column; padding: 6px 10px; background: var(--c-surface); font-size: var(--fs-xs); color: var(--c-text-3); }
.kv b { color: var(--c-text); font-size: var(--fs-sm); }
.act-sentence { margin: 0; padding: 12px 14px 4px; line-height: 1.7; font-size: var(--fs-sm); }
.act-effects { margin: 0; padding: 4px 14px 8px 28px; color: var(--c-text-2); font-size: var(--fs-xs); line-height: 1.6; }
.act-result { margin: 0; padding: 0 14px 8px; color: var(--c-text-2); }
.act-actions { padding: 0 10px 10px; justify-content: flex-end; }
.act.pending { border-color: var(--c-warn); }
.act.rejected { opacity: 0.6; }
.act.expired { border-color: var(--c-border); background: var(--c-surface-2); color: var(--c-text-3); }
.act.expired .act-actions .btn {
  --_bg: var(--c-text-3);
  --_fg: var(--c-bg);
  --_bd: var(--c-text-3);
  opacity: 0.55;
  pointer-events: none;
}
.act.located { outline: 2px solid var(--c-primary); }
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
.pend li { border-bottom: var(--bw) solid var(--c-border); min-width: 0; }
.pend-jump { display: flex; flex-direction: column; gap: 4px; width: 100%; padding: 10px 12px; border: 0; background: transparent; color: inherit; text-align: left; cursor: pointer; }
.pend-jump:hover { background: var(--c-surface-3); }
.pend-jump.expired { background: var(--c-surface-2); color: var(--c-text-3); }
.pend-desc { overflow-wrap: anywhere; line-height: 1.45; }
.pend .none { color: var(--c-text-3); font-size: var(--fs-sm); text-align: center; padding: 20px; }
.usage { display: flex; align-items: baseline; gap: 6px; padding: 10px 12px; background: var(--c-surface); border: var(--bw) solid var(--c-border); }
.usage b { font-size: var(--fs-lg); margin-left: auto; }
</style>
