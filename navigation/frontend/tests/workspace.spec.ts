import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { apiClient, apiRequest, clearCsrfToken, setCsrfToken } from '@/api'
import FolderTree from '@/components/FolderTree.vue'
import WorkspaceView from '@/views/WorkspaceView.vue'
import { useBookmarksStore } from '@/stores/bookmarks'
import type { Bookmark, Folder } from '@/types'
import { clearCurrentUser } from '@/session'

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    apiClient: {
      me: vi.fn(),
      login: vi.fn(),
      logout: vi.fn(),
      folders: vi.fn(),
      bookmarks: vi.fn(),
      search: vi.fn(),
      createBookmark: vi.fn(),
      updateBookmark: vi.fn(),
      deleteBookmark: vi.fn(),
      createFolder: vi.fn(),
      updateFolder: vi.fn(),
      deleteFolder: vi.fn(),
      deleteFolderRecursive: vi.fn(),
    },
  }
})

const mockedApi = vi.mocked(apiClient)

const folders: Folder[] = [
  { id: 1, parent_id: null, base_name: '工具', position: 1, bookmark_count: 0, created_at: '', updated_at: '' },
  { id: 2, parent_id: 1, base_name: '网络', position: 1, bookmark_count: 1, created_at: '', updated_at: '' },
]

const bookmark: Bookmark = {
  id: 9,
  folder_id: 2,
  title: 'Wireshark',
  url: 'https://www.wireshark.org/',
  normalized_url: 'https://www.wireshark.org',
  notes: '封包分析',
  domain: 'www.wireshark.org',
  position: 1,
  created_at: '',
  updated_at: '',
}

const secondBookmark: Bookmark = {
  ...bookmark,
  id: 10,
  title: 'Vue',
  url: 'https://vuejs.org/',
  normalized_url: 'https://vuejs.org',
  domain: 'vuejs.org',
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function setViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
  window.dispatchEvent(new Event('resize'))
}

function mountWorkspace() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
  return mount(WorkspaceView, {
    attachTo: '#app',
    global: {
      plugins: [createPinia(), router],
      stubs: { RouterLink: true },
    },
  })
}

beforeEach(() => {
  document.body.innerHTML = '<div id="app"></div>'
  localStorage.clear()
  vi.clearAllMocks()
  clearCurrentUser()
  setActivePinia(createPinia())
  vi.useRealTimers()
  setViewport(1280)
  mockedApi.folders.mockResolvedValue(folders)
  mockedApi.me.mockResolvedValue({
    id: 7, username: 'tester', is_admin: true, is_active: true,
    must_change_password: false, csrf_token: 'csrf',
  })
  mockedApi.bookmarks.mockResolvedValue([bookmark])
  mockedApi.search.mockResolvedValue({ items: [bookmark], total: 1, limit: 50, offset: 0 })
  mockedApi.deleteFolderRecursive.mockResolvedValue({ backup_id: 12 })
  mockedApi.createFolder.mockResolvedValue({ ...folders[1], id: 3, base_name: '新建' })
  mockedApi.updateFolder.mockImplementation(async (id, changes) => ({
    ...folders.find((folder) => folder.id === id)!, ...changes,
  }))
  mockedApi.deleteFolder.mockResolvedValue(undefined)
})

describe('API security', () => {
  it('lets the browser set the multipart boundary for FormData writes', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }))
    const body = new FormData()
    body.append('file', new File(['html'], 'bookmarks.html', { type: 'text/html' }))

    await apiRequest('/imports/preview', { method: 'POST', body })

    const [, init] = fetchMock.mock.calls[0]
    expect(new Headers(init?.headers).has('Content-Type')).toBe(false)
  })

  it('adds the CSRF header to writes and redirects unauthorized requests', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
    setCsrfToken('csrf-value')
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))

    await apiRequest('/auth/logout', { method: 'POST' })

    const [, init] = fetchMock.mock.calls[0]
    expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('csrf-value')
    expect(init?.credentials).toBe('same-origin')

    clearCsrfToken()
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'Not authenticated' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    await expect(apiRequest('/auth/me')).rejects.toMatchObject({ status: 401 })
    expect(window.location.pathname).toBe('/login')
  })
})

describe('bookmark store', () => {
  it('refreshes direct folder counts after bookmark create, move, and delete', async () => {
    const created = { ...secondBookmark, folder_id: 1 }
    mockedApi.createBookmark.mockResolvedValue(created)
    mockedApi.updateBookmark.mockResolvedValue({ ...bookmark, folder_id: 1 })
    mockedApi.deleteBookmark.mockResolvedValue(undefined)
    mockedApi.folders
      .mockResolvedValueOnce(folders)
      .mockResolvedValueOnce([{ ...folders[0], bookmark_count: 1 }, folders[1]])
      .mockResolvedValueOnce([{ ...folders[0], bookmark_count: 2 }, { ...folders[1], bookmark_count: 0 }])
      .mockResolvedValueOnce([{ ...folders[0], bookmark_count: 1 }, { ...folders[1], bookmark_count: 0 }])
    const store = useBookmarksStore()
    await store.initialize()

    await store.saveBookmark({ title: created.title, url: created.url, folder_id: 1, notes: '' })
    expect(store.folders.map(({ bookmark_count }) => bookmark_count)).toEqual([1, 1])
    await store.saveBookmark({ ...bookmark, folder_id: 1 })
    expect(store.folders.map(({ bookmark_count }) => bookmark_count)).toEqual([2, 0])
    await store.removeBookmark({ ...bookmark, folder_id: 1 })
    expect(store.folders.map(({ bookmark_count }) => bookmark_count)).toEqual([1, 0])
  })

  it('does not fail a successful bookmark mutation when count refresh fails', async () => {
    mockedApi.createBookmark.mockResolvedValue(secondBookmark)
    mockedApi.folders.mockResolvedValueOnce(folders).mockRejectedValueOnce(new Error('count refresh failed'))
    const store = useBookmarksStore()
    await store.initialize()

    await expect(store.saveBookmark({
      title: secondBookmark.title, url: secondBookmark.url, folder_id: 2, notes: '',
    })).resolves.toEqual(secondBookmark)
    expect(store.error).toBe('')
    expect(store.selectedBookmark).toEqual(secondBookmark)
  })

  it('creates, renames, moves, reorders, and empty-deletes folders through typed methods', async () => {
    const store = useBookmarksStore()
    await store.initialize()
    await store.createFolder({ base_name: '新建', parent_id: 1 })
    await store.updateFolder(2, { base_name: '网络工具' })
    await store.updateFolder(2, { parent_id: null })
    await store.updateFolder(2, { position: 2 })
    await store.removeFolder(folders[1])

    expect(mockedApi.createFolder).toHaveBeenCalledWith({ base_name: '新建', parent_id: 1 })
    expect(mockedApi.updateFolder).toHaveBeenNthCalledWith(1, 2, { base_name: '网络工具' })
    expect(mockedApi.updateFolder).toHaveBeenNthCalledWith(2, 2, { parent_id: null })
    expect(mockedApi.updateFolder).toHaveBeenNthCalledWith(3, 2, { position: 2 })
    expect(mockedApi.deleteFolder).toHaveBeenCalledWith(2)
  })
  it('ignores an older folder response that arrives after a newer selection', async () => {
    const first = deferred<Bookmark[]>()
    const second = deferred<Bookmark[]>()
    mockedApi.bookmarks.mockImplementation((params) => params?.folder_id === 1 ? first.promise : second.promise)
    const store = useBookmarksStore()

    const oldSelection = store.selectFolder(1)
    const newSelection = store.selectFolder(2)
    second.resolve([bookmark])
    await newSelection
    first.resolve([secondBookmark])
    await oldSelection

    expect(store.selectedFolderId).toBe(2)
    expect(store.bookmarks).toEqual([bookmark])
  })

  it('loads a selected folder and persists edited bookmarks', async () => {
    const updated = { ...bookmark, title: 'Packet analyzer' }
    mockedApi.updateBookmark.mockResolvedValue(updated)
    const store = useBookmarksStore()

    await store.initialize()
    await store.selectFolder(2)
    store.selectBookmark(bookmark)
    await store.saveBookmark({ ...bookmark, title: 'Packet analyzer' })

    expect(mockedApi.bookmarks).toHaveBeenCalledWith({ folder_id: 2, limit: 100, offset: 0 })
    expect(mockedApi.updateBookmark).toHaveBeenCalledWith(9, {
      title: 'Packet analyzer',
      url: bookmark.url,
      folder_id: 2,
      notes: bookmark.notes,
    })
    expect(store.selectedBookmark?.title).toBe('Packet analyzer')
  })

  it('removes an edited bookmark when the API moves it outside the selected folder', async () => {
    const moved = { ...bookmark, folder_id: 1 }
    mockedApi.updateBookmark.mockResolvedValue(moved)
    const store = useBookmarksStore()
    await store.selectFolder(2)

    await store.saveBookmark({ ...bookmark, folder_id: 1 })

    expect(store.bookmarks).toEqual([])
  })

  it('records a visible error when a folder cannot be loaded', async () => {
    mockedApi.bookmarks.mockRejectedValueOnce(new Error('文件夹加载失败'))
    const store = useBookmarksStore()

    await expect(store.selectFolder(2)).rejects.toThrow('文件夹加载失败')

    expect(store.error).toBe('文件夹加载失败')
  })
})

describe('workspace', () => {
  it('requires typing the folder name before recursive deletion', async () => {
    mockedApi.folders.mockResolvedValueOnce(folders).mockResolvedValueOnce([folders[1]])
    const wrapper = mountWorkspace()
    await flushPromises()
    const deleteButton = wrapper.get<HTMLElement>('[data-test="delete-folder-1"]')
    deleteButton.element.focus()
    await deleteButton.trigger('click')

    const body = new DOMWrapper(document.body)
    const confirm = body.get('[data-test="confirm-destructive"]')
    expect(document.getElementById('app')?.hasAttribute('inert')).toBe(true)
    expect(confirm.attributes()).toHaveProperty('disabled')
    await body.get('[data-test="confirmation-input"]').setValue('工具')
    await confirm.trigger('click')
    await flushPromises()

    expect(mockedApi.deleteFolderRecursive).toHaveBeenCalledWith(1, '工具')
    expect(document.getElementById('app')?.hasAttribute('inert')).toBe(false)
    expect((document.activeElement as HTMLElement).dataset.test).toBe('folder-heading')
  })

  it('keeps data management reachable in the rendered mobile toolbar', async () => {
    setViewport(390)
    const wrapper = mountWorkspace()
    await flushPromises()

    const link = wrapper.get('[data-test="mobile-data-management"]')
    expect(link.attributes('to')).toBe('/import')
    expect(link.attributes()).not.toHaveProperty('aria-hidden')
    expect(link.classes()).toContain('mobile-only')
  })

  it('closes recursive delete on document Escape, clears inert, and restores its trigger', async () => {
    const wrapper = mountWorkspace()
    await flushPromises()
    const deleteButton = wrapper.get<HTMLElement>('[data-test="delete-folder-1"]')
    deleteButton.element.focus()
    await deleteButton.trigger('click')
    expect(document.getElementById('app')?.hasAttribute('inert')).toBe(true)

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()

    expect(document.querySelector('[data-test="confirmation-input"]')).toBeNull()
    expect(document.getElementById('app')?.hasAttribute('inert')).toBe(false)
    expect(document.activeElement).toBe(deleteButton.element)
  })

  it('keeps the combobox-controlled listbox mounted while collapsed', async () => {
    const wrapper = mountWorkspace()
    await flushPromises()
    const search = wrapper.get('[data-test="global-search"]')

    expect(search.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find(`#${search.attributes('aria-controls')}`).exists()).toBe(true)
  })

  it('debounces search, supports keyboard selection, and opens the selected result', async () => {
    vi.useFakeTimers()
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const wrapper = mountWorkspace()
    await flushPromises()

    await wrapper.get('[data-test="global-search"]').setValue('wireshark')
    await vi.advanceTimersByTimeAsync(249)
    expect(mockedApi.search).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()
    expect(mockedApi.search).toHaveBeenCalledWith({ q: 'wireshark', limit: 50, offset: 0 })

    await wrapper.get('[data-test="global-search"]').trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.get('[data-test="global-search"]').attributes('aria-activedescendant')).toBe('search-result-9')
    await wrapper.get('[data-test="global-search"]').trigger('keydown', { key: 'Enter' })
    expect(open).toHaveBeenCalledWith(bookmark.url, '_blank', 'noopener')
    await wrapper.get('[data-test="result-0"]').trigger('click')
    expect(open).toHaveBeenLastCalledWith(bookmark.url, '_blank', 'noopener')
  })

  it('keeps the newest search results when responses resolve out of order', async () => {
    vi.useFakeTimers()
    const first = deferred<Awaited<ReturnType<typeof apiClient.search>>>()
    const second = deferred<Awaited<ReturnType<typeof apiClient.search>>>()
    mockedApi.search.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const wrapper = mountWorkspace()
    await flushPromises()

    await wrapper.get('[data-test="global-search"]').setValue('old')
    await vi.advanceTimersByTimeAsync(250)
    await wrapper.get('[data-test="global-search"]').setValue('new')
    await vi.advanceTimersByTimeAsync(250)
    second.resolve({ items: [secondBookmark], total: 1, limit: 50, offset: 0 })
    await flushPromises()
    first.resolve({ items: [bookmark], total: 1, limit: 50, offset: 0 })
    await flushPromises()

    expect(wrapper.get('[data-test="result-0"]').text()).toContain('Vue')
    expect(wrapper.get('[data-test="result-0"]').text()).not.toContain('Wireshark')
  })

  it('clears search and rejects a pending response after Escape', async () => {
    vi.useFakeTimers()
    const pending = deferred<Awaited<ReturnType<typeof apiClient.search>>>()
    mockedApi.search.mockReturnValueOnce(pending.promise)
    const wrapper = mountWorkspace()
    await flushPromises()

    const search = wrapper.get('[data-test="global-search"]')
    await search.setValue('wireshark')
    await vi.advanceTimersByTimeAsync(250)
    await search.trigger('keydown', { key: 'Escape' })
    pending.resolve({ items: [bookmark], total: 1, limit: 50, offset: 0 })
    await flushPromises()

    expect((search.element as HTMLInputElement).value).toBe('')
    expect(search.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('[data-test="result-0"]').exists()).toBe(false)
  })

  it('announces a current search failure without an unhandled rejection', async () => {
    vi.useFakeTimers()
    mockedApi.search.mockRejectedValueOnce(new Error('搜索失败'))
    const wrapper = mountWorkspace()
    await flushPromises()

    await wrapper.get('[data-test="global-search"]').setValue('broken')
    await vi.advanceTimersByTimeAsync(250)
    await flushPromises()

    expect(wrapper.get('[data-test="search-error"]').text()).toContain('搜索失败')
    expect(wrapper.get('[data-test="search-error"]').attributes('role')).toBe('alert')
    expect(wrapper.find('[data-test="result-0"]').exists()).toBe(false)
  })

  it('does not let a stale search error replace newer successful results', async () => {
    vi.useFakeTimers()
    const stale = deferred<Awaited<ReturnType<typeof apiClient.search>>>()
    mockedApi.search
      .mockReturnValueOnce(stale.promise)
      .mockResolvedValueOnce({ items: [secondBookmark], total: 1, limit: 50, offset: 0 })
    const wrapper = mountWorkspace()
    await flushPromises()

    await wrapper.get('[data-test="global-search"]').setValue('old')
    await vi.advanceTimersByTimeAsync(250)
    await wrapper.get('[data-test="global-search"]').setValue('vue')
    await vi.advanceTimersByTimeAsync(250)
    await flushPromises()
    stale.reject(new Error('过期失败'))
    await flushPromises()

    expect(wrapper.get('[data-test="result-0"]').text()).toContain('Vue')
    expect(wrapper.find('[data-test="search-error"]').exists()).toBe(false)
  })

  it('switches between list and card layouts', async () => {
    const wrapper = mountWorkspace()
    await flushPromises()
    expect(wrapper.get('[data-test="bookmark-list"]').classes()).toContain('is-list')
    await wrapper.get('[data-test="view-card"]').trigger('click')
    expect(wrapper.get('[data-test="bookmark-list"]').classes()).toContain('is-card')
  })

  it('keeps the editor open and shows a save failure', async () => {
    mockedApi.updateBookmark.mockRejectedValueOnce(new Error('保存失败'))
    const wrapper = mountWorkspace()
    await flushPromises()
    await wrapper.get('.bookmark-item').trigger('click')

    await wrapper.get('.editor form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('.editor [role="alert"]').text()).toContain('保存失败')
  })

  it('collapses the folder tree into a closed drawer on narrow screens', async () => {
    setViewport(390)
    const wrapper = mountWorkspace()
    await flushPromises()

    expect(wrapper.get('[data-test="folder-drawer"]').attributes('aria-hidden')).toBe('true')
    await wrapper.get('[data-test="open-folders"]').trigger('click')
    expect(wrapper.get('[data-test="folder-drawer"]').attributes('aria-hidden')).toBe('false')
  })

  it('treats the mobile folder drawer as a modal, traps focus, and restores its trigger', async () => {
    setViewport(390)
    const wrapper = mountWorkspace()
    wrapper.element.remove()
    document.body.appendChild(wrapper.element)
    await flushPromises()
    const trigger = wrapper.get('[data-test="open-folders"]')
    ;(trigger.element as HTMLElement).focus()

    await trigger.trigger('click')
    await flushPromises()
    const drawer = wrapper.get('[data-test="folder-drawer"]')
    expect(drawer.attributes('role')).toBe('dialog')
    expect(drawer.attributes('aria-modal')).toBe('true')
    expect(wrapper.get('.content-panel').attributes()).toHaveProperty('inert')
    expect(drawer.element.contains(document.activeElement)).toBe(true)

    await drawer.trigger('keydown', { key: 'Tab', shiftKey: true })
    expect(drawer.element.contains(document.activeElement)).toBe(true)
    await drawer.trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(drawer.attributes('aria-hidden')).toBe('true')
    expect(document.activeElement).toBe(trigger.element)
    wrapper.unmount()
  })

  it('preserves the active folder and announces a failed mobile folder selection in the drawer', async () => {
    setViewport(390)
    mockedApi.bookmarks
      .mockResolvedValueOnce([bookmark])
      .mockRejectedValueOnce(new Error('无法加载网络文件夹'))
    const wrapper = mountWorkspace()
    await flushPromises()
    expect(wrapper.get('.content-heading h1').text()).toBe('工具')
    expect(wrapper.get('.bookmark-item').text()).toContain('Wireshark')

    await wrapper.get('[data-test="open-folders"]').trigger('click')
    await wrapper.get('[data-test="expand-all-folders"]').trigger('click')
    await wrapper.get('[data-folder-id="2"]').trigger('click')
    await flushPromises()

    const drawer = wrapper.get('[data-test="folder-drawer"]')
    expect(wrapper.get('.content-heading h1').text()).toBe('工具')
    expect(wrapper.get('.bookmark-item').text()).toContain('Wireshark')
    expect(drawer.attributes('aria-hidden')).toBe('false')
    expect(drawer.get('[role="alert"]').text()).toContain('无法加载网络文件夹')
  })

  it('opens the mobile editor as a focus-managed modal and closes it with Escape', async () => {
    setViewport(390)
    const wrapper = mountWorkspace()
    wrapper.element.remove()
    document.body.appendChild(wrapper.element)
    await flushPromises()
    const trigger = wrapper.get('.primary-button.compact')
    ;(trigger.element as HTMLElement).focus()

    await trigger.trigger('click')
    await flushPromises()
    const editor = wrapper.get('.editor-panel')
    expect(editor.attributes('role')).toBe('dialog')
    expect(editor.attributes('aria-modal')).toBe('true')
    expect(editor.attributes('aria-hidden')).toBe('false')
    expect(wrapper.get('.content-panel').attributes()).toHaveProperty('inert')
    expect(editor.element.contains(document.activeElement)).toBe(true)

    await editor.trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(editor.attributes('aria-hidden')).toBe('true')
    expect(document.activeElement).toBe(trigger.element)
    wrapper.unmount()
  })
})

describe('folder tree accessibility', () => {
  it('shows direct bookmark counts and exposes accessible folder management actions', async () => {
    const wrapper = mount(FolderTree, { props: { folders, selectedId: 2, userId: 7 }, attachTo: document.body })
    expect(wrapper.get('[data-folder-id="2"]').text()).toContain('1')
    expect(wrapper.get('[data-test="create-root-folder"]').attributes('aria-label')).toBe('新建根文件夹')
    expect(wrapper.get('[data-test="rename-folder"]').attributes('aria-label')).toContain('网络')

    const rename = wrapper.get<HTMLElement>('[data-test="rename-folder"]')
    rename.element.focus()
    await rename.trigger('click')
    const dialog = wrapper.get('[role="dialog"]')
    expect(dialog.attributes('aria-modal')).toBe('true')
    expect(document.activeElement).toBe(dialog.get('input').element)
    await dialog.get('input').setValue('网络工具')
    await dialog.get('form').trigger('submit')
    expect(wrapper.emitted('update')).toEqual([[2, { base_name: '网络工具' }]])
    expect(document.activeElement).toBe(rename.element)
    wrapper.unmount()
  })
  it('puts expansion and roving focus on treeitems and supports tree keyboard navigation', async () => {
    const wrapper = mount(FolderTree, {
      props: { folders, selectedId: 2, userId: 7 },
      attachTo: document.body,
    })
    const root = wrapper.get('[data-folder-id="1"]')
    const child = wrapper.get('[data-folder-id="2"]')
    expect(root.attributes('aria-expanded')).toBe('true')
    expect(root.attributes('tabindex')).toBe('-1')
    expect(child.attributes('tabindex')).toBe('0')

    ;(root.element as HTMLElement).focus()
    await root.trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement).toBe(child.element)
    await child.trigger('keydown', { key: 'ArrowUp' })
    expect(document.activeElement).toBe(root.element)
    await root.trigger('keydown', { key: 'ArrowLeft' })
    expect(root.attributes('aria-expanded')).toBe('false')
    await root.trigger('keydown', { key: 'ArrowRight' })
    expect(root.attributes('aria-expanded')).toBe('true')
    await root.trigger('keydown', { key: 'ArrowRight' })
    const visibleChild = wrapper.get('[data-folder-id="2"]')
    expect(document.activeElement).toBe(visibleChild.element)
    await visibleChild.trigger('keydown', { key: 'ArrowLeft' })
    expect(document.activeElement).toBe(root.element)
    await root.trigger('keydown', { key: 'ArrowRight' })
    await visibleChild.trigger('keydown', { key: 'Home' })
    expect(document.activeElement).toBe(root.element)
    await root.trigger('keydown', { key: 'End' })
    expect(document.activeElement).toBe(wrapper.get('[data-folder-id="2"]').element)
    wrapper.unmount()
  })

  it('expands and collapses all folders and persists the state per user', async () => {
    localStorage.setItem('navigation.folderTree.expanded.7', '[]')
    const wrapper = mount(FolderTree, {
      props: { folders, selectedId: 1, userId: 7 },
      attachTo: document.body,
    })

    expect(wrapper.find('[data-folder-id="2"]').exists()).toBe(false)
    await wrapper.get('[data-test="expand-all-folders"]').trigger('click')
    expect(wrapper.find('[data-folder-id="2"]').exists()).toBe(true)
    expect(localStorage.getItem('navigation.folderTree.expanded.7')).toBe('[1]')

    await wrapper.get('[data-test="collapse-all-folders"]').trigger('click')
    expect(wrapper.find('[data-folder-id="2"]').exists()).toBe(false)
    expect(localStorage.getItem('navigation.folderTree.expanded.7')).toBe('[]')
    wrapper.unmount()
  })
})
