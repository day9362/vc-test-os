import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api/http'
import type { AiModule } from '@/api/types'
import { AI_MODULES } from '@/mock/cluster'

export interface SyncJob {
  key: string
  name: string
  api: string
  interval_s: number
  enabled: boolean
  note: string
}

export interface PlatformSettings {
  source: 'cluster' | 'sim'
  cluster: { base_url: string; token: string; timeout_s: number; retries: number; on_503: 'skip' | 'pause' }
  sim: { base_url: string; speed: number; use_ground_truth: boolean }
  jobs: SyncJob[]
  storage: { dsn: string; samples_days: number; runs_days: number; agg_5m: boolean; object_store: string }
  ai: { base_url: string; api_key: string; monthly_budget_m: number; alert_pct: number; models: Record<AiModule, string> }
  rules: { drift_c: number; we_rules: string[]; sentinel_as_data_anomaly: boolean; degraded_alarm: boolean; ack_timeout_min: number }
}

export const DEFAULT_JOBS: SyncJob[] = [
  { key: 'fleet', name: '机群状态', api: 'GET /api/fleet', interval_s: 2, enabled: true, note: '状态、通信、已装载方案、排队剩余' },
  { key: 'slots', name: '槽位实时', api: 'GET /api/machines/{id}/slots', interval_s: 1, enabled: true, note: '步骤、功率、真空、各测点温度；DISCONNECTED 时跳过' },
  { key: 'machine', name: '机台详情', api: 'GET /api/machines/{id}', interval_s: 10, enabled: true, note: '配置、报警、房间温度、能力范围' },
  { key: 'runs', name: '测试记录', api: 'GET /api/runs', interval_s: 5, enabled: true, note: '按 run_id 增量入库，RUNNING 记录持续跟踪' },
  { key: 'samples', name: '过程曲线', api: 'GET /api/runs/{id}/samples?since=', interval_s: 2, enabled: true, note: '用 seq 增量拉取，写入时序表' },
  { key: 'plans', name: '测试方案', api: 'GET /api/plans', interval_s: 60, enabled: true, note: '最新版本；历史版本按需拉取' },
  { key: 'batches', name: '批次与型号', api: 'GET /api/products/batches', interval_s: 300, enabled: true, note: '含 /api/product-models' },
  { key: 'calib', name: '补偿与漂移', api: 'GET /api/machines/{id}/compensation · /drifts', interval_s: 60, enabled: true, note: '用于设备一致性页' },
  { key: 'agg', name: '5 分钟汇总', api: '本地 · 连续聚合 agg_5m', interval_s: 300, enabled: true, note: '良率、Rc 均值、异常数' },
]

const DEFAULTS: PlatformSettings = {
  source: 'sim',
  cluster: { base_url: 'http://10.20.1.10:18000/api', token: '', timeout_s: 5, retries: 2, on_503: 'skip' },
  sim: { base_url: 'https://cluster.simuoss.cn/api', speed: 1, use_ground_truth: false },
  jobs: DEFAULT_JOBS,
  storage: { dsn: 'postgresql://vcos@127.0.0.1:5432/vcos', samples_days: 400, runs_days: 1095, agg_5m: true, object_store: 'minio://127.0.0.1:9000/vcos' },
  ai: {
    base_url: 'https://api.example.com/v1',
    api_key: '',
    monthly_budget_m: 120,
    alert_pct: 80,
    models: Object.fromEntries(AI_MODULES.map((m) => [m.id, m.model])) as Record<AiModule, string>,
  },
  rules: { drift_c: 0.15, we_rules: ['WE-1', 'WE-2', 'WE-4'], sentinel_as_data_anomaly: true, degraded_alarm: true, ack_timeout_min: 15 },
}

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v))

function normalize(body: PlatformSettings): PlatformSettings {
  const next = clone(DEFAULTS)
  next.source = body.source || next.source
  next.cluster = { ...next.cluster, ...body.cluster }
  next.sim = { ...next.sim, ...body.sim }
  next.jobs = body.jobs?.length ? body.jobs : next.jobs
  next.storage = { ...next.storage, ...body.storage }
  next.ai = { ...next.ai, ...body.ai, models: { ...next.ai.models, ...(body.ai?.models || {}) } }
  next.rules = { ...next.rules, ...body.rules, we_rules: body.rules?.we_rules?.length ? [...body.rules.we_rules] : next.rules.we_rules }
  return next
}

export const useSettingsStore = defineStore('settings', () => {
  const saved = ref<PlatformSettings>(clone(DEFAULTS))
  const draft = ref<PlatformSettings>(clone(DEFAULTS))
  const dirty = computed(() => JSON.stringify(saved.value) !== JSON.stringify(draft.value))

  async function load() {
    const body = await api<PlatformSettings>('/settings')
    const next = normalize(body)
    const editing = dirty.value
    saved.value = clone(next)
    if (!editing) draft.value = clone(next)
  }

  async function save() {
    const body = await api<PlatformSettings>('/settings', {
      method: 'PUT',
      body: JSON.stringify(draft.value),
      headers: { 'Idempotency-Key': crypto.randomUUID() },
    })
    const next = normalize(body)
    saved.value = clone(next)
    draft.value = clone(next)
  }

  function discard() {
    draft.value = clone(saved.value)
  }
  function reset() {
    draft.value = clone(DEFAULTS)
  }
  function commitSpeed(speed: number) {
    draft.value.sim.speed = speed
    saved.value.sim.speed = speed
  }

  const baseUrl = computed(() => (saved.value.source === 'sim' ? saved.value.sim.base_url : saved.value.cluster.base_url))

  load().catch(() => { /* 设置页会提示加载失败 */ })

  return { saved, draft, dirty, load, save, discard, reset, commitSpeed, baseUrl }
})
