<script setup lang="ts">
import { ChevronRight, Database, FileText, Download, ShieldCheck, Sparkles, TriangleAlert, Crosshair } from 'lucide-vue-next'
import { useRouter } from 'vue-router'

/** 业务主链路：方案生成 → 安全校验 → 下发执行 → 数据采集 → 异常分析 → 一致性校准 → 批次报告 */
defineProps<{ stats?: Record<string, { v: string; state?: 'ok' | 'warn' | 'danger' | 'idle' }> }>()
const router = useRouter()

const STEPS = [
  { k: 'gen', name: '方案生成', icon: Sparkles, to: '/plans' },
  { k: 'check', name: '安全校验', icon: ShieldCheck, to: '/plans' },
  { k: 'dispatch', name: '下发执行', icon: Download, to: '/testing' },
  { k: 'collect', name: '数据采集', icon: Database, to: '/settings' },
  { k: 'anomaly', name: '异常分析', icon: TriangleAlert, to: '/agent' },
  { k: 'calib', name: '一致性校准', icon: Crosshair, to: '/devices' },
  { k: 'report', name: '批次报告', icon: FileText, to: '/testing' },
]
</script>

<template>
  <ol class="pipe" aria-label="测试业务链路">
    <template v-for="(s, i) in STEPS" :key="s.k">
      <li>
        <button class="step" :class="stats?.[s.k]?.state ?? 'idle'" @click="router.push(s.to)">
          <span class="no mono">{{ String(i + 1).padStart(2, '0') }}</span>
          <component :is="s.icon" :size="18" class="ic" />
          <span class="nm">{{ s.name }}</span>
          <span v-if="stats?.[s.k]" class="v num">{{ stats[s.k].v }}</span>
        </button>
      </li>
      <li v-if="i < STEPS.length - 1" class="arrow" aria-hidden="true"><ChevronRight :size="16" /></li>
    </template>
  </ol>
</template>

<style scoped>
.pipe { list-style: none; margin: 0; padding: 0; display: flex; align-items: stretch; gap: 2px; overflow-x: auto; }
.pipe > li:not(.arrow) { flex: 1 1 0; min-width: 120px; }
.arrow { display: grid; place-items: center; color: var(--c-text-3); flex: none; }
.step {
  --_c: var(--c-idle);
  width: 100%;
  height: 100%;
  display: grid;
  grid-template-columns: auto 1fr auto;
  grid-template-rows: auto auto;
  align-items: center;
  column-gap: 8px;
  padding: 8px 10px;
  background: var(--c-surface);
  border: var(--bw) solid var(--c-border);
  border-bottom: 3px solid var(--_c);
  text-align: left;
  cursor: pointer;
}
.step:hover { background: var(--c-surface-2); border-color: var(--c-border-strong); border-bottom-color: var(--_c); }
.step.ok { --_c: var(--c-ok); }
.step.warn { --_c: var(--c-warn); }
.step.danger { --_c: var(--c-danger); }
.no { grid-row: 1 / 3; font-size: 10px; color: var(--c-text-3); writing-mode: vertical-rl; letter-spacing: 0.1em; }
.ic { color: var(--_c); }
.nm { font-weight: 600; font-size: var(--fs-sm); white-space: nowrap; }
.v { grid-column: 2 / 4; font-size: var(--fs-xs); color: var(--c-text-2); grid-row: 2; }
.ic { grid-row: 1; grid-column: 3; justify-self: end; }
.nm { grid-row: 1; grid-column: 2; }
</style>
