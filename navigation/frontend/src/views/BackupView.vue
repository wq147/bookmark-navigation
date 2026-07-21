<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiClient, clearCsrfToken } from '@/api'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import type { Backup } from '@/types'
import { clearCurrentUser, currentUser } from '@/session'

const router = useRouter()

const backups = ref<Backup[]>([])
const loading = ref(true)
const exporting = ref<'bookmarks.html' | 'backup.json' | null>(null)
const restoring = ref(false)
const selectedBackup = ref<Backup | null>(null)
const error = ref('')
const notice = ref('')

function message(caught: unknown, fallback: string): string {
  return caught instanceof Error ? caught.message : fallback
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

async function loadBackups(): Promise<void> {
  if (!currentUser.value?.is_admin) {
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  try {
    backups.value = await apiClient.backups()
  } catch (caught) {
    error.value = message(caught, '无法加载备份')
  } finally {
    loading.value = false
  }
}

async function exportData(kind: 'bookmarks.html' | 'backup.json'): Promise<void> {
  if (exporting.value) return
  exporting.value = kind
  error.value = ''
  try {
    await apiClient.downloadExport(kind)
  } catch (caught) {
    error.value = message(caught, '无法导出数据')
  } finally {
    exporting.value = null
  }
}

async function restore(): Promise<void> {
  if (!selectedBackup.value || restoring.value) return
  restoring.value = true
  error.value = ''
  notice.value = ''
  try {
    const restoredId = selectedBackup.value.id
    await apiClient.restoreBackup(restoredId)
    selectedBackup.value = null
    clearCsrfToken()
    clearCurrentUser()
    await router.replace({ name: 'login', query: { restored: '1' } })
  } catch (caught) {
    error.value = message(caught, '无法还原备份')
  } finally {
    restoring.value = false
  }
}

onMounted(() => void loadBackups())
</script>

<template>
  <main class="management-page">
    <nav class="management-nav" aria-label="数据管理">
      <RouterLink to="/">返回书签</RouterLink><RouterLink to="/import">导入书签</RouterLink>
    </nav>
    <header class="page-heading"><p class="eyebrow">RECOVERY</p><h1>导出与备份</h1><p>导出便携数据，或从服务器快照还原。</p></header>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="success-note" role="status">{{ notice }}</p>

    <section class="management-card export-card">
      <div><p class="eyebrow">EXPORT</p><h2>下载数据</h2></div>
      <div class="export-actions">
        <button data-test="export-html" type="button" class="primary-button" :disabled="Boolean(exporting)" @click="exportData('bookmarks.html')">导出浏览器 HTML</button>
        <button data-test="export-json" type="button" class="ghost-button bordered" :disabled="Boolean(exporting)" @click="exportData('backup.json')">导出完整 JSON</button>
      </div>
      <p class="safety-note">HTML 适合导入浏览器，但浏览器通常会追加导入内容，可能产生重复项。JSON 用于保存完整元数据。</p>
    </section>

    <section v-if="currentUser?.is_admin" class="management-card backup-card">
      <div class="section-heading"><div><p class="eyebrow">SERVER SNAPSHOTS</p><h2>可还原备份</h2></div><span class="count-pill">{{ backups.length }}</span></div>
      <p v-if="loading" role="status">正在加载备份…</p>
      <p v-else-if="!backups.length" class="empty-state">暂无可还原备份。导入和递归删除前会自动创建快照。</p>
      <ul v-else class="backup-list">
        <li v-for="backup in backups" :key="backup.id">
          <div><strong>#{{ backup.id }} · {{ backup.filename }}</strong><span>{{ formatDate(backup.created_at) }}</span><small>SHA-256 {{ backup.checksum }}</small></div>
          <button :data-test="`restore-${backup.id}`" type="button" class="danger-button" @click="selectedBackup = backup">还原</button>
        </li>
      </ul>
    </section>

    <ConfirmDialog
      :open="Boolean(selectedBackup)"
      title="还原服务器备份"
      :phrase="selectedBackup ? `还原备份 ${selectedBackup.id}` : ''"
      message="整库还原会影响所有用户，替换全部账号、书签和文件夹，并注销所有会话。服务器会先保存当前状态以便回退。"
      confirm-label="还原备份"
      :busy="restoring"
      @cancel="selectedBackup = null"
      @confirm="restore"
    />
  </main>
</template>
