<script setup lang="ts">
import { computed, type Component } from 'vue'
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-vue-next'

const props = defineProps<{
  label: string
  value: string | number
  unit?: string
  icon?: Component
  delta?: number
  /** delta 为正是否代表变好（良率↑好，告警↑坏） */
  higherIsBetter?: boolean
  deltaUnit?: string
  sub?: string
  state?: 'ok' | 'warn' | 'danger'
}>()

const trend = computed(() => {
  if (props.delta === undefined) return null
  const good = props.higherIsBetter === false ? props.delta < 0 : props.delta > 0
  const icon = props.delta === 0 ? Minus : props.delta > 0 ? ArrowUpRight : ArrowDownRight
  return { icon, cls: props.delta === 0 ? 'muted' : good ? 't-ok' : 't-danger' }
})
</script>

<template>
  <div class="kpi" :class="state">
    <div class="row-between">
      <span class="lb">{{ label }}</span>
      <component :is="icon" v-if="icon" :size="16" class="muted" />
    </div>
    <div class="val">
      <span class="num">{{ value }}</span>
      <span v-if="unit" class="unit">{{ unit }}</span>
    </div>
    <div class="row-between fs-xs">
      <span class="muted ellipsis">{{ sub }}</span>
      <span v-if="trend" class="row gap-4 num" :class="trend.cls">
        <component :is="trend.icon" :size="12" />{{ Math.abs(delta!) }}{{ deltaUnit }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.kpi {
  --_c: var(--c-border-strong);
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  background: var(--c-surface);
  border: var(--bw) solid var(--c-border);
  box-shadow: inset 0 3px 0 var(--_c);
  min-width: 0;
}
.kpi.ok { --_c: var(--c-ok); }
.kpi.warn { --_c: var(--c-warn); }
.kpi.danger { --_c: var(--c-danger); }
.lb { font-size: var(--fs-sm); color: var(--c-text-2); }
.val { display: flex; align-items: baseline; gap: 4px; }
.val .num { font-size: var(--fs-2xl); font-weight: 700; line-height: 1.15; }
.unit { font-size: var(--fs-sm); color: var(--c-text-3); }
.kpi.danger .val .num { color: var(--c-danger); }
</style>
