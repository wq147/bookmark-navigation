import type {
  AdminAudit, AdminUser, Backup, Bookmark, BookmarkInput, ConflictChoice, Folder, FolderCreateInput,
  FolderUpdateInput, ImportApplyResult, ImportPreview, SearchResponse, User,
} from './types'

const API_ROOT = '/api/v1'
let csrfToken = sessionStorage.getItem('navigation.csrf') ?? ''

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly details: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  static async fromResponse(response: Response): Promise<ApiError> {
    let details: unknown
    try {
      details = await response.json()
    } catch {
      details = undefined
    }
    const message =
      typeof details === 'object' && details && 'detail' in details
        ? String((details as { detail: unknown }).detail)
        : `Request failed (${response.status})`
    return new ApiError(response.status, message, details)
  }
}

export function setCsrfToken(token: string): void {
  csrfToken = token
  sessionStorage.setItem('navigation.csrf', token)
}

export function clearCsrfToken(): void {
  csrfToken = ''
  sessionStorage.removeItem('navigation.csrf')
}

export async function apiRequest<T = void>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const method = (init.method ?? 'GET').toUpperCase()
  if (!['GET', 'HEAD'].includes(method) && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken)
  }
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers,
    credentials: 'same-origin',
  })
  if (response.status === 401) {
    clearCsrfToken()
    if (window.location.pathname !== '/login') window.history.replaceState({}, '', '/login')
    window.dispatchEvent(new CustomEvent('navigation:unauthorized'))
  }
  if (!response.ok) throw await ApiError.fromResponse(response)
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

async function apiBlobRequest(path: string): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_ROOT}${path}`, { credentials: 'same-origin' })
  if (response.status === 401) {
    clearCsrfToken()
    if (window.location.pathname !== '/login') window.history.replaceState({}, '', '/login')
    window.dispatchEvent(new CustomEvent('navigation:unauthorized'))
  }
  if (!response.ok) throw await ApiError.fromResponse(response)
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const filename = /filename="?([^";]+)"?/i.exec(disposition)?.[1] ?? 'bookmarks-export'
  return { blob: await response.blob(), filename }
}

async function downloadExport(kind: 'bookmarks.html' | 'backup.json'): Promise<void> {
  const { blob, filename } = await apiBlobRequest(`/exports/${kind}`)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.style.display = 'none'
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined) search.set(key, String(value))
  })
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ''
}

export const apiClient = {
  async me() {
    const user = await apiRequest<User>('/auth/me')
    setCsrfToken(user.csrf_token)
    return user
  },
  async login(username: string, password: string) {
    const result = await apiRequest<{ csrf_token: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    setCsrfToken(result.csrf_token)
    return result
  },
  async logout() {
    await apiRequest('/auth/logout', { method: 'POST' })
    clearCsrfToken()
  },
  changePassword: (currentPassword: string, newPassword: string) =>
    apiRequest('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),
  folders: () => apiRequest<Folder[]>('/folders'),
  createFolder: (payload: FolderCreateInput) =>
    apiRequest<Folder>('/folders', { method: 'POST', body: JSON.stringify(payload) }),
  updateFolder: (id: number, payload: FolderUpdateInput) =>
    apiRequest<Folder>(`/folders/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteFolder: (id: number) => apiRequest(`/folders/${id}`, { method: 'DELETE' }),
  bookmarks: (params: { folder_id?: number; limit?: number; offset?: number } = {}) =>
    apiRequest<Bookmark[]>(`/bookmarks${query(params)}`),
  search: (params: { q: string; folder_id?: number; limit?: number; offset?: number }) =>
    apiRequest<SearchResponse>(`/search${query(params)}`),
  createBookmark: (payload: BookmarkInput) =>
    apiRequest<Bookmark>('/bookmarks', { method: 'POST', body: JSON.stringify(payload) }),
  updateBookmark: (id: number, payload: BookmarkInput) =>
    apiRequest<Bookmark>(`/bookmarks/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteBookmark: (id: number) => apiRequest(`/bookmarks/${id}`, { method: 'DELETE' }),
  previewImport: (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return apiRequest<ImportPreview>('/imports/preview', { method: 'POST', body })
  },
  applyImport: (batchId: number, payload: { overrides: ConflictChoice[] }) =>
    apiRequest<ImportApplyResult>(`/imports/${batchId}/apply`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  downloadExport,
  backups: () => apiRequest<Backup[]>('/backups'),
  restoreBackup: (backupId: number) =>
    apiRequest<{ pre_restore_backup_id: number }>(`/backups/${backupId}/restore`, {
      method: 'POST', headers: { 'X-Confirm-Restore': 'RESTORE ALL USERS' },
    }),
  adminUsers: () => apiRequest<AdminUser[]>('/admin/users'),
  createUser: (username: string, temporaryPassword: string) => apiRequest<AdminUser>('/admin/users', {
    method: 'POST', body: JSON.stringify({ username, temporary_password: temporaryPassword }),
  }),
  setUserActive: (userId: number, isActive: boolean) => apiRequest<AdminUser>(
    `/admin/users/${userId}/status`,
    { method: 'PATCH', body: JSON.stringify({ is_active: isActive }) },
  ),
  resetUserPassword: (userId: number, temporaryPassword: string) => apiRequest(
    `/admin/users/${userId}/reset-password`,
    { method: 'POST', body: JSON.stringify({ temporary_password: temporaryPassword }) },
  ),
  deleteUser: (userId: number, username: string) => apiRequest(`/admin/users/${userId}`, {
    method: 'DELETE', headers: { 'X-Confirm-Username': encodeURIComponent(username) },
  }),
  adminAudit: () => apiRequest<AdminAudit[]>('/admin/audit'),
  deleteFolderRecursive: (folderId: number, folderName: string) => apiRequest<{ backup_id: number }>(
    `/folders/${folderId}?recursive=true`,
    { method: 'DELETE', headers: { 'X-Confirm-Delete': encodeURIComponent(folderName) } },
  ),
}
