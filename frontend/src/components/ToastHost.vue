<script setup lang="ts">
import { CircleAlert, CircleCheck, CircleX, Info, X } from 'lucide-vue-next'
import { useAppStore } from '@/stores/app'

const app = useAppStore()
const icons = { ok: CircleCheck, info: Info, warn: CircleAlert, danger: CircleX }
</script>

<template>
  <div class="host" aria-live="polite">
    <TransitionGroup name="t">
      <div v-for="t in app.toasts" :key="t.id" class="toast" :class="t.kind" role="status">
        <component :is="icons[t.kind]" :size="18" class="ic" />
        <div class="grow">
          <b>{{ t.title }}</b>
          <p v-if="t.desc" class="fs-sm text-2">{{ t.desc }}</p>
        </div>
        <button v-if="t.action" class="btn btn-sm" @click="t.action.run(); app.dismiss(t.id)">{{ t.action.label }}</button>
        <button class="btn btn-ghost btn-icon btn-sm" v-tip="'关闭'" @click="app.dismiss(t.id)"><X :size="14" /></button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.host { position: fixed; right: 16px; bottom: 16px; z-index: 100; display: flex; flex-direction: column; gap: 8px; width: 360px; max-width: calc(100vw - 32px); }
.toast {
  --_c: var(--c-info);
  display: flex; align-items: flex-start; gap: 10px;
  padding: 10px 8px 10px 12px;
  background: var(--c-surface);
  border: var(--bw) solid var(--c-border-strong);
  box-shadow: inset 4px 0 0 var(--_c), var(--shadow-pop);
}
.toast.ok { --_c: var(--c-ok); }
.toast.warn { --_c: var(--c-warn); }
.toast.danger { --_c: var(--c-danger); }
.ic { color: var(--_c); flex: none; margin-top: 1px; }
.t-enter-active, .t-leave-active { transition: all 180ms var(--ease); }
.t-enter-from { opacity: 0; transform: translateX(16px); }
.t-leave-to { opacity: 0; transform: translateX(16px); }
</style>
