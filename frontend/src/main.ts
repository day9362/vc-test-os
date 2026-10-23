import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import { vTip } from './directives/tip'
import './styles/tokens.css'
import './styles/base.css'

createApp(App).use(createPinia()).use(router).directive('tip', vTip).mount('#app')
