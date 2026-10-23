<script setup lang="ts">
import { computed } from 'vue'
import { CircleAlert, CircleCheck, CircleDashed, CirclePause, Crosshair, WifiOff, Wifi, CircleX, Loader, Archive, PencilLine, ShieldCheck, Hourglass, Wrench, Power } from 'lucide-vue-next'

/** 状态始终同时用「图标 + 文字 + 颜色」表达，避免只靠颜色区分（色弱、强光车间屏幕） */
const MAP: Record<string, { text: string; cls: string; icon: any }> = {
  running: { text: '运行中', cls: 'ok', icon: Loader },
  idle: { text: '待机', cls: '', icon: CirclePause },
  alarm: { text: '告警', cls: 'danger', icon: CircleAlert },
  offline: { text: '离线', cls: 'danger solid', icon: WifiOff },
  calibrating: { text: '校准中', cls: 'info', icon: Crosshair },
  draft: { text: '草稿', cls: '', icon: PencilLine },
  validating: { text: '校验中', cls: 'info', icon: CircleDashed },
  review: { text: '待审批', cls: 'warn', icon: Hourglass },
  approved: { text: '已批准', cls: 'primary', icon: ShieldCheck },
  archived: { text: '已归档', cls: '', icon: Archive },
  rejected: { text: '已驳回', cls: 'danger', icon: CircleX },
  done: { text: '已完成', cls: 'ok', icon: CircleCheck },
  hold: { text: '冻结待判', cls: 'warn', icon: CirclePause },
  pass: { text: '通过', cls: 'ok', icon: CircleCheck },
  fail: { text: '失败', cls: 'danger', icon: CircleX },
  warn: { text: '警告', cls: 'warn', icon: CircleAlert },
  stopped: { text: '已停止', cls: 'warn', icon: CirclePause },
  // MachineStatus
  READY: { text: '就绪', cls: 'ok', icon: CircleCheck },
  FAULT: { text: '故障', cls: 'danger solid', icon: CircleX },
  MAINTENANCE: { text: '维修', cls: 'info', icon: Wrench },
  OFFLINE: { text: '关机', cls: '', icon: Power },
  STOPPED: { text: '已停机', cls: '', icon: Power },
  CREATED: { text: '已创建', cls: '', icon: CircleDashed },
  STARTING: { text: '上电中', cls: 'info', icon: Loader },
  INITIALIZING: { text: '初始化', cls: 'info', icon: Loader },
  // CommStatus
  ONLINE: { text: '在线', cls: 'ok', icon: Wifi },
  DEGRADED: { text: '降级', cls: 'warn', icon: Wifi },
  DISCONNECTED: { text: '通信断开', cls: 'danger solid', icon: WifiOff },
  // RunStatus
  RUNNING: { text: '进行中', cls: 'info', icon: Loader },
  COMPLETED: { text: '完成', cls: 'ok', icon: CircleCheck },
  ABORTED: { text: '中止', cls: 'warn', icon: CirclePause },
  // 判定
  PASS: { text: '合格', cls: 'ok', icon: CircleCheck },
  NG: { text: '不合格', cls: 'danger', icon: CircleX },
}

const props = defineProps<{ status: string; text?: string }>()
const m = computed(() => MAP[props.status] ?? { text: props.status, cls: '', icon: CircleDashed })
</script>

<template>
  <span class="tag" :class="m.cls">
    <component :is="m.icon" :size="12" :class="{ spin: ['running', 'validating', 'RUNNING', 'STARTING', 'INITIALIZING'].includes(status) }" />
    {{ text ?? m.text }}
  </span>
</template>

<style scoped>
.spin { animation: spin 2.4s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
