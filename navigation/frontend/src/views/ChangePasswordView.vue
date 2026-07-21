<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiClient } from '@/api'
import { clearCurrentUser, currentUser, refreshCurrentUser } from '@/session'

const router = useRouter()
const currentPassword = ref('')
const newPassword = ref('')
const confirmation = ref('')
const error = ref('')
const submitting = ref(false)
const forced = computed(() => currentUser.value?.must_change_password ?? false)

async function submit(): Promise<void> {
  error.value = ''
  if (newPassword.value !== confirmation.value) {
    error.value = '两次输入的新密码不一致。'
    return
  }
  submitting.value = true
  try {
    await apiClient.changePassword(currentPassword.value, newPassword.value)
    await refreshCurrentUser()
    await router.replace('/')
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '密码修改失败，请重试。'
  } finally {
    submitting.value = false
  }
}

async function logout(): Promise<void> {
  await apiClient.logout()
  clearCurrentUser()
  await router.replace('/login')
}
</script>

<template>
  <main class="login-page">
    <section class="login-card" aria-labelledby="password-title">
      <p class="eyebrow">ACCOUNT SECURITY</p>
      <h1 id="password-title">{{ forced ? '首次登录，请修改密码' : '修改密码' }}</h1>
      <p class="login-intro">新密码至少 12 个字符，且不能与用户名相同。修改后其他设备会自动退出。</p>
      <form @submit.prevent="submit">
        <label>当前密码<input v-model="currentPassword" type="password" autocomplete="current-password" required /></label>
        <label>新密码<input v-model="newPassword" type="password" autocomplete="new-password" minlength="12" required /></label>
        <label>再次输入新密码<input v-model="confirmation" type="password" autocomplete="new-password" minlength="12" required /></label>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <button class="primary-button" type="submit" :disabled="submitting">{{ submitting ? '正在保存…' : '保存新密码' }}</button>
        <button class="ghost-button bordered" type="button" @click="logout">退出登录</button>
      </form>
    </section>
  </main>
</template>
