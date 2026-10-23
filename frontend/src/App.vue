<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppSidebar from './components/AppSidebar.vue'
import AppTopbar from './components/AppTopbar.vue'
import CommandPalette from './components/CommandPalette.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import ToastHost from './components/ToastHost.vue'
import { useAppStore } from './stores/app'
import { useLiveStore } from './stores/live'
import { THEMES, useThemeStore } from './stores/theme'

const route = useRoute()
const app = useAppStore()
const theme = useThemeStore()
const live = useLiveStore()
const authed = computed(() => route.name !== 'login')
watch(authed, (on) => { if (on) live.start() })

function typing(e: KeyboardEvent) {
  const el = e.target as HTMLElement
  return el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)
}

function onKey(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    app.paletteOpen = !app.paletteOpen
    return
  }
  if (e.altKey && e.key.toLowerCase() === 't') {
    e.preventDefault()
    theme.cycle()
    const t = THEMES.find((x) => x.id === theme.theme)!
    app.toast({ kind: 'info', title: `主题：${t.name}`, desc: t.desc }, 1800)
    return
  }
  if (typing(e) || app.paletteOpen || app.confirmState) return
  if (e.key === '[') app.navCollapsed = !app.navCollapsed
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  if (authed.value) live.start()
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <RouterView v-if="!authed" />
  <template v-else>
  <a class="skip sr-only" href="#main">跳到主内容</a>
  <div class="shell">
    <AppSidebar />
    <div class="main">
      <AppTopbar />
      <main id="main" class="content" tabindex="-1">
        <RouterView v-slot="{ Component }">
          <Transition name="page" mode="out-in">
            <component :is="Component" />
          </Transition>
        </RouterView>
      </main>
    </div>
  </div>
  <CommandPalette />
  <ConfirmDialog />
  <ToastHost />
  </template>
</template>

<style scoped>
.shell { display: flex; height: 100%; min-width: 1024px; }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.content { flex: 1; overflow: auto; outline: none; }
.skip:focus { position: fixed; top: 8px; left: 8px; z-index: 200; width: auto; height: auto; clip: auto; padding: 8px 12px; background: var(--c-primary); color: #fff; }
.page-enter-active, .page-leave-active { transition: opacity 120ms var(--ease), transform 120ms var(--ease); }
.page-enter-from { opacity: 0; transform: translateY(4px); }
.page-leave-to { opacity: 0; }
</style>
