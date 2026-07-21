export interface User {
  id: number
  username: string
  is_admin: boolean
  is_active: boolean
  must_change_password: boolean
  csrf_token: string
}

export interface AdminUser {
  id: number
  username: string
  is_admin: boolean
  is_active: boolean
  must_change_password: boolean
  created_at: string
  updated_at: string
}

export interface AdminAudit {
  id: number
  actor_user_id: number | null
  target_user_id: number | null
  target_username: string
  action: string
  result: string
  created_at: string
}

export interface Folder {
  id: number
  parent_id: number | null
  base_name: string
  position: number
  /** Number of active bookmarks directly in this folder (not descendants). */
  bookmark_count: number
  created_at: string
  updated_at: string
}

export interface FolderCreateInput {
  base_name: string
  parent_id?: number | null
  position?: number
}

export interface FolderUpdateInput {
  base_name?: string
  parent_id?: number | null
  position?: number
}

export interface Bookmark {
  id: number
  folder_id: number
  title: string
  url: string
  normalized_url: string
  notes: string
  position: number
  domain: string
  created_at: string
  updated_at: string
}

export interface BookmarkInput {
  title: string
  url: string
  folder_id: number
  notes: string
}

export interface SearchResponse {
  items: Bookmark[]
  total: number
  limit: number
  offset: number
}

export type ImportItemStatus = 'new' | 'duplicate' | 'conflict' | 'suggested_move'

export interface ImportItem {
  id: number
  source_url: string
  title: string
  notes: string
  folder_path: string[]
  classification_method: string
  attrs: Record<string, unknown>
  folder_attrs: Array<Record<string, unknown>>
  toolbar_attrs: Record<string, unknown>
  status: ImportItemStatus
  bookmark_id: number | null
}

export interface ImportSummaryCounts {
  new: number
  duplicate: number
  conflict: number
  suggested_move: number
  unclassified: number
}

export interface ImportPreview {
  id: number
  status: string
  expires_at: string
  summary: ImportSummaryCounts
  items: ImportItem[]
}

export interface ConflictChoice {
  item_id: number
  overwrite_title: boolean
  overwrite_folder: boolean
  overwrite_notes: boolean
}

export interface ImportApplyResult {
  batch_id: number
  status: string
  backup_id: number
  unique_bookmarks: number
  duplicate_urls: number
  unclassified: number
  created: Array<Record<string, unknown>>
  updated: number[]
}

export interface Backup {
  id: number
  filename: string
  checksum: string
  created_at: string
}
