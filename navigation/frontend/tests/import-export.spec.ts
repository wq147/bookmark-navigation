import { DOMWrapper, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { apiClient } from '@/api'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import BackupView from '@/views/BackupView.vue'
import ImportView from '@/views/ImportView.vue'
import type { ImportPreview } from '@/types'
import { currentUser } from '@/session'

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    apiClient: {
      ...actual.apiClient,
      previewImport: vi.fn(), applyImport: vi.fn(), downloadExport: vi.fn(),
      backups: vi.fn(), restoreBackup: vi.fn(),
    },
  }
})

const mockedApi = vi.mocked(apiClient)
const preview: ImportPreview = {
  id: 41, status: 'previewed', expires_at: '2026-07-14T00:00:00Z',
  summary: { new: 12, duplicate: 2, conflict: 1, suggested_move: 1, unclassified: 3 },
  items: [{
    id: 9, source_url: 'https://example.com/', title: '新标题', notes: '新备注',
    folder_path: ['工具'], classification_method: 'rule', attrs: {}, folder_attrs: [],
    toolbar_attrs: {}, status: 'conflict', bookmark_id: 2,
  }, {
    id: 10, source_url: 'https://move.example/', title: '建议移动', notes: '',
    folder_path: ['AI'], classification_method: 'rule', attrs: {}, folder_attrs: [],
    toolbar_attrs: {}, status: 'suggested_move', bookmark_id: 3,
  }],
}

function testRouter() {
  return createRouter({ history: createMemoryHistory(), routes: [
    { path: '/login', name: 'login', component: { template: '<div />' } },
    { path: '/', component: { template: '<div />' } },
    { path: '/import', component: { template: '<div />' } },
    { path: '/backups', component: { template: '<div />' } },
  ] })
}

async function uploadFixture(wrapper: VueWrapper) {
  const input = wrapper.get<HTMLInputElement>('[data-test="import-file"]')
  Object.defineProperty(input.element, 'files', { configurable: true, value: [
    new File(['<!DOCTYPE NETSCAPE-Bookmark-file-1>'], 'bookmarks.html', { type: 'text/html' }),
  ] })
  await input.trigger('change')
}

beforeEach(() => {
  document.body.innerHTML = '<div id="app"></div>'
  vi.clearAllMocks()
  currentUser.value = {
    id: 1, username: 'admin', is_admin: true, is_active: true,
    must_change_password: false, csrf_token: 'csrf',
  }
  mockedApi.previewImport.mockResolvedValue(preview)
  mockedApi.applyImport.mockResolvedValue({ batch_id: 41, status: 'applied', backup_id: 7,
    unique_bookmarks: 12, duplicate_urls: 2, unclassified: 3, created: [], updated: [] })
  mockedApi.backups.mockResolvedValue([
    { id: 7, filename: 'before-import.sqlite3', checksum: 'abc', created_at: '2026-07-13T01:00:00Z' },
  ])
  mockedApi.restoreBackup.mockResolvedValue({ pre_restore_backup_id: 8 })
})

describe('safe import', () => {
  it('does not enable apply until preview is loaded', async () => {
    const wrapper = mount(ImportView, { global: { plugins: [testRouter()] } })
    expect(wrapper.get('[data-test="apply-import"]').attributes()).toHaveProperty('disabled')
    await uploadFixture(wrapper)
    await flushPromises()
    expect(wrapper.get('[data-test="new-count"]').text()).toContain('12')
    expect(wrapper.get('[data-test="apply-import"]').attributes()).not.toHaveProperty('disabled')
  })

  it('defaults all conflict overwrite controls to off and submits explicit safe choices', async () => {
    const wrapper = mount(ImportView, { global: { plugins: [testRouter()] } })
    await uploadFixture(wrapper)
    await flushPromises()
    expect(wrapper.findAll('[data-test="overwrite-title"]:checked')).toHaveLength(0)
    expect(wrapper.findAll('[data-test="overwrite-folder"]:checked')).toHaveLength(0)
    expect(wrapper.findAll('[data-test="overwrite-notes"]:checked')).toHaveLength(0)
    expect(wrapper.text()).toContain('不会根据导入文件缺失项删除服务器书签')
    await wrapper.get('[data-test="apply-import"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('建议移动')
    expect(mockedApi.applyImport).toHaveBeenCalledWith(41, { overrides: [
      { item_id: 9, overwrite_title: false, overwrite_folder: false, overwrite_notes: false },
      { item_id: 10, overwrite_title: false, overwrite_folder: false, overwrite_notes: false },
    ] })
  })

  it('reports preview failures without enabling apply', async () => {
    mockedApi.previewImport.mockRejectedValueOnce(new Error('文件格式错误'))
    const wrapper = mount(ImportView, { global: { plugins: [testRouter()] } })
    await uploadFixture(wrapper)
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('文件格式错误')
    expect(wrapper.get('[data-test="apply-import"]').attributes()).toHaveProperty('disabled')
  })
})

describe('exports and recovery', () => {
  it('uses authenticated export downloads', async () => {
    const wrapper = mount(BackupView, { global: { plugins: [testRouter()] } })
    await flushPromises()
    await wrapper.get('[data-test="export-html"]').trigger('click')
    await flushPromises()
    expect(mockedApi.downloadExport).toHaveBeenCalledWith('bookmarks.html')
  })

  it('requires the exact typed phrase before confirming restore', async () => {
    const router = testRouter()
    const wrapper = mount(BackupView, { attachTo: '#app', global: { plugins: [router] } })
    await flushPromises()
    const restoreButton = wrapper.get<HTMLElement>('[data-test="restore-7"]')
    restoreButton.element.focus()
    await restoreButton.trigger('click')
    const body = new DOMWrapper(document.body)
    const confirm = body.get('[data-test="confirm-destructive"]')
    expect(document.getElementById('app')?.hasAttribute('inert')).toBe(true)
    expect(confirm.attributes()).toHaveProperty('disabled')
    await body.get('[data-test="confirmation-input"]').setValue('还原备份 7')
    expect(confirm.attributes()).not.toHaveProperty('disabled')
    await confirm.trigger('click')
    await flushPromises()
    expect(mockedApi.restoreBackup).toHaveBeenCalledWith(7)
    expect(mockedApi.backups).toHaveBeenCalledTimes(1)
    expect(currentUser.value).toBeNull()
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.restored).toBe('1')
    expect(document.getElementById('app')?.hasAttribute('inert')).toBe(false)
  })

  it('closes restore on document Escape, clears inert, and restores its trigger', async () => {
    const wrapper = mount(BackupView, { attachTo: '#app', global: { plugins: [testRouter()] } })
    await flushPromises()
    const restoreButton = wrapper.get<HTMLElement>('[data-test="restore-7"]')
    restoreButton.element.focus()
    await restoreButton.trigger('click')
    expect(document.getElementById('app')?.hasAttribute('inert')).toBe(true)

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()

    expect(document.querySelector('[data-test="confirmation-input"]')).toBeNull()
    expect(document.getElementById('app')?.hasAttribute('inert')).toBe(false)
    expect((document.activeElement as HTMLElement).dataset.test).toBe('restore-7')
  })
})

describe('typed confirmation', () => {
  it('resets stale input when reopened for another destructive action', async () => {
    const wrapper = mount(ConfirmDialog, { attachTo: '#app', props: { open: true, title: '危险操作', phrase: '删除 A' } })
    const body = new DOMWrapper(document.body)
    await body.get('[data-test="confirmation-input"]').setValue('删除 A')
    expect(body.get('[data-test="confirm-destructive"]').attributes()).not.toHaveProperty('disabled')
    await wrapper.setProps({ open: false })
    await wrapper.setProps({ open: true, phrase: '删除 B' })
    expect(body.get<HTMLInputElement>('[data-test="confirmation-input"]').element.value).toBe('')
    expect(body.get('[data-test="confirm-destructive"]').attributes()).toHaveProperty('disabled')
  })

  it('traps Tab in both directions, handles document Escape, and restores focus', async () => {
    const origin = document.createElement('button')
    origin.textContent = '打开'
    document.getElementById('app')?.append(origin)
    origin.focus()
    const wrapper = mount(ConfirmDialog, {
      attachTo: '#app', props: { open: false, title: '危险操作', phrase: '删除 A' },
    })
    await wrapper.setProps({ open: true })
    await nextTick()
    const body = new DOMWrapper(document.body)
    const input = body.get<HTMLInputElement>('[data-test="confirmation-input"]')
    await input.setValue('删除 A')
    const confirm = body.get<HTMLElement>('[data-test="confirm-destructive"]')
    confirm.element.focus()

    await confirm.trigger('keydown', { key: 'Tab' })
    expect(document.activeElement).toBe(input.element)
    await input.trigger('keydown', { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(confirm.element)

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    await wrapper.setProps({ open: false })
    await nextTick()
    expect(document.getElementById('app')?.hasAttribute('inert')).toBe(false)
    expect(document.activeElement).toBe(origin)
  })
})
