import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient, clearCsrfToken, setCsrfToken } from '@/api'

describe('recursive delete transport', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    clearCsrfToken()
  })

  it('sends a Unicode folder name as strict ASCII percent-encoded UTF-8', async () => {
    setCsrfToken('csrf')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(
      JSON.stringify({ backup_id: 12 }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ))

    await apiClient.deleteFolderRecursive(3, '工具')

    const [url, init] = fetchMock.mock.calls[0]
    const headers = new Headers(init?.headers)
    expect(url).toBe('/api/v1/folders/3?recursive=true')
    expect(headers.get('X-Confirm-Delete')).toBe('%E5%B7%A5%E5%85%B7')
    expect(headers.get('X-CSRF-Token')).toBe('csrf')
  })

  it('bootstraps a fresh tab CSRF token from me before its first write', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 1, username: 'admin', csrf_token: 'fresh' }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))

    await apiClient.me()
    await apiClient.logout()

    const headers = new Headers(fetchMock.mock.calls[1][1]?.headers)
    expect(headers.get('X-CSRF-Token')).toBe('fresh')
  })

  it('provides typed transports for folder create, rename, move, reorder, and empty delete', async () => {
    const folder = { id: 3, parent_id: null, base_name: 'Docs', position: 1, bookmark_count: 0, created_at: '', updated_at: '' }
    const fetchMock = vi.spyOn(globalThis, 'fetch')
    for (let index = 0; index < 4; index += 1) fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(folder), {
      status: index === 0 ? 201 : 200, headers: { 'Content-Type': 'application/json' },
    }))
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))

    await apiClient.createFolder({ base_name: 'Docs', parent_id: null })
    await apiClient.updateFolder(3, { base_name: 'Manuals' })
    await apiClient.updateFolder(3, { parent_id: 2 })
    await apiClient.updateFolder(3, { position: 2 })
    await apiClient.deleteFolder(3)

    expect(fetchMock.mock.calls.map(([url, init]) => [url, init?.method])).toEqual([
      ['/api/v1/folders', 'POST'], ['/api/v1/folders/3', 'PATCH'],
      ['/api/v1/folders/3', 'PATCH'], ['/api/v1/folders/3', 'PATCH'],
      ['/api/v1/folders/3', 'DELETE'],
    ])
  })

  it('sends the explicit all-users confirmation for a database restore', async () => {
    setCsrfToken('csrf')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(
      JSON.stringify({ pre_restore_backup_id: 9 }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ))

    await apiClient.restoreBackup(7)

    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers)
    expect(headers.get('X-Confirm-Restore')).toBe('RESTORE ALL USERS')
    expect(headers.get('X-CSRF-Token')).toBe('csrf')
  })
})
