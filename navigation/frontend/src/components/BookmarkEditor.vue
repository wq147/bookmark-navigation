<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import type { Bookmark, BookmarkInput, Folder } from '@/types'

const props = defineProps<{
  bookmark: Bookmark | null
  folderId: number | null
  folders: Folder[]
  error?: string
}>()
const emit = defineEmits<{
  save: [bookmark: Bookmark | BookmarkInput]
  delete: [bookmark: Bookmark]
  close: []
}>()

const form = reactive({ title: '', url: '', folder_id: 0, notes: '' })
const isExisting = computed(() => props.bookmark !== null)

watch(
  () => [props.bookmark, props.folderId] as const,
  () => {
    form.title = props.bookmark?.title ?? ''
    form.url = props.bookmark?.url ?? ''
    form.folder_id = props.bookmark?.folder_id ?? props.folderId ?? props.folders[0]?.id ?? 0
    form.notes = props.bookmark?.notes ?? ''
  },
  { immediate: true },
)

function submit(): void {
  const input: BookmarkInput = { ...form }
  emit('save', props.bookmark ? { ...props.bookmark, ...input } : input)
}
</script>

<template>
  <aside class="editor" aria-label="书签编辑器">
    <div class="panel-heading">
      <div>
        <p class="eyebrow">DETAILS</p>
        <h2>{{ isExisting ? '编辑书签' : '新建书签' }}</h2>
      </div>
      <button type="button" class="icon-button mobile-only" aria-label="关闭编辑器" @click="emit('close')">×</button>
    </div>
    <form @submit.prevent="submit">
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <label>
        <span>标题</span>
        <input v-model="form.title" name="title" required maxlength="1024" />
      </label>
      <label>
        <span>网址</span>
        <input v-model="form.url" name="url" type="url" required />
      </label>
      <label>
        <span>文件夹</span>
        <select v-model="form.folder_id" name="folder_id" required>
          <option v-for="folder in folders" :key="folder.id" :value="folder.id">
            {{ folder.base_name }}
          </option>
        </select>
      </label>
      <label>
        <span>备注</span>
        <textarea v-model="form.notes" name="notes" rows="7"></textarea>
      </label>
      <div class="editor-actions">
        <button type="submit" class="primary-button">保存书签</button>
        <button
          v-if="bookmark"
          type="button"
          class="danger-button"
          @click="emit('delete', bookmark)"
        >
          删除
        </button>
      </div>
    </form>
  </aside>
</template>
