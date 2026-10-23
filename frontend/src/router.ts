import { createRouter, createWebHashHistory } from 'vue-router'
import type { Component } from 'vue'
import { Bot, Coins, FileCode2, FlaskConical, LayoutDashboard, Server, Settings2 } from 'lucide-vue-next'

export interface NavItem {
  path: string
  name: string
  title: string
  icon: Component
  group: string
  code: string
  view: () => Promise<unknown>
}

export const NAV: NavItem[] = [
  { path: '/overview', name: 'overview', title: '运行总览', icon: LayoutDashboard, group: '运行', code: 'OVW', view: () => import('./views/Overview.vue') },
  { path: '/testing', name: 'testing', title: '测试执行', icon: FlaskConical, group: '测试', code: 'TST', view: () => import('./views/Testing.vue') },
  { path: '/plans', name: 'plans', title: '测试方案', icon: FileCode2, group: '测试', code: 'PLN', view: () => import('./views/Plans.vue') },
  { path: '/agent', name: 'agent', title: 'AI Agent', icon: Bot, group: '智能', code: 'AGT', view: () => import('./views/Agent.vue') },
  { path: '/tokens', name: 'tokens', title: 'Token 统计', icon: Coins, group: '智能', code: 'TOK', view: () => import('./views/Tokens.vue') },
  { path: '/devices', name: 'devices', title: '设备配置', icon: Server, group: '设备与系统', code: 'DEV', view: () => import('./views/Devices.vue') },
  { path: '/settings', name: 'settings', title: '系统设置', icon: Settings2, group: '设备与系统', code: 'SYS', view: () => import('./views/Settings.vue') },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('./views/Login.vue'), meta: { title: '登录', public: true } },
    { path: '/', redirect: '/overview' },
    ...NAV.map((n) => ({ path: n.path, name: n.name, component: n.view, meta: { title: n.title, code: n.code, group: n.group } })),
    { path: '/report', name: 'report', component: () => import('./views/Report.vue'), meta: { title: '批次报告', code: 'RPT', group: '测试', parent: '/testing' } },
    { path: '/:pathMatch(.*)*', redirect: '/overview' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => {
  const token = sessionStorage.getItem('vc-token')
  if (to.meta.public) return token ? { path: '/overview' } : true
  if (!token) return { path: '/login' }
})

router.afterEach((to) => {
  document.title = `${to.meta.title ?? ''} · VC-TestOS`
})
