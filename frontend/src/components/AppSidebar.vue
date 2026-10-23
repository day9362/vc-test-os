<script setup lang="ts">
import { computed } from 'vue'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-vue-next'
import { NAV } from '@/router'
import { useAppStore } from '@/stores/app'
import { useLiveStore } from '@/stores/live'

const app = useAppStore()
const live = useLiveStore()

const groups = computed(() => {
  const map = new Map<string, typeof NAV>()
  NAV.forEach((n) => {
    if (!map.has(n.group)) map.set(n.group, [])
    map.get(n.group)!.push(n)
  })
  return [...map.entries()]
})

const badges = computed<Record<string, { n: number; kind: string } | undefined>>(() => ({
  overview: live.kpi.openAlarms ? { n: live.kpi.openAlarms, kind: live.kpi.critical ? 'danger' : 'warn' } : undefined,
  testing: live.production ? { n: live.batchStats.filter((b) => b.state === 'running').length, kind: 'info' } : undefined,
  devices: { n: live.machines.filter((m) => m.status === 'FAULT' || m.comm_status === 'DISCONNECTED').length, kind: 'warn' },
}))
</script>

<template>
  <aside class="nav" :class="{ collapsed: app.navCollapsed }" aria-label="主导航">
    <div class="brand">
      <div class="logo" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="20" height="20"><rect x="3" y="6" width="18" height="12" fill="none" stroke="currentColor" stroke-width="2.2" /><path d="M7 12h10" stroke="currentColor" stroke-width="2.2" /></svg>
      </div>
      <div v-if="!app.navCollapsed" class="brand-txt">
        <b>VC-TestOS</b>
        <span class="code-label">均热板热阻测试平台</span>
      </div>
    </div>

    <nav class="groups">
      <section v-for="[g, items] in groups" :key="g" class="group">
        <h6 v-if="!app.navCollapsed" class="code-label">{{ g }}</h6>
        <hr v-else class="divider" />
        <RouterLink
          v-for="it in items"
          :key="it.path"
          :to="it.path"
          class="item"
          v-tip="app.navCollapsed ? { text: it.title, placement: 'right' } : ''"
        >
          <component :is="it.icon" :size="18" :stroke-width="1.8" />
          <template v-if="!app.navCollapsed">
            <span class="grow ellipsis">{{ it.title }}</span>
            <span v-if="badges[it.name]?.n" class="badge" :class="badges[it.name]!.kind">{{ badges[it.name]!.n }}</span>
            <span v-else class="code mono">{{ it.code }}</span>
          </template>
          <i v-else-if="badges[it.name]?.n" class="pip" :class="badges[it.name]!.kind" />
        </RouterLink>
      </section>
    </nav>

    <div class="foot">
      <div v-if="!app.navCollapsed" class="safety">
        <span class="hazard stripe" aria-hidden="true" />
        <p>AI 不直接控制 PLC：所有写操作都转成集群 API 调用，经结构化校验与人工确认后执行。</p>
      </div>
      <button
        class="btn btn-ghost collapse"
        :class="{ 'btn-icon': app.navCollapsed }"
        v-tip="{ text: app.navCollapsed ? '展开导航' : '收起导航', kbd: '[', placement: 'right' }"
        @click="app.navCollapsed = !app.navCollapsed"
      >
        <PanelLeftOpen v-if="app.navCollapsed" :size="18" />
        <template v-else><PanelLeftClose :size="18" /><span class="grow" style="text-align: left">收起</span></template>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.nav {
  width: var(--nav-w);
  flex: none;
  display: flex;
  flex-direction: column;
  background: var(--c-nav-bg);
  border-right: var(--bw) solid var(--c-border-strong);
  transition: width 180ms var(--ease);
  overflow: hidden;
}
.nav.collapsed { width: var(--nav-w-collapsed); }

.brand {
  height: var(--topbar-h);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 14px;
  border-bottom: var(--bw) solid var(--c-border);
  border-top: 3px solid var(--c-topbar-rule);
  flex: none;
}
.collapsed .brand { padding: 0; justify-content: center; }
.logo {
  width: 28px; height: 28px; flex: none;
  display: grid; place-items: center;
  background: var(--c-primary); color: var(--c-on-primary);
}
.brand-txt { display: flex; flex-direction: column; line-height: 1.2; white-space: nowrap; }
.brand-txt b { font-size: var(--fs-lg); letter-spacing: 0.02em; }
.brand-txt .code-label { font-family: var(--font-sans); letter-spacing: 0.04em; font-size: 10px; }

.groups { flex: 1; overflow-y: auto; overflow-x: hidden; padding: 6px 8px; }
.group { padding: 6px 0; }
.group h6 { margin: 4px 8px 6px; font-size: 10px; }
.group .divider { margin: 2px 6px 8px; }
.item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  height: 36px;
  padding: 0 10px;
  margin-bottom: 2px;
  color: var(--c-text-2);
  border-radius: var(--radius);
  text-decoration: none;
  white-space: nowrap;
}
.collapsed .item { justify-content: center; padding: 0; }
.item:hover { background: var(--c-surface-3); color: var(--c-text); text-decoration: none; }
.item.router-link-active {
  background: var(--c-surface);
  color: var(--c-nav-active);
  font-weight: 600;
  box-shadow: inset 3px 0 0 var(--c-nav-active), inset 0 0 0 1px var(--c-border);
}
.item .code { font-size: 10px; color: var(--c-text-3); opacity: 0; transition: opacity var(--dur); }
.item:hover .code, .item.router-link-active .code { opacity: 1; }
.badge {
  min-width: 18px; height: 18px; padding: 0 5px;
  display: inline-grid; place-items: center;
  font-family: var(--font-mono); font-size: 10px; font-weight: 700;
  color: #fff; background: var(--c-idle);
}
.badge.danger { background: var(--c-danger); }
.badge.warn { background: var(--c-warn); }
.badge.info { background: var(--c-info); }
.pip { position: absolute; top: 7px; right: 9px; width: 7px; height: 7px; background: var(--c-warn); }
.pip.danger { background: var(--c-danger); }
.pip.info { background: var(--c-info); }

.foot { padding: 8px; border-top: var(--bw) solid var(--c-border); display: flex; flex-direction: column; gap: 8px; }
.safety { position: relative; padding: 8px 8px 8px 14px; background: var(--c-warn-weak); border: var(--bw) solid color-mix(in srgb, var(--c-warn) 35%, transparent); }
.safety .stripe { position: absolute; left: 0; top: 0; bottom: 0; width: 5px; }
.safety p { font-size: var(--fs-xs); color: var(--c-text-2); line-height: 1.5; }
.collapse { width: 100%; justify-content: flex-start; color: var(--c-text-2); }
.collapsed .collapse { justify-content: center; }
</style>
