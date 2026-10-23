<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Bell, BellOff, CheckCheck, ChevronDown, ChevronRight, HardHat, LogOut, MonitorCog, Search, ShieldCheck, Sparkles, UserCog,
} from 'lucide-vue-next'
import Popover from './Popover.vue'
import ThemeSwitcher from './ThemeSwitcher.vue'
import { logout } from '@/api/http'
import { ROLES, useAppStore } from '@/stores/app'
import { useLiveStore } from '@/stores/live'
import { useSettingsStore } from '@/stores/settings'
import { ago, hms } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const app = useAppStore()
const live = useLiveStore()

const now = ref(Date.now())
const t = window.setInterval(() => (now.value = Date.now()), 1000)
onBeforeUnmount(() => window.clearInterval(t))

const alarmOpen = ref(false)
const roleOpen = ref(false)
const openAlarms = computed(() => live.alarms.filter((a) => !a.acked).slice(0, 6))
const roleIcon = { process: HardHat, test: UserCog, quality: ShieldCheck, admin: MonitorCog }
const currentRole = computed(() => ROLES.find((r) => r.id === app.role)!)
const displayName = computed(() => app.session?.name || '未登录')
const displayTenant = computed(() => app.session?.tenant_name || currentRole.value.name)

async function signOut() {
  roleOpen.value = false
  await logout()
  app.setSession(null)
  await router.replace('/login')
}

const settings = useSettingsStore()
const sourceText = computed(() => (settings.saved.source === 'sim' ? '仿真平台' : '真实集群'))
const host = computed(() => settings.baseUrl.replace(/^https?:\/\//, '').replace(/\/api\/?$/, ''))
const bad = computed(() => live.machines.filter((m) => m.comm_status !== 'ONLINE').length)
const linkText = computed(() => ({ online: '集群通信正常', degraded: `${bad.value} 台通信异常`, offline: '集群连接断开' })[live.link])
const linkKind = computed(() => ({ online: 'ok', degraded: 'warn', offline: 'danger' })[live.link])
const levelText = { critical: '严重', major: '主要', minor: '次要' }
const levelKind = { critical: 'danger', major: 'warn', minor: 'info' }
</script>

<template>
  <header class="top">
    <div class="crumb">
      <span class="code-label">{{ route.meta.group }}</span>
      <ChevronRight :size="14" class="muted" />
      <h1>{{ route.meta.title }}</h1>
      <span class="code-label pg">{{ route.meta.code }}</span>
    </div>

    <button class="search" @click="app.paletteOpen = true" aria-label="搜索或用自然语言提问">
      <Search :size="16" />
      <span class="grow ellipsis">搜索机台 / 批次 / 方案，或直接问 Agent…</span>
      <Sparkles :size="14" class="t-primary" />
      <span class="kbd">Ctrl K</span>
    </button>

    <div class="right">
      <button class="link" :class="linkKind" v-tip="`数据源 ${settings.baseUrl} · 最后更新 ${hms(live.lastUpdate)}`" @click="router.push('/settings')">
        <span class="src mono">{{ sourceText }} · {{ host }}</span>
        <span class="dot pulse" :class="linkKind" />
        <span class="fs-sm">{{ live.paused ? '已暂停刷新' : linkText }}</span>
      </button>
      <span class="clock num" aria-label="当前时间">{{ hms(now) }}</span>
      <span class="vdivider" />

      <Popover v-model:open="alarmOpen" :width="380">
        <template #trigger="{ toggle }">
          <button class="btn btn-ghost btn-icon bell" :aria-expanded="alarmOpen" v-tip="'告警中心'" @click="toggle">
            <Bell :size="18" />
            <span v-if="live.kpi.openAlarms" class="cnt" :class="{ crit: live.kpi.critical }">{{ live.kpi.openAlarms }}</span>
          </button>
        </template>
        <template #default="{ close }">
          <div class="pop-hd row-between">
            <span class="code-label">未确认告警 · {{ live.kpi.openAlarms }}</span>
            <button class="btn btn-ghost btn-sm" :disabled="!live.kpi.openAlarms" @click="live.ackAll(); app.toast({ kind: 'ok', title: '已全部确认' })">
              <CheckCheck :size="14" />全部确认
            </button>
          </div>
          <ul v-if="openAlarms.length" class="al-list">
            <li v-for="a in openAlarms" :key="a.id" :class="levelKind[a.level]">
              <div class="row-between">
                <span class="row gap-4">
                  <span class="tag" :class="levelKind[a.level]">{{ levelText[a.level] }}</span>
                  <b class="mono fs-sm">{{ a.machine_id }}{{ a.slot_index ? `#${a.slot_index}` : '' }}</b>
                  <span class="muted fs-xs">{{ a.source }} · {{ a.code }}</span>
                </span>
                <span class="muted fs-xs">{{ ago(a.time, now) }}</span>
              </div>
              <p class="fs-sm">{{ a.message }}</p>
            </li>
          </ul>
          <div v-else class="empty">
            <BellOff :size="22" />
            <span>没有未确认告警</span>
          </div>
          <div class="pop-ft">
            <button class="btn btn-sm" style="width: 100%" @click="close(); router.push('/overview')">在运行总览中查看</button>
          </div>
        </template>
      </Popover>

      <ThemeSwitcher />

      <Popover v-model:open="roleOpen" :width="260">
        <template #trigger="{ toggle }">
          <button class="user" :aria-expanded="roleOpen" @click="toggle">
            <span class="avatar"><component :is="roleIcon[app.role]" :size="16" /></span>
            <span class="who">
              <b>{{ displayName }}</b>
              <span class="fs-xs muted">{{ displayTenant }}</span>
            </span>
            <ChevronDown :size="14" class="muted" />
          </button>
        </template>
        <template #default="{ close }">
          <div class="pop-hd"><span class="code-label">切换视角</span></div>
          <div class="roles">
            <button
              v-for="r in ROLES"
              :key="r.id"
              class="role"
              :aria-pressed="app.role === r.id"
              @click="app.role = r.id; close(); app.toast({ kind: 'info', title: `已切换为「${r.name}」视角`, desc: r.desc })"
            >
              <component :is="roleIcon[r.id]" :size="16" />
              <span class="grow">
                <b class="fs-sm">{{ r.name }}</b>
                <span class="fs-xs muted" style="display: block">{{ r.desc }}</span>
              </span>
            </button>
          </div>
          <div class="pop-ft">
            <button class="btn btn-ghost btn-sm" style="width: 100%; justify-content: flex-start" @click="signOut"><LogOut :size="14" />退出登录</button>
          </div>
        </template>
      </Popover>
    </div>
  </header>
</template>

<style scoped>
.top {
  height: var(--topbar-h);
  flex: none;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 12px 0 20px;
  background: var(--c-topbar-bg);
  border-top: 3px solid var(--c-topbar-rule);
  border-bottom: var(--bw) solid var(--c-border-strong);
}
.crumb { display: flex; align-items: center; gap: 6px; min-width: 0; flex: none; }
.crumb h1 { font-size: var(--fs-lg); font-weight: 700; white-space: nowrap; }
.crumb .pg { padding: 1px 5px; border: var(--bw) solid var(--c-border); }

.search {
  flex: 0 1 440px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  height: var(--h-ctl);
  padding: 0 8px 0 10px;
  border: var(--bw) solid var(--c-border-strong);
  border-radius: var(--radius);
  background: var(--c-surface-2);
  color: var(--c-text-3);
  text-align: left;
  cursor: text;
  min-width: 160px;
}
.search:hover { border-color: var(--c-text-2); background: var(--c-surface); }

.right { display: flex; align-items: center; gap: 6px; flex: none; }
.link { display: flex; align-items: center; gap: 6px; height: 30px; padding: 0 8px; color: var(--c-text-2); background: transparent; border: var(--bw) solid transparent; cursor: pointer; }
.link:hover { border-color: var(--c-border); background: var(--c-surface-2); }
.link .src { font-size: var(--fs-xs); color: var(--c-text-3); padding-right: 6px; border-right: var(--bw) solid var(--c-border); }
.link.warn { color: var(--c-warn); }
.link.danger { color: var(--c-danger); }
.clock { font-size: var(--fs-sm); color: var(--c-text-2); padding: 0 4px; }
.vdivider { height: 22px; margin: 0 4px; }

.bell { position: relative; }
.cnt {
  position: absolute; top: 2px; right: 1px;
  min-width: 16px; height: 16px; padding: 0 3px;
  font-family: var(--font-mono); font-size: 10px; font-weight: 700; line-height: 16px;
  color: #fff; background: var(--c-warn);
}
.cnt.crit { background: var(--c-danger); }

.pop-hd { padding: 10px 12px; border-bottom: var(--bw) solid var(--c-border); }
.pop-ft { padding: 8px; border-top: var(--bw) solid var(--c-border); }
.al-list { list-style: none; margin: 0; padding: 0; max-height: 360px; overflow: auto; }
.al-list li { padding: 10px 12px; border-bottom: var(--bw) solid var(--c-border); box-shadow: inset 3px 0 0 var(--c-info); display: flex; flex-direction: column; gap: 4px; }
.al-list li.danger { box-shadow: inset 3px 0 0 var(--c-danger); }
.al-list li.warn { box-shadow: inset 3px 0 0 var(--c-warn); }
.al-list li:last-child { border-bottom: 0; }
.empty { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 28px; color: var(--c-text-3); }

.user {
  display: flex; align-items: center; gap: 8px;
  height: 38px; padding: 0 8px 0 4px;
  border: var(--bw) solid transparent; border-radius: var(--radius);
  background: transparent; cursor: pointer;
}
.user:hover { background: var(--c-surface-3); }
.avatar { width: 28px; height: 28px; display: grid; place-items: center; background: var(--c-accent); color: #fff; }
.who { display: flex; flex-direction: column; align-items: flex-start; line-height: 1.2; }
.who b { font-size: var(--fs-sm); }
.roles { padding: 6px; display: flex; flex-direction: column; gap: 2px; }
.role {
  display: flex; align-items: center; gap: 10px; padding: 8px;
  border: var(--bw) solid transparent; border-radius: var(--radius);
  background: transparent; text-align: left; cursor: pointer; color: var(--c-text-2);
}
.role:hover { background: var(--c-surface-2); }
.role[aria-pressed='true'] { border-color: var(--c-primary); background: var(--c-primary-weak); color: var(--c-primary); }

@media (max-width: 1100px) {
  .link span:last-child, .link .src, .clock { display: none; }
}
</style>
