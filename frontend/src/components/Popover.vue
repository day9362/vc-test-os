<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(defineProps<{ align?: 'left' | 'right'; width?: number }>(), { align: 'right', width: 300 })
const open = defineModel<boolean>('open', { default: false })
const root = ref<HTMLElement>()

function onDoc(e: MouseEvent) {
  if (root.value && !root.value.contains(e.target as Node)) open.value = false
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && open.value) {
    open.value = false
    ;(root.value?.querySelector('[data-trigger] button, [data-trigger]') as HTMLElement | null)?.focus()
  }
}
watch(open, (v) => {
  if (v) {
    setTimeout(() => document.addEventListener('mousedown', onDoc))
    document.addEventListener('keydown', onKey)
  } else {
    document.removeEventListener('mousedown', onDoc)
    document.removeEventListener('keydown', onKey)
  }
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDoc)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="root" class="pop">
    <div data-trigger>
      <slot name="trigger" :open="open" :toggle="() => (open = !open)" />
    </div>
    <Transition name="pop">
      <div v-if="open" class="pop-panel" :class="props.align" :style="{ width: `${props.width}px` }" role="dialog">
        <slot :close="() => (open = false)" />
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.pop { position: relative; display: inline-flex; }
.pop-panel {
  position: absolute;
  top: calc(100% + 6px);
  z-index: 60;
  background: var(--c-surface);
  border: var(--bw) solid var(--c-border-strong);
  border-top: 3px solid var(--c-accent);
  border-radius: var(--radius);
  box-shadow: var(--shadow-pop);
}
.pop-panel.right { right: 0; }
.pop-panel.left { left: 0; }
.pop-enter-active, .pop-leave-active { transition: opacity 120ms var(--ease), transform 120ms var(--ease); }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
