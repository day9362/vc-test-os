<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ShieldAlert, X } from 'lucide-vue-next'
import { useAppStore } from '@/stores/app'

const app = useAppStore()
const s = computed(() => app.confirmState)
const typed = ref('')
const checks = ref<boolean[]>([])
const box = ref<HTMLElement>()

watch(s, async (v) => {
  if (!v) return
  typed.value = ''
  checks.value = (v.checklist ?? []).map(() => false)
  await nextTick()
  ;(box.value?.querySelector('input, button.btn-primary, button.btn-danger') as HTMLElement | null)?.focus()
})

const ready = computed(() => {
  if (!s.value) return false
  if (s.value.typeToConfirm && typed.value.trim() !== s.value.typeToConfirm) return false
  return checks.value.every(Boolean)
})

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') app.settleConfirm(false)
  if (e.key === 'Enter' && ready.value && (e.target as HTMLElement).tagName !== 'BUTTON') app.settleConfirm(true)
}
</script>

<template>
  <Transition name="fade">
    <div v-if="s" class="mask" @keydown="onKey">
      <div ref="box" class="dlg" :class="{ danger: s.danger }" role="alertdialog" aria-modal="true" :aria-label="s.title">
        <div v-if="s.danger" class="hazard strip" aria-hidden="true" />
        <div class="hd">
          <ShieldAlert :size="20" :class="s.danger ? 't-danger' : 't-primary'" />
          <h2 class="grow">{{ s.title }}</h2>
          <button class="btn btn-ghost btn-icon btn-sm" v-tip="'取消'" @click="app.settleConfirm(false)"><X :size="16" /></button>
        </div>
        <div class="bd">
          <p v-if="s.desc" class="text-2">{{ s.desc }}</p>
          <ul v-if="s.checklist?.length" class="checks">
            <li v-for="(c, i) in s.checklist" :key="i">
              <label>
                <input v-model="checks[i]" type="checkbox" />
                <span>{{ c }}</span>
              </label>
            </li>
          </ul>
          <div v-if="s.typeToConfirm" class="field">
            <label>请输入 <b class="mono">{{ s.typeToConfirm }}</b> 以确认</label>
            <input v-model="typed" class="input mono" :placeholder="s.typeToConfirm" autocomplete="off" spellcheck="false" />
          </div>
        </div>
        <div class="ft">
          <button class="btn" @click="app.settleConfirm(false)">取消</button>
          <button class="btn" :class="s.danger ? 'btn-danger' : 'btn-primary'" :disabled="!ready" @click="app.settleConfirm(true)">
            {{ s.confirmText ?? '确认' }}
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.mask { position: fixed; inset: 0; z-index: 95; background: rgba(12, 16, 20, 0.4); display: grid; place-items: center; padding: 16px; }
.dlg { position: relative; width: min(480px, 100%); background: var(--c-surface); border: var(--bw) solid var(--c-border-strong); box-shadow: var(--shadow-pop); }
.strip { height: 6px; }
.hd { display: flex; align-items: center; gap: 10px; padding: 14px 14px 10px 16px; }
.hd h2 { font-size: var(--fs-lg); }
.bd { padding: 0 16px 16px; display: flex; flex-direction: column; gap: 12px; }
.checks { list-style: none; margin: 0; padding: 10px 12px; background: var(--c-surface-2); border: var(--bw) solid var(--c-border); display: flex; flex-direction: column; gap: 8px; }
.checks label { display: flex; gap: 8px; align-items: flex-start; cursor: pointer; font-size: var(--fs-sm); }
.checks input { margin-top: 3px; accent-color: var(--c-primary); }
.ft { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 16px; border-top: var(--bw) solid var(--c-border); background: var(--c-surface-2); }
.fade-enter-active, .fade-leave-active { transition: opacity 120ms var(--ease); }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
