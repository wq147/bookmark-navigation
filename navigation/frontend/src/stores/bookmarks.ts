import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { apiClient } from '@/api'
import type { Bookmark, BookmarkInput, Folder, FolderCreateInput, FolderUpdateInput } from '@/types'

export const useBookmarksStore = defineStore('bookmarks', () => {
  const folders = ref<Folder[]>([])
  const bookmarks = ref<Bookmark[]>([])
  const selectedFolderId = ref<number | null>(null)
  const selectedBookmark = ref<Bookmark | null>(null)
  const loading = ref(false)
  const error = ref('')
  let folderSelectionGeneration = 0

  const selectedFolder = computed(
    () => folders.value.find((folder) => folder.id === selectedFolderId.value) ?? null,
  )

  function recordError(caught: unknown, fallback: string): void {
    error.value = caught instanceof Error ? caught.message : fallback
  }

  async function initialize(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      folders.value = await apiClient.folders()
      if (selectedFolderId.value === null && folders.value.length) {
        selectedFolderId.value = folders.value[0].id
      }
      if (selectedFolderId.value !== null) await loadBookmarks()
    } catch (caught) {
      recordError(caught, '无法加载书签')
    } finally {
      loading.value = false
    }
  }

  async function loadBookmarks(): Promise<void> {
    error.value = ''
    if (selectedFolderId.value === null) {
      bookmarks.value = []
      return
    }
    try {
      bookmarks.value = await fetchBookmarks(selectedFolderId.value)
    } catch (caught) {
      recordError(caught, '无法加载文件夹')
      throw caught
    }
    if (selectedBookmark.value && !bookmarks.value.some(({ id }) => id === selectedBookmark.value?.id)) {
      selectedBookmark.value = null
    }
  }

  function fetchBookmarks(folderId: number): Promise<Bookmark[]> {
    return apiClient.bookmarks({ folder_id: folderId, limit: 100, offset: 0 })
  }

  async function selectFolder(id: number): Promise<void> {
    const generation = ++folderSelectionGeneration
    error.value = ''
    try {
      const nextBookmarks = await fetchBookmarks(id)
      if (generation !== folderSelectionGeneration) return
      selectedFolderId.value = id
      selectedBookmark.value = null
      bookmarks.value = nextBookmarks
    } catch (caught) {
      if (generation !== folderSelectionGeneration) return
      recordError(caught, '无法加载文件夹')
      throw caught
    }
  }

  function selectBookmark(bookmark: Bookmark | null): void {
    selectedBookmark.value = bookmark
  }

  async function saveBookmark(bookmark: Bookmark | BookmarkInput): Promise<Bookmark> {
    error.value = ''
    const payload: BookmarkInput = {
      title: bookmark.title.trim(),
      url: bookmark.url.trim(),
      folder_id: bookmark.folder_id,
      notes: bookmark.notes,
    }
    let saved: Bookmark
    try {
      saved = 'id' in bookmark
        ? await apiClient.updateBookmark(bookmark.id, payload)
        : await apiClient.createBookmark(payload)
    } catch (caught) {
      recordError(caught, '无法保存书签')
      throw caught
    }
    const index = bookmarks.value.findIndex(({ id }) => id === saved.id)
    if (saved.folder_id !== selectedFolderId.value) {
      bookmarks.value = bookmarks.value.filter(({ id }) => id !== saved.id)
    } else if (index === -1) bookmarks.value.push(saved)
    else bookmarks.value[index] = saved
    selectedBookmark.value = saved
    await refreshFoldersNonFatally()
    return saved
  }

  async function removeBookmark(bookmark: Bookmark): Promise<void> {
    error.value = ''
    try {
      await apiClient.deleteBookmark(bookmark.id)
    } catch (caught) {
      recordError(caught, '无法删除书签')
      throw caught
    }
    bookmarks.value = bookmarks.value.filter(({ id }) => id !== bookmark.id)
    if (selectedBookmark.value?.id === bookmark.id) selectedBookmark.value = null
    await refreshFoldersNonFatally()
  }

  async function removeFolderRecursive(folder: Folder): Promise<number> {
    error.value = ''
    try {
      const { backup_id } = await apiClient.deleteFolderRecursive(folder.id, folder.base_name)
      folderSelectionGeneration += 1
      selectedFolderId.value = null
      selectedBookmark.value = null
      bookmarks.value = []
      await initialize()
      return backup_id
    } catch (caught) {
      recordError(caught, '无法删除文件夹')
      throw caught
    }
  }

  async function refreshFolders(): Promise<void> {
    folders.value = await apiClient.folders()
  }

  async function refreshFoldersNonFatally(): Promise<void> {
    try {
      await refreshFolders()
    } catch {
      // The bookmark mutation is already durable. Counts can refresh on the next action.
    }
  }

  async function createFolder(payload: FolderCreateInput): Promise<Folder> {
    error.value = ''
    try {
      const created = await apiClient.createFolder(payload)
      await refreshFolders()
      return created
    } catch (caught) {
      recordError(caught, '无法创建文件夹')
      throw caught
    }
  }

  async function updateFolder(id: number, payload: FolderUpdateInput): Promise<Folder> {
    error.value = ''
    try {
      const updated = await apiClient.updateFolder(id, payload)
      await refreshFolders()
      return updated
    } catch (caught) {
      recordError(caught, '无法更新文件夹')
      throw caught
    }
  }

  async function removeFolder(folder: Folder): Promise<void> {
    error.value = ''
    try {
      await apiClient.deleteFolder(folder.id)
      if (selectedFolderId.value === folder.id) {
        selectedFolderId.value = null
        selectedBookmark.value = null
        bookmarks.value = []
      }
      await refreshFolders()
    } catch (caught) {
      recordError(caught, '只能直接删除空文件夹')
      throw caught
    }
  }

  return {
    folders,
    bookmarks,
    selectedFolderId,
    selectedFolder,
    selectedBookmark,
    loading,
    error,
    initialize,
    loadBookmarks,
    selectFolder,
    selectBookmark,
    saveBookmark,
    removeBookmark,
    createFolder,
    updateFolder,
    removeFolder,
    removeFolderRecursive,
  }
})
