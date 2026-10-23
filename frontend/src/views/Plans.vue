<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Bot, CheckCircle2, CircleAlert, Copy, FilePlus2, History, Loader2, Plus, RotateCcw, Search, Send, Sparkles, Trash2, Upload, XCircle,
} from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Panel from '@/components/Panel.vue'
import { api } from '@/api/http'
import type { LimitRule, Plan, PlanMeta } from '@/api/types'
import { useAppStore } from '@/stores/app'
import { CAPABILITY, LIMIT_ITEMS } from '@/mock/cluster'
import { ago } from '@/utils/format'

interface PlanItem { plan: Plan; meta: PlanMeta }
interface Issue { level: 'ok' | 'warn' | 'danger'; text: string }
interface ValidateOut { ok: boolean; issues: { level: Issue['level']; field?: string | null; message: string }[] }
interface PublishOut { plan_id: string; version: number; audit_id: string }
interface DraftOut extends PlanItem { audit_id: string }
interface FromTextOut extends DraftOut { notes: string[] }

const app = useAppStore()
const route = useRoute()
const router = useRouter()

const plans = ref<Plan[]>([])
const meta = ref<Record<string, PlanMeta>>({})
const loading = ref(true)
const loadError = ref('')
const publishing = ref(false)
const kw = ref('')
const filtered = computed(() => plans.value.filter((p) => (p.name + p.plan_id).toLowerCase().includes(kw.value.toLowerCase())))

const curId = ref((route.query.p as string) || '')
watch(curId, (id) => { if (id) router.replace({ query: { p: id } }) })
const cur = computed(() => plans.value.find((p) => p.plan_id === curId.value))
const curMeta = computed<PlanMeta>(() => meta.value[curId.value] ?? {
  plan_id: curId.value, versions: [], updated_at: 0, author: '', source: 'manual', draft: false,
})

function blankPlan(): Plan {
  return {
    plan_id: '', name: '', version: 0, start_temp_c: 25, duration_s: 60, sample_period_s: 1,
    power_w: 2.5, force_g: 100, orientation: 0, overtemp_c: 80, ambient_low_c: 23, ambient_high_c: 27, limits: [],
  }
}
/* 编辑副本：已发布方案不能原地改，发布时以同名 POST /api/plans 生成新版本 */
const edit = ref<Plan>(blankPlan())
watch(cur, (p) => { if (p) edit.value = JSON.parse(JSON.stringify(p)) })
const dirty = computed(() => !!cur.value && JSON.stringify(edit.value) !== JSON.stringify(cur.value))

const FIELDS: { k: keyof Plan; label: string; unit: string; min: number; max: number; step: number }[] = [
  { k: 'start_temp_c', label: '起始温度', unit: '℃', min: 20, max: 80, step: 0.5 },
  { k: 'duration_s', label: '测量时长', unit: 's', min: CAPABILITY.duration_low_s, max: CAPABILITY.duration_high_s, step: 1 },
  { k: 'sample_period_s', label: '采样周期', unit: 's', min: 1, max: 10, step: 1 },
  { k: 'power_w', label: '加热功率', unit: 'W', min: CAPABILITY.power_low_w, max: CAPABILITY.power_high_w, step: 0.1 },
  { k: 'force_g', label: '压紧力', unit: 'g', min: CAPABILITY.force_low_g, max: CAPABILITY.force_high_g, step: 1 },
  { k: 'overtemp_c', label: '超温保护', unit: '℃', min: 40, max: 120, step: 1 },
  { k: 'ambient_low_c', label: '环境温度下限', unit: '℃', min: 10, max: 40, step: 0.5 },
  { k: 'ambient_high_c', label: '环境温度上限', unit: '℃', min: 10, max: 40, step: 0.5 },
]
const fieldErr = (f: (typeof FIELDS)[number]) => {
  const v = edit.value[f.k] as number
  if (v === null || v === undefined || Number.isNaN(v)) return '必填'
  if (v < f.min || v > f.max) return `机台能力范围 ${f.min}–${f.max} ${f.unit}`
  return ''
}
const changed = (k: keyof Plan) => !!cur.value && JSON.stringify(edit.value[k]) !== JSON.stringify(cur.value[k])

const issues = ref<Issue[]>([])
const checking = ref(false)
const localErr = computed(() => !edit.value.name.trim() || FIELDS.some((f) => fieldErr(f)))
const hasErr = computed(() => localErr.value || issues.value.some((i) => i.level === 'danger'))

function num(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value))) return Number(value)
  return null
}
function planBody(plan: Plan): Record<string, unknown> | null {
  const name = plan.name.trim()
  const start = num(plan.start_temp_c)
  const duration = num(plan.duration_s)
  const sample = num(plan.sample_period_s)
  const power = num(plan.power_w)
  const force = num(plan.force_g)
  const over = num(plan.overtemp_c)
  const low = num(plan.ambient_low_c)
  const high = num(plan.ambient_high_c)
  if (!name || [start, duration, sample, power, force, over, low, high].some((v) => v === null)) return null
  return {
    name,
    start_temp_c: start,
    duration_s: Math.round(duration as number),
    sample_period_s: sample,
    power_w: power,
    force_g: force,
    orientation: plan.orientation,
    overtemp_c: over,
    ambient_low_c: low,
    ambient_high_c: high,
    limits: plan.limits.map((rule) => ({
      item: rule.item,
      low: num(rule.low),
      high: num(rule.high),
      unit: rule.unit,
      skipped: rule.skipped,
    })),
  }
}
function fail(title: string, err: unknown) {
  app.toast({ kind: 'danger', title, desc: err instanceof Error ? err.message : '请求失败' })
}

let validateTimer = 0
async function runValidate() {
  if (!cur.value) return
  if (!edit.value.name.trim()) {
    issues.value = [{ level: 'danger', text: '方案名称不能为空' }]
    return
  }
  const payload = planBody(edit.value)
  if (!payload) {
    issues.value = [{ level: 'danger', text: '有字段不是有效数字' }]
    return
  }
  checking.value = true
  try {
    const res = await api<ValidateOut>('/plans/validate', { method: 'POST', body: JSON.stringify(payload) })
    issues.value = res.issues.map((item) => ({ level: item.level, text: item.message }))
  } catch (err) {
    issues.value = [{ level: 'danger', text: err instanceof Error ? err.message : '校验失败' }]
  } finally {
    checking.value = false
  }
}

let saveTimer = 0
function scheduleSave(id: string) {
  window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => { void saveDraft(id) }, 700)
}
async function saveDraft(id: string) {
  if (curId.value !== id || !meta.value[id]?.draft) return
  const payload = planBody(edit.value)
  if (!payload) return
  try {
    const res = await api<DraftOut>(`/plan-drafts/${id}`, {
      method: 'PUT',
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify(payload),
    })
    if (curId.value !== id) return
    const current = plans.value.find((p) => p.plan_id === id)
    const latest = planBody(edit.value)
    if (current && JSON.stringify(latest) === JSON.stringify(payload)) Object.assign(current, res.plan)
    if (meta.value[id]) meta.value[id] = res.meta
    if (JSON.stringify(planBody(edit.value)) !== JSON.stringify(payload)) scheduleSave(id)
  } catch (err) {
    fail('草稿保存失败', err)
  }
}

watch(edit, () => {
  window.clearTimeout(validateTimer)
  validateTimer = window.setTimeout(() => { void runValidate() }, 400)
  if (curMeta.value.draft && dirty.value) scheduleSave(curId.value)
}, { deep: true })

async function reload(selectId?: string) {
  const items = await api<PlanItem[]>('/plans')
  plans.value = items.map((item) => item.plan)
  meta.value = Object.fromEntries(items.map((item) => [item.plan.plan_id, item.meta]))
  const wanted = selectId || curId.value || (route.query.p as string)
  curId.value = plans.value.some((p) => p.plan_id === wanted) ? wanted : (plans.value[0]?.plan_id ?? '')
}
onMounted(async () => {
  try {
    await reload()
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : '方案列表读取失败'
  } finally {
    loading.value = false
  }
})
onBeforeUnmount(() => {
  window.clearTimeout(validateTimer)
  window.clearTimeout(saveTimer)
})

const body = computed(() => {
  const { plan_id, version, ...rest } = edit.value
  return rest
})

/* 判定项 */
function addLimit() {
  const used = new Set(edit.value.limits.map((l) => l.item))
  const item = LIMIT_ITEMS.find((i) => !used.has(i)) ?? 'Temp_Ta'
  edit.value.limits.push({ item, low: 0, high: null, unit: item.startsWith('F') ? 'g' : item === 'power_w' ? 'W' : '℃', skipped: false })
}
function removeLimit(i: number) {
  const [r] = edit.value.limits.splice(i, 1)
  app.toast({ kind: 'info', title: `已删除判定项 ${r.item}`, action: { label: '撤销', run: () => edit.value.limits.splice(i, 0, r) } })
}
const bulk = ref<number | null>(null)
function applyBulk() {
  if (bulk.value === null) return
  edit.value.limits.filter((l) => /^Temp_T1-T/.test(l.item) && !l.skipped).forEach((l) => (l.high = bulk.value))
}

/* 版本 */
const viewVersion = ref<number | null>(null)
watch(curId, () => (viewVersion.value = null))
async function loadVersion(v: number) {
  if (!cur.value) return
  viewVersion.value = v
  if (v === cur.value.version) { edit.value = JSON.parse(JSON.stringify(cur.value)); return }
  try {
    const res = await api<PlanItem>(`/plans/${cur.value.plan_id}?version=${v}`)
    edit.value = res.plan
    app.toast({ kind: 'info', title: `已载入 v${v}`, desc: '可在此基础上发布为新版本' })
  } catch (err) {
    fail('历史版本读取失败', err)
  }
}

async function publish() {
  if (!cur.value || publishing.value) return
  const payload = planBody(edit.value)
  if (!payload) { app.toast({ kind: 'warn', title: '还有字段不合法' }); return }
  const isDraft = curMeta.value.draft
  const nextV = isDraft ? 1 : cur.value.version + 1
  const ok = await app.confirm({
    title: isDraft ? '发布方案' : `发布为 v${nextV}`,
    desc: `「${edit.value.name}」${isDraft ? '将写入集群并生成新方案' : '同名提交会生成新版本，旧版本保留'}。`,
    confirmText: '发布',
    checklist: ['已核对功率、压紧力与目标型号匹配', '判定项上下限已和工艺确认'],
  })
  if (!ok) return
  publishing.value = true
  window.clearTimeout(saveTimer)
  try {
    const check = await api<ValidateOut>('/plans/validate', { method: 'POST', body: JSON.stringify(payload) })
    issues.value = check.issues.map((item) => ({ level: item.level, text: item.message }))
    if (!check.ok) { app.toast({ kind: 'danger', title: '方案未通过校验' }); return }
    const res = await api<PublishOut>('/plans', {
      method: 'POST',
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({ ...payload, plan_id: curId.value }),
    })
    await reload(res.plan_id)
    app.toast({ kind: 'ok', title: `已发布 ${res.plan_id} v${res.version}`, action: { label: '去下发', run: () => router.push({ path: '/testing', query: { plan: res.plan_id } }) } })
  } catch (err) {
    fail('发布失败', err)
  } finally {
    publishing.value = false
  }
}
async function duplicate() {
  const payload = planBody({ ...edit.value, name: `${edit.value.name}（副本）` })
  if (!payload) { app.toast({ kind: 'warn', title: '还有字段不合法，不能复制' }); return }
  try {
    const res = await api<DraftOut>('/plan-drafts', {
      method: 'POST',
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify(payload),
    })
    plans.value.unshift(res.plan)
    meta.value[res.plan.plan_id] = res.meta
    curId.value = res.plan.plan_id
  } catch (err) {
    fail('草稿创建失败', err)
  }
}
async function removeDraft() {
  if (!cur.value) return
  if (!(await app.confirm({ title: '删除草稿', desc: `「${cur.value.name}」只保存在本地，删除后无法恢复。`, danger: true, confirmText: '删除' }))) return
  const id = curId.value
  try {
    await api(`/plan-drafts/${id}`, { method: 'DELETE', headers: { 'Idempotency-Key': crypto.randomUUID() } })
    plans.value = plans.value.filter((p) => p.plan_id !== id)
    delete meta.value[id]
    curId.value = plans.value[0]?.plan_id ?? ''
  } catch (err) {
    fail('草稿删除失败', err)
  }
}

/* 自然语言 → 方案（agent.plan） */
const nl = ref('')
const nlBusy = ref(false)
const nlNotes = ref<string[]>([])
const nlPlanId = ref('')
const NL_EXAMPLES = ['HVP 3.5W，压紧力 120g，测 3 分钟，T0-T1 不超过 3.4 度', 'tb179 竖放 90 度，测 4 分钟，T1 到各点温差不超过 4.2', '只看功率稳定性的 10 秒快速检查']
async function draft() {
  if (!nl.value.trim()) return
  nlBusy.value = true
  try {
    const res = await api<FromTextOut>('/plan-drafts/from-text', {
      method: 'POST',
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({ text: nl.value.trim() }),
    })
    plans.value.unshift(res.plan)
    meta.value[res.plan.plan_id] = res.meta
    curId.value = res.plan.plan_id
    nlPlanId.value = res.plan.plan_id
    nlNotes.value = res.notes
    nl.value = ''
  } catch (err) {
    fail('草稿生成失败', err)
  } finally {
    nlBusy.value = false
  }
}
</script>

<template>
  <div class="page">
    <PageHeader title="测试方案" desc="对应集群 /api/plans · 本地草稿只保存在平台，发布后才写入集群 · 下发在「测试执行」">
      <button class="btn" :disabled="!cur" @click="duplicate"><Copy :size="16" />复制为草稿</button>
      <button class="btn btn-primary" :disabled="!cur || curMeta.draft" @click="router.push({ path: '/testing', query: { plan: curId } })" v-tip="curMeta.draft ? '草稿需先发布' : ''"><Send :size="16" />去下发</button>
    </PageHeader>
    <p v-if="loadError" class="load-err">{{ loadError }} <button class="btn btn-sm" @click="reload().then(() => { loadError = '' }).catch((err) => fail('方案列表读取失败', err))">重试</button></p>

    <div class="lay">
      <!-- 方案列表 -->
      <Panel flush class="side">
        <div class="pad"><div class="input-wrap" style="width: 100%"><Search :size="14" /><input v-model="kw" class="input" placeholder="名称 / plan_id" aria-label="搜索方案" /></div></div>
        <ul class="plist">
          <li v-if="loading" class="empty">正在读取方案…</li>
          <li v-else-if="!filtered.length" class="empty">没有匹配的方案</li>
          <li v-for="p in filtered" :key="p.plan_id">
            <button :class="{ on: p.plan_id === curId }" @click="curId = p.plan_id">
              <div class="row-between">
                <b class="ellipsis">{{ p.name }}</b>
                <span v-if="meta[p.plan_id]?.draft" class="tag warn">草稿</span>
                <span v-else class="tag primary num">v{{ p.version }}</span>
              </div>
              <div class="row-between fs-xs muted">
                <span class="mono">{{ p.plan_id }}</span>
                <span class="row gap-4"><Bot v-if="meta[p.plan_id]?.source === 'agent'" :size="12" v-tip="'由 Agent 生成'" />{{ ago(meta[p.plan_id]?.updated_at ?? Date.now()) }}</span>
              </div>
              <div class="fs-xs text-2 num">{{ p.power_w }} W · {{ p.force_g }} g · {{ p.duration_s }} s · {{ p.orientation }}°</div>
            </button>
          </li>
        </ul>
      </Panel>

      <div class="col" style="gap: 12px; min-width: 0">
        <!-- 自然语言起草 -->
        <Panel title="用一句话起草方案" code="AGENT.PLAN · qwen3-max" :icon="Sparkles">
          <div class="row">
            <div class="input-wrap grow"><Bot :size="14" /><input v-model="nl" class="input" placeholder="例如：HVP 3.5W，压紧力 120g，测 3 分钟，T0-T1 不超过 3.4 度" :disabled="nlBusy" @keydown.enter="draft" /></div>
            <button class="btn btn-primary" :disabled="nlBusy || !nl.trim()" @click="draft"><Loader2 v-if="nlBusy" :size="16" class="spin" /><FilePlus2 v-else :size="16" />生成草稿</button>
          </div>
          <div class="row wrap gap-4" style="margin-top: 8px">
            <button v-for="e in NL_EXAMPLES" :key="e" class="chip" @click="nl = e">{{ e }}</button>
          </div>
          <ul v-if="nlNotes.length && curId === nlPlanId" class="notes">
            <li v-for="n in nlNotes" :key="n">{{ n }}</li>
          </ul>
        </Panel>

        <!-- 编辑器 -->
        <Panel v-if="cur" flush>
          <div class="eh">
            <div class="grow" style="min-width: 0">
              <input v-model="edit.name" class="title-in" aria-label="方案名称" />
              <div class="row fs-xs muted">
                <span class="mono">{{ edit.plan_id }}</span>
                <span>·</span><span>{{ curMeta.author }} · {{ ago(curMeta.updated_at) }}</span>
                <span v-if="dirty" class="tag warn">未发布的修改</span>
              </div>
            </div>
            <div v-if="!curMeta.draft" class="row gap-4">
              <History :size="14" class="muted" />
              <select class="select" style="width: 120px" :value="viewVersion ?? cur.version" aria-label="历史版本" @change="loadVersion(+($event.target as HTMLSelectElement).value)">
                <option v-for="v in [...curMeta.versions].reverse()" :key="v" :value="v">v{{ v }}{{ v === cur.version ? '（最新）' : '' }}</option>
              </select>
            </div>
            <button v-if="dirty" class="btn btn-ghost" v-tip="'放弃修改'" @click="edit = JSON.parse(JSON.stringify(cur))"><RotateCcw :size="16" /></button>
            <button v-if="curMeta.draft" class="btn btn-ghost btn-icon" v-tip="'删除草稿'" @click="removeDraft"><Trash2 :size="16" /></button>
            <button class="btn btn-primary" :disabled="publishing || hasErr || (!dirty && !curMeta.draft)" @click="publish">
              <Loader2 v-if="publishing" :size="16" class="spin" /><Upload v-else :size="16" />{{ curMeta.draft ? '发布方案' : `发布为 v${cur.version + 1}` }}
            </button>
          </div>

          <div class="eb">
            <div class="form">
              <h4 class="code-label">测量参数</h4>
              <div class="fgrid">
                <div v-for="f in FIELDS" :key="f.k" class="field" :class="{ chg: changed(f.k), err: fieldErr(f) }">
                  <label :for="`f-${f.k}`">{{ f.label }} <span class="mono muted fs-xs">{{ f.k }}</span></label>
                  <div class="unit-in">
                    <input :id="`f-${f.k}`" v-model.number="(edit as any)[f.k]" class="input num" type="number" :min="f.min" :max="f.max" :step="f.step" />
                    <span>{{ f.unit }}</span>
                  </div>
                  <span class="hint" :class="{ 't-danger': fieldErr(f) }">{{ fieldErr(f) || `${f.min}–${f.max}` }}</span>
                </div>
                <div class="field" :class="{ chg: changed('orientation') }">
                  <label>朝向 <span class="mono muted fs-xs">orientation</span></label>
                  <div class="seg">
                    <button v-for="o in [0, 90, 180, 270]" :key="o" :aria-pressed="edit.orientation === o" @click="edit.orientation = o">{{ o }}°</button>
                  </div>
                </div>
              </div>

              <div class="row-between" style="margin-top: 18px">
                <h4 class="code-label">判定项 limits · {{ edit.limits.filter((l) => !l.skipped).length }} 项生效</h4>
                <div class="row gap-4">
                  <span class="fs-xs muted">T1-Tx 上限统一设为</span>
                  <input v-model.number="bulk" class="input num" type="number" step="0.1" style="width: 72px; height: 28px" aria-label="批量上限" />
                  <button class="btn btn-sm" :disabled="bulk === null" @click="applyBulk">应用</button>
                  <button class="btn btn-sm" @click="addLimit"><Plus :size="14" />添加</button>
                </div>
              </div>
              <div class="table-wrap lim">
                <table class="table">
                  <thead><tr><th>判定项 item</th><th style="width: 110px">下限 low</th><th style="width: 110px">上限 high</th><th style="width: 70px">单位</th><th style="width: 70px" class="c">跳过</th><th style="width: 44px" /></tr></thead>
                  <tbody>
                    <tr v-for="(l, i) in edit.limits" :key="i" :class="{ skip: l.skipped }">
                      <td>
                        <select v-model="l.item" class="select cell mono" aria-label="判定项">
                          <option v-for="it in LIMIT_ITEMS" :key="it" :value="it">{{ it }}</option>
                        </select>
                      </td>
                      <td><input v-model.number="l.low" class="input cell num" type="number" step="0.1" placeholder="不限" :disabled="l.skipped" aria-label="下限" /></td>
                      <td><input v-model.number="l.high" class="input cell num" type="number" step="0.1" placeholder="不限" :disabled="l.skipped" aria-label="上限" :class="{ bad: !l.skipped && l.low !== null && l.high !== null && l.low >= l.high }" /></td>
                      <td class="mono fs-sm">{{ l.unit }}</td>
                      <td class="c"><input v-model="l.skipped" type="checkbox" :aria-label="`跳过 ${l.item}`" /></td>
                      <td><button class="btn btn-ghost btn-icon btn-sm" v-tip="'删除'" @click="removeLimit(i)"><Trash2 :size="14" /></button></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <aside class="aside">
              <h4 class="code-label">发布前校验{{ checking ? ' · 校验中' : '' }}</h4>
              <ul class="checks">
                <li v-for="c in issues" :key="c.text" :class="c.level">
                  <CheckCircle2 v-if="c.level === 'ok'" :size="14" /><CircleAlert v-else-if="c.level === 'warn'" :size="14" /><XCircle v-else :size="14" />
                  <span>{{ c.text }}</span>
                </li>
              </ul>
              <h4 class="code-label" style="margin-top: 14px">请求体 · POST /api/plans</h4>
              <pre class="json">{{ JSON.stringify(body, null, 2) }}</pre>
            </aside>
          </div>
        </Panel>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lay { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 12px; align-items: start; }
.side { position: sticky; top: 0; }
.pad { padding: 10px; border-bottom: var(--bw) solid var(--c-border); }
.load-err { margin: 0 0 12px; padding: 8px 12px; background: var(--c-danger-weak, #fde8e8); color: var(--c-danger); display: flex; align-items: center; gap: 8px; }
.plist { list-style: none; margin: 0; padding: 0; max-height: calc(100vh - 210px); overflow: auto; }
.empty { padding: 16px 12px; color: var(--c-text-3); font-size: var(--fs-sm); }
.plist button { width: 100%; text-align: left; display: flex; flex-direction: column; gap: 3px; padding: 10px 12px; border: 0; border-bottom: var(--bw) solid var(--c-border); background: transparent; cursor: pointer; }
.plist button:hover { background: var(--c-surface-2); }
.plist button.on { background: var(--c-primary-weak); box-shadow: inset 3px 0 0 var(--c-primary); }
.chip { height: 26px; padding: 0 10px; border: var(--bw) dashed var(--c-border-strong); background: var(--c-surface-2); color: var(--c-text-2); font-size: var(--fs-xs); cursor: pointer; }
.chip:hover { border-style: solid; color: var(--c-text); }
.notes { margin: 10px 0 0; padding: 8px 12px 8px 28px; background: var(--c-surface-2); border-left: 3px solid var(--c-primary); font-size: var(--fs-sm); color: var(--c-text-2); }
.spin { animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.eh { display: flex; align-items: center; gap: 8px; padding: 12px 14px; border-bottom: var(--bw) solid var(--c-border); }
.title-in { width: 100%; border: 0; border-bottom: var(--bw) dashed transparent; background: transparent; font-size: var(--fs-lg); font-weight: 700; padding: 0; }
.title-in:hover { border-bottom-color: var(--c-border-strong); }
.title-in:focus { outline: none; border-bottom-color: var(--c-primary); }
.eb { display: grid; grid-template-columns: minmax(0, 1fr) 320px; }
@media (max-width: 1360px) { .eb { grid-template-columns: 1fr; } }
.form { padding: 14px; min-width: 0; }
.form h4 { margin-bottom: 8px; }
.fgrid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px 14px; }
.field.chg > label::after { content: '已修改'; margin-left: 6px; font-size: 10px; color: var(--c-warn); font-weight: 700; }
.field.err .input { border-color: var(--c-danger); }
.unit-in { display: flex; }
.unit-in .input { flex: 1; border-right: 0; }
.unit-in span { display: grid; place-items: center; min-width: 36px; padding: 0 8px; border: var(--bw) solid var(--c-border-strong); background: var(--c-surface-2); color: var(--c-text-3); font-size: var(--fs-sm); }
.lim { border: var(--bw) solid var(--c-border); max-height: 420px; }
.lim td { height: 34px; padding: 0 6px; }
.cell { height: 28px; width: 100%; }
.cell.bad { border-color: var(--c-danger); }
.lim tr.skip td { color: var(--c-text-3); background: var(--c-surface-2); }
.lim input[type='checkbox'] { accent-color: var(--c-primary); }
.aside { padding: 14px; border-left: var(--bw) solid var(--c-border); background: var(--c-surface-2); min-width: 0; }
@media (max-width: 1360px) { .aside { border-left: 0; border-top: var(--bw) solid var(--c-border); } }
.checks { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.checks li { display: flex; gap: 6px; align-items: flex-start; font-size: var(--fs-sm); padding: 5px 8px; background: var(--c-surface); border-left: 3px solid var(--c-ok); }
.checks li svg { flex: none; margin-top: 3px; color: var(--c-ok); }
.checks li.warn { border-left-color: var(--c-warn); } .checks li.warn svg { color: var(--c-warn); }
.checks li.danger { border-left-color: var(--c-danger); color: var(--c-danger); } .checks li.danger svg { color: var(--c-danger); }
.json { margin: 8px 0 0; padding: 10px; background: var(--c-surface); border: var(--bw) solid var(--c-border); font-family: var(--font-mono); font-size: 11px; max-height: 420px; overflow: auto; }
</style>
