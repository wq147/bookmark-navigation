<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { apiClient } from '@/api'
import type { AdminAudit, AdminUser } from '@/types'

const users = ref<AdminUser[]>([])
const audit = ref<AdminAudit[]>([])
const username = ref('')
const temporaryPassword = ref('')
const resetPasswords = reactive<Record<number, string>>({})
const error = ref('')
const notice = ref('')
const busy = ref(false)

function message(caught: unknown): string {
  return caught instanceof Error ? caught.message : '操作失败，请重试。'
}

async function load(): Promise<void> {
  try {
    ;[users.value, audit.value] = await Promise.all([apiClient.adminUsers(), apiClient.adminAudit()])
  } catch (caught) {
    error.value = message(caught)
  }
}

async function run(action: () => Promise<unknown>, success: string): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await action()
    notice.value = success
    await load()
  } catch (caught) {
    error.value = message(caught)
  } finally {
    busy.value = false
  }
}

async function createUser(): Promise<void> {
  const createdUsername = username.value.trim()
  await run(
    () => apiClient.createUser(createdUsername, temporaryPassword.value),
    `账号 ${createdUsername} 已创建。请只通过安全渠道交付本次输入的临时密码。`,
  )
  if (!error.value) {
    username.value = ''
    temporaryPassword.value = ''
  }
}

async function resetPassword(user: AdminUser): Promise<void> {
  const password = resetPasswords[user.id] ?? ''
  await run(
    () => apiClient.resetUserPassword(user.id, password),
    `${user.username} 的密码已重置，全部旧会话已注销。`,
  )
  if (!error.value) resetPasswords[user.id] = ''
}

async function deleteUser(user: AdminUser): Promise<void> {
  const confirmation = window.prompt(`永久删除 ${user.username} 及其全部数据。请输入用户名确认：`)
  if (confirmation !== user.username) return
  await run(() => apiClient.deleteUser(user.id, confirmation), `${user.username} 已永久删除，删除前快照已创建。`)
}

onMounted(() => void load())
</script>

<template>
  <main class="management-page">
    <nav class="management-nav" aria-label="用户管理"><RouterLink to="/">返回书签</RouterLink><RouterLink to="/backups">数据管理</RouterLink></nav>
    <header class="page-heading"><p class="eyebrow">ADMINISTRATION</p><h1>用户管理</h1><p>创建和维护独立账号。管理员只能管理账号，不能查看其他用户的书签内容。</p></header>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="success-note" role="status">{{ notice }}</p>

    <section class="management-card">
      <div class="section-heading"><div><p class="eyebrow">NEW ACCOUNT</p><h2>创建普通用户</h2></div></div>
      <form class="inline-form" @submit.prevent="createUser">
        <label>用户名<input v-model="username" required maxlength="255" autocomplete="off" /></label>
        <label>临时密码<input v-model="temporaryPassword" required minlength="12" type="password" autocomplete="new-password" /></label>
        <button class="primary-button" type="submit" :disabled="busy">创建账号</button>
      </form>
    </section>

    <section class="management-card">
      <div class="section-heading"><div><p class="eyebrow">ACCOUNTS</p><h2>账号列表</h2></div><span class="count-pill">{{ users.length }}</span></div>
      <div class="table-scroll">
        <table><thead><tr><th>用户</th><th>状态</th><th>临时密码</th><th>操作</th></tr></thead>
          <tbody><tr v-for="user in users" :key="user.id">
            <td><strong>{{ user.username }}</strong><small>{{ user.is_admin ? '主管理员' : '普通用户' }}</small></td>
            <td>{{ user.is_active ? '启用' : '停用' }}<small v-if="user.must_change_password">下次登录强制改密</small></td>
            <td><input v-if="!user.is_admin" v-model="resetPasswords[user.id]" type="password" minlength="12" placeholder="至少 12 个字符" aria-label="临时密码" /></td>
            <td><div v-if="!user.is_admin" class="row-actions">
              <button type="button" class="ghost-button bordered" :disabled="busy" @click="run(() => apiClient.setUserActive(user.id, !user.is_active), user.is_active ? `${user.username} 已停用。` : `${user.username} 已启用。`)">{{ user.is_active ? '停用' : '启用' }}</button>
              <button type="button" class="ghost-button bordered" :disabled="busy || (resetPasswords[user.id] ?? '').length < 12" @click="resetPassword(user)">重置密码</button>
              <button type="button" class="danger-button" :disabled="busy" @click="deleteUser(user)">永久删除</button>
            </div></td>
          </tr></tbody>
        </table>
      </div>
    </section>

    <section class="management-card">
      <div class="section-heading"><div><p class="eyebrow">AUDIT</p><h2>安全审计</h2></div><span class="count-pill">{{ audit.length }}</span></div>
      <div class="table-scroll"><table><thead><tr><th>时间</th><th>动作</th><th>目标</th><th>结果</th></tr></thead><tbody>
        <tr v-for="entry in audit" :key="entry.id"><td>{{ new Date(entry.created_at).toLocaleString('zh-CN') }}</td><td>{{ entry.action }}</td><td>{{ entry.target_username }}</td><td>{{ entry.result }}</td></tr>
      </tbody></table></div>
    </section>
  </main>
</template>
