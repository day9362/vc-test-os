<script setup lang="ts">
import { ref } from 'vue'
import { Check, Palette } from 'lucide-vue-next'
import Popover from './Popover.vue'
import { THEMES, useThemeStore } from '@/stores/theme'

const theme = useThemeStore()
const open = ref(false)
</script>

<template>
  <Popover v-model:open="open" :width="300">
    <template #trigger="{ toggle }">
      <button
        class="btn btn-ghost btn-icon"
        :aria-expanded="open"
        aria-haspopup="dialog"
        v-tip="{ text: '切换主题', kbd: 'Alt+T' }"
        @click="toggle"
      >
        <Palette :size="18" />
      </button>
    </template>

    <div class="hd row-between">
      <span class="code-label">Theme · 界面主题</span>
      <span class="kbd">Alt+T</span>
    </div>
    <ul class="list" role="radiogroup" aria-label="界面主题">
      <li v-for="t in THEMES" :key="t.id">
        <button
          class="item"
          role="radio"
          :aria-checked="theme.theme === t.id"
          @click="theme.set(t.id)"
        >
          <span class="sw" aria-hidden="true">
            <i v-for="c in t.swatches" :key="c" :style="{ background: c }" />
          </span>
          <span class="grow">
            <span class="row gap-4">
              <b>{{ t.name }}</b>
              <span class="code-label">{{ t.en }}</span>
            </span>
            <span class="desc">{{ t.desc }}</span>
          </span>
          <Check v-if="theme.theme === t.id" :size="16" class="t-primary" />
        </button>
      </li>
    </ul>
  </Popover>
</template>

<style scoped>
.hd { padding: 10px 12px; border-bottom: var(--bw) solid var(--c-border); }
.list { list-style: none; margin: 0; padding: 6px; display: flex; flex-direction: column; gap: 4px; }
.item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border: var(--bw) solid transparent;
  border-radius: var(--radius);
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.item:hover { background: var(--c-surface-2); border-color: var(--c-border); }
.item[aria-checked='true'] { border-color: var(--c-primary); background: var(--c-primary-weak); }
.sw { display: grid; grid-template-columns: repeat(2, 14px); grid-template-rows: repeat(2, 14px); border: var(--bw) solid var(--c-border-strong); flex: none; }
.sw i { display: block; }
.desc { display: block; font-size: var(--fs-xs); color: var(--c-text-3); margin-top: 1px; }
</style>
