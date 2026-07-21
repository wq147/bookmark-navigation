<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { apiClient } from '@/api'
import AppToolbar from '@/components/AppToolbar.vue'
import BookmarkEditor from '@/components/BookmarkEditor.vue'
import BookmarkList from '@/components/BookmarkList.vue'
import FolderTree from '@/components/FolderTree.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useBookmarksStore } from '@/stores/bookmarks'
import type { Bookmark, BookmarkInput, Folder, FolderCreateInput, FolderUpdateInput } from '@/types'
import { clearCurrentUser, currentUser, refreshCurrentUser } from '@/session'

const router = useRouter()
const store = useBookmarksStore()
const mode = ref<'list' | 'card'>('list')
const query = ref('')
const results = ref<Bookmark[]>([])
const activeResult = ref(-1)
const searchError = ref('')
const mobile = ref(window.innerWidth < 800)
const folderDrawerOpen = ref(false)
const editorOpen = ref(false)
const folderDialog = ref<HTMLElement | null>(null)
const editorDialog = ref<HTMLElement | null>(null)
const folderToDelete = ref<Folder | null>(null)
const deletingFolder = ref(false)
let folderFocusOrigin: HTMLElement | null = null
let editorFocusOrigin: HTMLElement | null = null
let searchTimer: ReturnType<typeof setTimeout> | undefined
let searchGeneration = 0

const heading = computed(() => store.selectedFolder?.base_name ?? '书签')
const backgroundInert = computed(() => mobile.value && (folderDrawerOpen.value || editorOpen.value))
const activeResultId = computed(() => {
  const result = results.value[activeResult.value]
  return result ? `search-result-${result.id}` : undefined
})

function updateViewport(): void {
  mobile.value = window.innerWidth < 800
  if (!mobile.value) {
    folderDrawerOpen.value = false
    editorOpen.value = false
  }
}

function openBookmark(bookmark: Bookmark): void {
  window.open(bookmark.url, '_blank', 'noopener')
}

function handleSearchKey(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    query.value = ''
    return
  }
  if (!results.value.length) return
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    activeResult.value = (activeResult.value + 1) % results.value.length
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    activeResult.value = (activeResult.value - 1 + results.value.length) % results.value.length
  } else if (event.key === 'Enter') {
    event.preventDefault()
    openBookmark(results.value[Math.max(activeResult.value, 0)])
  }
}

watch(query, (value) => {
  const generation = ++searchGeneration
  clearTimeout(searchTimer)
  activeResult.value = -1
  searchError.value = ''
  if (!value.trim()) {
    results.value = []
    return
  }
  searchTimer = setTimeout(async () => {
    try {
      const response = await apiClient.search({ q: value.trim(), limit: 50, offset: 0 })
      if (generation === searchGeneration) results.value = response.items
    } catch (caught) {
      if (generation !== searchGeneration) return
      results.value = []
      searchError.value = caught instanceof Error ? caught.message : '搜索失败，请重试。'
    }
  }, 250)
})

async function selectFolder(id: number): Promise<void> {
  try {
    await store.selectFolder(id)
    closeFolderDrawer()
  } catch {
    // The store exposes the API message in the live alert.
  }
}

function selectBookmark(bookmark: Bookmark): void {
  store.selectBookmark(bookmark)
  if (mobile.value) void openEditor()
}

async function openFolderDrawer(): Promise<void> {
  folderFocusOrigin = document.activeElement instanceof HTMLElement ? document.activeElement : null
  folderDrawerOpen.value = true
  await nextTick()
  folderDialog.value?.querySelector<HTMLElement>('.drawer-close')?.focus()
}

function closeFolderDrawer(): void {
  folderDrawerOpen.value = false
  const origin = folderFocusOrigin
  folderFocusOrigin = null
  void nextTick(() => origin?.focus())
}

async function openEditor(): Promise<void> {
  editorFocusOrigin = document.activeElement instanceof HTMLElement ? document.activeElement : null
  editorOpen.value = true
  await nextTick()
  editorDialog.value?.querySelector<HTMLElement>('[aria-label="关闭编辑器"]')?.focus()
}

function closeEditor(): void {
  editorOpen.value = false
  const origin = editorFocusOrigin
  editorFocusOrigin = null
  void nextTick(() => origin?.focus())
}

function createBookmark(): void {
  store.selectBookmark(null)
  if (mobile.value) void openEditor()
}

function dialogKeydown(event: KeyboardEvent, kind: 'folder' | 'editor'): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    kind === 'folder' ? closeFolderDrawer() : closeEditor()
    return
  }
  if (event.key !== 'Tab') return
  const dialog = kind === 'folder' ? folderDialog.value : editorDialog.value
  const focusable = dialog
    ? Array.from(dialog.querySelectorAll<HTMLElement>(
      'button:not([disabled]):not([tabindex="-1"]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ))
    : []
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

async function saveBookmark(bookmark: Bookmark | BookmarkInput): Promise<void> {
  try {
    await store.saveBookmark(bookmark)
    if (mobile.value) closeEditor()
  } catch {
    // Keep the editor open so its live alert remains visible.
  }
}

async function deleteBookmark(bookmark: Bookmark): Promise<void> {
  if (window.confirm(`删除“${bookmark.title}”？`)) {
    try {
      await store.removeBookmark(bookmark)
      closeEditor()
    } catch {
      // Keep the editor open so its live alert remains visible.
    }
  }
}

async function deleteFolder(): Promise<void> {
  if (!folderToDelete.value || deletingFolder.value) return
  deletingFolder.value = true
  try {
    await store.removeFolderRecursive(folderToDelete.value)
    folderToDelete.value = null
    closeFolderDrawer()
  } catch {
    // The folder panel exposes the API message.
  } finally {
    deletingFolder.value = false
  }
}

async function createFolder(payload: FolderCreateInput): Promise<void> {
  try { await store.createFolder(payload) } catch { /* live error is in the folder panel */ }
}

async function updateFolder(id: number, payload: FolderUpdateInput): Promise<void> {
  try { await store.updateFolder(id, payload) } catch { /* live error is in the folder panel */ }
}

async function requestFolderDelete(folder: Folder, recursive: boolean): Promise<void> {
  if (recursive) {
    folderToDelete.value = folder
    return
  }
  if (window.confirm(`删除空文件夹“${folder.base_name}”？`)) {
    try { await store.removeFolder(folder) } catch { /* live error is in the folder panel */ }
  }
}

async function logout(): Promise<void> {
  await apiClient.logout()
  clearCurrentUser()
  await router.replace('/login')
}

onMounted(async () => {
  window.addEventListener('resize', updateViewport)
  if (!currentUser.value) await refreshCurrentUser()
  await store.initialize()
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewport)
  clearTimeout(searchTimer)
})
</script>

<template>
  <div class="workspace-shell">
    <AppToolbar
      :username="currentUser?.username ?? ''"
      :is-admin="currentUser?.is_admin ?? false"
      :inert="backgroundInert ? true : undefined"
      v-model:query="query"
      :mode="mode"
      :result-count="results.length"
      :active-result="activeResult"
      :active-result-id="activeResultId"
      :error="searchError"
      @keydown="handleSearchKey"
      @mode="mode = $event"
      @folders="openFolderDrawer"
      @create="createBookmark"
      @logout="logout"
    >
      <template #results>
        <button
          v-for="(result, index) in results"
          :key="result.id"
          :data-test="`result-${index}`"
          :id="`search-result-${result.id}`"
          type="button"
          role="option"
          :aria-selected="activeResult === index"
          :class="{ active: activeResult === index }"
          @mouseenter="activeResult = index"
          @click="openBookmark(result)"
        >
          <strong>{{ result.title }}</strong><span>{{ result.domain }}</span>
        </button>
      </template>
    </AppToolbar>

    <div class="workspace-grid">
      <aside
        ref="folderDialog"
        data-test="folder-drawer"
        class="folder-panel"
        :class="{ 'drawer-open': folderDrawerOpen }"
        :aria-hidden="mobile && !folderDrawerOpen"
        :role="mobile ? 'dialog' : undefined"
        :aria-modal="mobile ? 'true' : undefined"
        aria-label="文件夹"
        :inert="editorOpen ? true : undefined"
        @keydown="dialogKeydown($event, 'folder')"
      >
        <button tabindex="-1" class="drawer-scrim mobile-only" aria-label="关闭文件夹" @click="closeFolderDrawer"></button>
        <div class="drawer-surface">
          <button type="button" class="icon-button drawer-close mobile-only" aria-label="关闭文件夹" @click="closeFolderDrawer">×</button>
          <FolderTree
            v-if="currentUser"
            :folders="store.folders"
            :selected-id="store.selectedFolderId"
            :user-id="currentUser.id"
            :error="store.error"
            @select="selectFolder"
            @create="createFolder"
            @update="updateFolder"
            @delete="requestFolderDelete"
          />
        </div>
      </aside>

      <main class="content-panel" :inert="backgroundInert ? true : undefined">
        <div class="content-heading">
          <div>
            <p class="eyebrow">CURRENT FOLDER</p>
            <h1>{{ heading }}</h1>
          </div>
          <span>{{ store.bookmarks.length }} 个书签</span>
        </div>
        <p v-if="store.error" class="form-error" role="alert">{{ store.error }}</p>
        <BookmarkList
          :bookmarks="store.bookmarks"
          :selected-id="store.selectedBookmark?.id ?? null"
          :mode="mode"
          :loading="store.loading"
          @select="selectBookmark"
          @open="openBookmark"
        />
      </main>

      <div
        ref="editorDialog"
        data-test="editor-dialog"
        class="editor-panel"
        :class="{ 'editor-open': editorOpen }"
        :aria-hidden="mobile && !editorOpen"
        :role="mobile ? 'dialog' : undefined"
        :aria-modal="mobile ? 'true' : undefined"
        aria-label="书签编辑器"
        :inert="folderDrawerOpen ? true : undefined"
        @keydown="dialogKeydown($event, 'editor')"
      >
        <div class="editor-scrim mobile-only" @click="closeEditor"></div>
        <BookmarkEditor
          :bookmark="store.selectedBookmark"
          :folder-id="store.selectedFolderId"
          :folders="store.folders"
          :error="store.error"
          @save="saveBookmark"
          @delete="deleteBookmark"
          @close="closeEditor"
        />
      </div>
    </div>
    <ConfirmDialog
      :open="Boolean(folderToDelete)"
      title="递归删除文件夹"
      :phrase="folderToDelete?.base_name ?? ''"
      message="此操作将删除该文件夹、所有子文件夹和其中的书签。服务器会先创建安全备份。"
      confirm-label="递归删除"
      fallback-focus-selector="[data-test='folder-heading']"
      :busy="deletingFolder"
      @cancel="folderToDelete = null"
      @confirm="deleteFolder"
    />
  </div>
</template>
