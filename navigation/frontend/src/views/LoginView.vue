<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, apiClient } from '@/api'
import { refreshCurrentUser } from '@/session'

const router = useRouter()
const route = useRoute()
const username = ref('')
const password = ref('')
const error = ref('')
const submitting = ref(false)

async function login(): Promise<void> {
  error.value = ''
  submitting.value = true
  try {
    await apiClient.login(username.value, password.value)
    const user = await refreshCurrentUser()
    await router.replace(user.must_change_password ? '/change-password' : '/')
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : '登录失败，请重试。'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-card" aria-labelledby="login-title">
      <div class="login-brand"><span class="brand-mark">N</span></div>
      <p class="eyebrow">PRIVATE LIBRARY</p>
      <h1 id="login-title">欢迎回来</h1>
      <p class="login-intro">登录后继续整理你的私人书签。</p>
      <p v-if="route.query.restored === '1'" class="success-note" role="status">备份还原完成，所有会话已注销，请重新登录。</p>
      <form @submit.prevent="login">
        <label>
          <span>用户名</span>
          <input v-model="username" name="username" autocomplete="username" required autofocus />
        </label>
        <label>
          <span>密码</span>
          <input v-model="password" name="password" type="password" autocomplete="current-password" required />
        </label>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <button class="primary-button login-button" type="submit" :disabled="submitting">
          {{ submitting ? '正在登录…' : '登录' }}
        </button>
      </form>
    </section>
  </main>
</template>
