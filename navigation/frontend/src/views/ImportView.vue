<script setup lang="ts">
import { computed, ref } from 'vue'
import { apiClient } from '@/api'
import ConflictTable from '@/components/ConflictTable.vue'
import ImportSummary from '@/components/ImportSummary.vue'
import type { ConflictChoice, ImportApplyResult, ImportPreview } from '@/types'

const batch = ref<ImportPreview | null>(null)
const choices = ref<ConflictChoice[]>([])
const previewing = ref(false)
const applying = ref(false)
const error = ref('')
const result = ref<ImportApplyResult | null>(null)
const conflictItems = computed(() => batch.value?.items.filter(
  ({ status }) => status === 'conflict' || status === 'suggested_move',
) ?? [])

function message(caught: unknown, fallback: string): string {
  return caught instanceof Error ? caught.message : fallback
}

async function previewFile(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0]
  batch.value = null
  choices.value = []
  result.value = null
  error.value = ''
  if (!file) return
  previewing.value = true
  try {
    const preview = await apiClient.previewImport(file)
    batch.value = preview
    choices.value = preview.items
      .filter(({ status }) => status === 'conflict' || status === 'suggested_move')
      .map(({ id }) => ({ item_id: id, overwrite_title: false, overwrite_folder: false, overwrite_notes: false }))
  } catch (caught) {
    error.value = message(caught, '无法生成导入预览')
  } finally {
    previewing.value = false
  }
}

async function applyImport(): Promise<void> {
  if (!batch.value || applying.value) return
  applying.value = true
  error.value = ''
  try {
    result.value = await apiClient.applyImport(batch.value.id, { overrides: choices.value })
  } catch (caught) {
    error.value = message(caught, '无法应用导入')
  } finally {
    applying.value = false
  }
}
</script>

<template>
  <main class="management-page">
    <nav class="management-nav" aria-label="数据管理">
      <RouterLink to="/">返回书签</RouterLink><RouterLink to="/backups">导出与备份</RouterLink>
    </nav>
    <header class="page-heading"><p class="eyebrow">SAFE IMPORT</p><h1>导入书签</h1><p>先生成预览，确认冲突选项后再写入。</p></header>
    <section class="management-card upload-card">
      <label for="import-file"><strong>选择 Netscape 书签 HTML</strong><span>浏览器导出的 HTML 文件，上限由服务器设置。</span></label>
      <input id="import-file" data-test="import-file" type="file" accept="text/html,.html,.htm" :disabled="previewing || applying" @change="previewFile" />
      <p class="safety-note">安全默认：所有冲突覆盖选项均为关闭；不会根据导入文件缺失项删除服务器书签。</p>
      <p class="safety-note">如果之后再将此 HTML 导入浏览器，浏览器通常会追加而不是替换现有书签，可能产生重复项。</p>
    </section>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <template v-if="batch">
      <ImportSummary :summary="batch.summary" />
      <ConflictTable v-model="choices" :items="conflictItems" />
    </template>
    <section class="apply-bar">
      <div>
        <strong>{{ result ? '导入已完成' : '准备应用预览' }}</strong>
        <p v-if="result">已创建安全备份 #{{ result.backup_id }}，共 {{ result.unique_bookmarks }} 个唯一书签。</p>
        <p v-else>仅会写入预览内容与你明确开启的覆盖项。</p>
      </div>
      <button data-test="apply-import" type="button" class="primary-button" :disabled="!batch || previewing || applying || Boolean(result)" @click="applyImport">
        {{ applying ? '正在导入…' : '应用导入' }}
      </button>
    </section>
  </main>
</template>
