<script setup lang="ts">
import type { Component } from 'vue'

defineProps<{ title?: string; code?: string; icon?: Component; flush?: boolean; accent?: 'primary' | 'warn' | 'danger' | 'ok' }>()
</script>

<template>
  <section class="panel" :class="accent ? `ac-${accent}` : ''">
    <header v-if="title || $slots.actions" class="hd">
      <component :is="icon" v-if="icon" :size="16" class="ic" />
      <h3 class="grow ellipsis">
        {{ title }}
        <span v-if="code" class="code-label">{{ code }}</span>
      </h3>
      <div class="row gap-4"><slot name="actions" /></div>
    </header>
    <div class="bd" :class="{ flush }"><slot /></div>
    <footer v-if="$slots.footer" class="ft"><slot name="footer" /></footer>
  </section>
</template>

<style scoped>
.panel {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--c-surface);
  border: var(--bw) solid var(--c-border);
  border-radius: var(--radius);
}
.panel::before {
  content: '';
  position: absolute;
  left: -1px;
  top: -1px;
  width: 14px;
  height: 3px;
  background: var(--c-accent);
}
.panel.ac-primary::before { background: var(--c-primary); width: 100%; }
.panel.ac-warn::before { background: var(--c-warn); width: 100%; }
.panel.ac-danger::before { background: var(--c-danger); width: 100%; }
.panel.ac-ok::before { background: var(--c-ok); width: 100%; }
.hd {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 42px;
  padding: 0 12px 0 14px;
  border-bottom: var(--bw) solid var(--c-border);
}
.hd h3 { font-size: var(--fs-md); font-weight: 700; display: flex; align-items: baseline; gap: 8px; }
.hd h3 .code-label { font-size: 10px; font-weight: 500; }
.ic { color: var(--c-text-3); flex: none; }
.bd { padding: 14px; flex: 1; min-height: 0; }
.bd.flush { padding: 0; }
.ft { padding: 8px 14px; border-top: var(--bw) solid var(--c-border); background: var(--c-surface-2); font-size: var(--fs-sm); color: var(--c-text-3); }
</style>
