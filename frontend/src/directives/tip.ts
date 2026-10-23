import type { Directive } from 'vue'

/**
 * v-tip="'文字'" 或 v-tip="{ text, kbd, placement }"
 * 图标按钮统一使用：鼠标悬停 / 键盘聚焦都会出现，同时写入 aria-label
 */
type TipValue = string | { text: string; kbd?: string; placement?: 'top' | 'bottom' | 'right' | 'left' }

let el: HTMLDivElement | null = null
let showTimer: number | undefined

function ensure() {
  if (el) return el
  el = document.createElement('div')
  el.className = 'v-tip'
  el.setAttribute('role', 'tooltip')
  document.body.appendChild(el)
  return el
}

function norm(v: TipValue) {
  return typeof v === 'string' ? { text: v, placement: 'bottom' as const } : { placement: 'bottom' as const, ...v }
}

function show(target: HTMLElement) {
  const v = norm((target as any).__tip as TipValue)
  if (!v.text) return
  window.clearTimeout(showTimer)
  showTimer = window.setTimeout(() => {
    if (!target.isConnected) return
    const tip = ensure()
    tip.innerHTML = ''
    tip.append(document.createTextNode(v.text))
    if (v.kbd) {
      const k = document.createElement('span')
      k.className = 'v-tip-kbd'
      k.textContent = v.kbd
      tip.append(k)
    }
    tip.style.opacity = '0'
    tip.style.display = 'flex'
    const r = target.getBoundingClientRect()
    const t = tip.getBoundingClientRect()
    const gap = 6
    let x = r.left + r.width / 2 - t.width / 2
    let y = r.bottom + gap
    if (v.placement === 'top') y = r.top - t.height - gap
    if (v.placement === 'right') { x = r.right + gap; y = r.top + r.height / 2 - t.height / 2 }
    if (v.placement === 'left') { x = r.left - t.width - gap; y = r.top + r.height / 2 - t.height / 2 }
    x = Math.max(6, Math.min(window.innerWidth - t.width - 6, x))
    if (y + t.height > window.innerHeight - 4) y = r.top - t.height - gap
    tip.style.left = `${x}px`
    tip.style.top = `${y}px`
    tip.style.opacity = '1'
  }, 280)
}

function hide() {
  window.clearTimeout(showTimer)
  if (el) el.style.display = 'none'
}

export const vTip: Directive<HTMLElement, TipValue> = {
  mounted(target, binding) {
    ;(target as any).__tip = binding.value
    const { text } = norm(binding.value)
    if (text && !target.getAttribute('aria-label')) target.setAttribute('aria-label', text)
    target.addEventListener('mouseenter', () => show(target))
    target.addEventListener('focus', () => target.matches(':focus-visible') && show(target))
    target.addEventListener('mouseleave', hide)
    target.addEventListener('blur', hide)
    target.addEventListener('mousedown', hide)
  },
  updated(target, binding) {
    ;(target as any).__tip = binding.value
    const { text } = norm(binding.value)
    if (text) target.setAttribute('aria-label', text)
    else target.removeAttribute('aria-label')
  },
  beforeUnmount: hide,
}
