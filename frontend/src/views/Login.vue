<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listTenants, login, type TenantOption } from '@/api/http'
import { useAppStore } from '@/stores/app'

const router = useRouter()
const app = useAppStore()
const tenants = ref<TenantOption[]>([])
const tenant = ref('line-a')
const username = ref('limingyuan')
const password = ref('')
const error = ref('')
const loading = ref(false)

const samples = [
  { tenant: 'line-a', username: 'limingyuan', name: '李明远 · 测试工程师' },
  { tenant: 'line-a', username: 'admin', name: '产线管理员' },
  { tenant: 'line-b', username: 'wanggong', name: '王工 · B 产线' },
  { tenant: 'lab', username: 'zhougong', name: '周工 · 实验室' },
]

onMounted(async () => {
  try {
    tenants.value = await listTenants()
    if (tenants.value.length && !tenants.value.some((item) => item.tenant_id === tenant.value)) {
      tenant.value = tenants.value[0].tenant_id
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : '无法读取租户'
  }
})

function fill(sample: (typeof samples)[number]) {
  tenant.value = sample.tenant
  username.value = sample.username
  password.value = 'changeme'
  error.value = ''
}

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const me = await login(tenant.value, username.value.trim(), password.value)
    app.setSession(me)
    app.role = me.role
    await router.replace('/overview')
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="gate">
    <form class="card" @submit.prevent="submit">
      <p class="code-label">VC-TestOS</p>
      <h1>登录</h1>
      <p class="muted fs-sm">选择租户后进入对应产线账号。</p>
      <label class="field">
        <span>租户</span>
        <select v-model="tenant" class="select">
          <option v-for="item in tenants" :key="item.tenant_id" :value="item.tenant_id">{{ item.name }}</option>
        </select>
      </label>
      <label class="field">
        <span>用户名</span>
        <input v-model="username" class="input" autocomplete="username" />
      </label>
      <label class="field">
        <span>密码</span>
        <input v-model="password" class="input" type="password" autocomplete="current-password" />
      </label>
      <p v-if="error" class="err">{{ error }}</p>
      <button class="btn btn-primary" type="submit" :disabled="loading || !username || !password">
        {{ loading ? '登录中…' : '登录' }}
      </button>
      <div class="samples">
        <span class="code-label">试用账号 · 密码 changeme</span>
        <button v-for="sample in samples" :key="sample.username" type="button" class="btn btn-ghost btn-sm sample" @click="fill(sample)">
          {{ sample.name }}
        </button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.gate {
  min-height: 100%;
  display: grid;
  place-items: center;
  padding: 32px 16px;
}
.card {
  width: min(420px, 100%);
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 24px;
  background: var(--c-surface);
  border: var(--bw) solid var(--c-border-strong);
}
.card h1 { font-size: 22px; }
.input, .select { width: 100%; }
.err { color: var(--c-danger); font-size: var(--fs-sm); }
.samples { display: flex; flex-direction: column; gap: 6px; padding-top: 8px; border-top: var(--bw) solid var(--c-border); }
.sample { justify-content: flex-start; }
</style>
