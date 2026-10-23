import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { currentUser, type Me } from '@/api/http'

export type Role = 'process' | 'test' | 'quality' | 'admin'
export const ROLES: { id: Role; name: string; desc: string }[] = [
  { id: 'process', name: '工艺工程师', desc: '工艺优化 / 方案制定' },
  { id: 'test', name: '测试工程师', desc: '测试执行 / 结果分析' },
  { id: 'quality', name: '质量工程师', desc: '质量监控 / 问题追溯' },
  { id: 'admin', name: '产线管理', desc: '看板 / 报表查看' },
]

export interface Toast {
  id: number
  kind: 'ok' | 'info' | 'warn' | 'danger'
  title: string
  desc?: string
  action?: { label: string; run: () => void }
}

export interface ConfirmOptions {
  title: string
  desc?: string
  danger?: boolean
  confirmText?: string
  /** 需要用户输入此文本才能确认，用于下发、回滚等高风险操作 */
  typeToConfirm?: string
  checklist?: string[]
}

export const useAppStore = defineStore('app', () => {
  const navCollapsed = ref(localStorage.getItem('vc-nav') === '1')
  watch(navCollapsed, (v) => localStorage.setItem('vc-nav', v ? '1' : '0'))

  const role = ref<Role>((localStorage.getItem('vc-role') as Role) || 'test')
  watch(role, (v) => localStorage.setItem('vc-role', v))
  const session = ref<Me | null>(currentUser())
  function setSession(me: Me | null) {
    session.value = me
    if (me) role.value = me.role
  }

  const paletteOpen = ref(false)

  const toasts = ref<Toast[]>([])
  let tid = 0
  function toast(t: Omit<Toast, 'id'>, ms = 4200) {
    const id = ++tid
    toasts.value.push({ ...t, id })
    window.setTimeout(() => dismiss(id), ms)
  }
  function dismiss(id: number) {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }

  const confirmState = ref<(ConfirmOptions & { resolve: (v: boolean) => void }) | null>(null)
  function confirm(opts: ConfirmOptions) {
    return new Promise<boolean>((resolve) => {
      confirmState.value = { ...opts, resolve }
    })
  }
  function settleConfirm(v: boolean) {
    confirmState.value?.resolve(v)
    confirmState.value = null
  }

  return { navCollapsed, role, session, setSession, paletteOpen, toasts, toast, dismiss, confirmState, confirm, settleConfirm }
})
