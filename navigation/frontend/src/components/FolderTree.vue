<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { Folder, FolderCreateInput, FolderUpdateInput } from '@/types'

interface TreeEntry {
  folder: Folder
  level: number
}

const props = defineProps<{
  folders: Folder[]
  selectedId: number | null
  userId: number
  error?: string
}>()
const emit = defineEmits<{
  select: [id: number]
  create: [payload: FolderCreateInput]
  update: [id: number, payload: FolderUpdateInput]
  delete: [folder: Folder, recursive: boolean]
}>()
function storageKey(userId = props.userId): string {
  return `navigation.folderTree.expanded.${userId}`
}

function storedExpanded(userId = props.userId): Set<number> | null {
  const value = localStorage.getItem(storageKey(userId))
  if (value === null) return null
  try {
    const ids = JSON.parse(value)
    return new Set(Array.isArray(ids) ? ids.filter((id): id is number => Number.isInteger(id)) : [])
  } catch {
    return new Set()
  }
}

const initialExpanded = storedExpanded()
const expandedIds = ref(initialExpanded ?? new Set<number>())
let useDefaultExpansion = initialExpanded === null
const focusedId = ref<number | null>(props.selectedId)
const selectedFolder = computed(() => props.folders.find(({ id }) => id === props.selectedId) ?? null)
const dialogMode = ref<'create-root' | 'create-child' | 'rename' | 'move' | null>(null)
const dialogValue = ref('')
const moveParentId = ref<number | null>(null)
const managementDialog = ref<HTMLElement | null>(null)
let dialogFocusOrigin: HTMLElement | null = null

async function openDialog(mode: NonNullable<typeof dialogMode.value>): Promise<void> {
  dialogFocusOrigin = document.activeElement instanceof HTMLElement ? document.activeElement : null
  dialogMode.value = mode
  dialogValue.value = mode === 'rename' ? selectedFolder.value?.base_name ?? '' : ''
  moveParentId.value = selectedFolder.value?.parent_id ?? null
  await nextTick()
  managementDialog.value?.querySelector<HTMLElement>('input, select')?.focus()
}

function closeDialog(): void {
  dialogMode.value = null
  const origin = dialogFocusOrigin
  dialogFocusOrigin = null
  void nextTick(() => origin?.focus())
}

function dialogKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    closeDialog()
    return
  }
  if (event.key !== 'Tab' || !managementDialog.value) return
  const controls = Array.from(
    managementDialog.value.querySelectorAll<HTMLElement>('input, select, button:not([disabled])'),
  )
  const first = controls[0]
  const last = controls[controls.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}

function submitDialog(): void {
  if (dialogMode.value === 'create-root' && dialogValue.value.trim()) {
    emit('create', { base_name: dialogValue.value.trim(), parent_id: null })
  } else if (dialogMode.value === 'create-child' && selectedFolder.value && dialogValue.value.trim()) {
    emit('create', { base_name: dialogValue.value.trim(), parent_id: selectedFolder.value.id })
  } else if (dialogMode.value === 'rename' && selectedFolder.value && dialogValue.value.trim()) {
    emit('update', selectedFolder.value.id, { base_name: dialogValue.value.trim() })
  } else if (dialogMode.value === 'move' && selectedFolder.value) {
    emit('update', selectedFolder.value.id, { parent_id: moveParentId.value })
  }
  closeDialog()
}

function reorder(delta: number): void {
  if (!selectedFolder.value) return
  const siblings = childrenOf(selectedFolder.value.parent_id)
  const target = Math.max(1, Math.min(siblings.length, selectedFolder.value.position + delta))
  if (target !== selectedFolder.value.position) emit('update', selectedFolder.value.id, { position: target })
}

function childrenOf(parentId: number | null): Folder[] {
  return props.folders
    .filter((folder) => folder.parent_id === parentId)
    .sort((a, b) => a.position - b.position)
}

function hasChildren(id: number): boolean {
  return props.folders.some((folder) => folder.parent_id === id)
}

watch(
  () => props.folders,
  (folders) => {
    const folderIds = new Set(folders.map(({ id }) => id))
    const next = new Set([...expandedIds.value].filter((id) => folderIds.has(id) && hasChildren(id)))
    if (useDefaultExpansion) folders.filter(({ id }) => hasChildren(id)).forEach(({ id }) => next.add(id))
    expandedIds.value = next
    if (folders.length > 0 || !useDefaultExpansion) {
      localStorage.setItem(storageKey(), JSON.stringify([...next].sort((a, b) => a - b)))
      useDefaultExpansion = false
    }
  },
  { immediate: true },
)

watch(
  () => props.userId,
  (userId) => {
    const stored = storedExpanded(userId)
    expandedIds.value = stored ?? new Set(props.folders.filter(({ id }) => hasChildren(id)).map(({ id }) => id))
    localStorage.setItem(storageKey(userId), JSON.stringify([...expandedIds.value].sort((a, b) => a - b)))
  },
)

const visibleEntries = computed<TreeEntry[]>(() => {
  const entries: TreeEntry[] = []
  function append(parentId: number | null, level: number): void {
    for (const folder of childrenOf(parentId)) {
      entries.push({ folder, level })
      if (expandedIds.value.has(folder.id)) append(folder.id, level + 1)
    }
  }
  append(null, 1)
  return entries
})

watch(
  () => [props.selectedId, visibleEntries.value.map(({ folder }) => folder.id).join(',')] as const,
  () => {
    const visibleIds = visibleEntries.value.map(({ folder }) => folder.id)
    if (props.selectedId !== null && visibleIds.includes(props.selectedId)) focusedId.value = props.selectedId
    else if (focusedId.value === null || !visibleIds.includes(focusedId.value)) focusedId.value = visibleIds[0] ?? null
  },
  { immediate: true },
)

function setExpanded(id: number, expanded: boolean): void {
  const next = new Set(expandedIds.value)
  expanded ? next.add(id) : next.delete(id)
  expandedIds.value = next
  localStorage.setItem(storageKey(), JSON.stringify([...next].sort((a, b) => a - b)))
}

function expandAll(): void {
  const next = new Set(props.folders.filter(({ id }) => hasChildren(id)).map(({ id }) => id))
  expandedIds.value = next
  localStorage.setItem(storageKey(), JSON.stringify([...next].sort((a, b) => a - b)))
}

function collapseAll(): void {
  expandedIds.value = new Set()
  localStorage.setItem(storageKey(), '[]')
}

async function focusFolder(id: number): Promise<void> {
  focusedId.value = id
  await nextTick()
  document.getElementById(`folder-treeitem-${id}`)?.focus()
}

function selectFolder(id: number): void {
  focusedId.value = id
  emit('select', id)
}

async function handleKey(event: KeyboardEvent, entry: TreeEntry): Promise<void> {
  const entries = visibleEntries.value
  const index = entries.findIndex(({ folder }) => folder.id === entry.folder.id)
  const children = childrenOf(entry.folder.id)
  if (event.key === 'ArrowDown' && index < entries.length - 1) {
    event.preventDefault()
    await focusFolder(entries[index + 1].folder.id)
  } else if (event.key === 'ArrowUp' && index > 0) {
    event.preventDefault()
    await focusFolder(entries[index - 1].folder.id)
  } else if (event.key === 'Home' && entries.length) {
    event.preventDefault()
    await focusFolder(entries[0].folder.id)
  } else if (event.key === 'End' && entries.length) {
    event.preventDefault()
    await focusFolder(entries[entries.length - 1].folder.id)
  } else if (event.key === 'ArrowRight' && children.length) {
    event.preventDefault()
    if (!expandedIds.value.has(entry.folder.id)) setExpanded(entry.folder.id, true)
    else await focusFolder(children[0].id)
  } else if (event.key === 'ArrowLeft') {
    if (children.length && expandedIds.value.has(entry.folder.id)) {
      event.preventDefault()
      setExpanded(entry.folder.id, false)
    } else if (entry.folder.parent_id !== null) {
      event.preventDefault()
      await focusFolder(entry.folder.parent_id)
    }
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    selectFolder(entry.folder.id)
  }
}
</script>

<template>
  <nav class="folder-tree" aria-label="书签文件夹">
    <div data-test="folder-heading" class="panel-heading" tabindex="-1">
      <div>
        <p class="eyebrow">COLLECTIONS</p>
        <h2>文件夹</h2>
      </div>
      <div class="folder-heading-actions">
        <span class="count-pill">{{ folders.length }}</span>
        <button data-test="create-root-folder" type="button" class="icon-button" aria-label="新建根文件夹" @click="openDialog('create-root')">+</button>
      </div>
    </div>
    <div class="folder-expand-actions" role="toolbar" aria-label="文件夹展开状态">
      <button data-test="expand-all-folders" type="button" @click="expandAll">全部展开</button>
      <button data-test="collapse-all-folders" type="button" @click="collapseAll">全部收起</button>
    </div>
    <div v-if="selectedFolder" class="folder-actions" role="toolbar" :aria-label="`管理文件夹 ${selectedFolder.base_name}`">
      <button type="button" :aria-label="`在 ${selectedFolder.base_name} 中新建子文件夹`" @click="openDialog('create-child')">子文件夹</button>
      <button data-test="rename-folder" type="button" :aria-label="`重命名文件夹 ${selectedFolder.base_name}`" @click="openDialog('rename')">重命名</button>
      <button type="button" :aria-label="`移动文件夹 ${selectedFolder.base_name}`" @click="openDialog('move')">移动</button>
      <button type="button" :disabled="selectedFolder.position <= 1" :aria-label="`上移文件夹 ${selectedFolder.base_name}`" @click="reorder(-1)">↑</button>
      <button type="button" :disabled="selectedFolder.position >= childrenOf(selectedFolder.parent_id).length" :aria-label="`下移文件夹 ${selectedFolder.base_name}`" @click="reorder(1)">↓</button>
      <button type="button" :aria-label="`删除空文件夹 ${selectedFolder.base_name}`" @click="emit('delete', selectedFolder, false)">删除空文件夹</button>
      <button :data-test="`delete-folder-${selectedFolder.id}`" type="button" class="folder-delete" :aria-label="`递归删除文件夹 ${selectedFolder.base_name}`" @click="emit('delete', selectedFolder, true)">递归删除</button>
    </div>
    <p v-if="error" class="form-error" role="alert" aria-live="assertive">{{ error }}</p>
    <ul role="tree" aria-label="文件夹树">
      <li
        v-for="entry in visibleEntries"
        :id="`folder-treeitem-${entry.folder.id}`"
        :key="entry.folder.id"
        role="treeitem"
        :data-folder-id="entry.folder.id"
        :aria-level="entry.level"
        :aria-selected="selectedId === entry.folder.id"
        :aria-expanded="hasChildren(entry.folder.id) ? expandedIds.has(entry.folder.id) : undefined"
        :tabindex="focusedId === entry.folder.id ? 0 : -1"
        @focus="focusedId = entry.folder.id"
        @click="selectFolder(entry.folder.id)"
        @keydown="handleKey($event, entry)"
      >
        <div
          class="tree-row"
          :class="{ selected: selectedId === entry.folder.id }"
          :style="{ paddingInlineStart: `${(entry.level - 1) * 16}px` }"
        >
          <span
            v-if="hasChildren(entry.folder.id)"
            class="disclosure tree-disclosure"
            aria-hidden="true"
            @click.stop="setExpanded(entry.folder.id, !expandedIds.has(entry.folder.id))"
          >{{ expandedIds.has(entry.folder.id) ? '−' : '+' }}</span>
          <span v-else class="tree-spacer" aria-hidden="true"></span>
          <span class="tree-label"><span aria-hidden="true">📁</span> {{ entry.folder.base_name }} <span class="count-pill" :aria-label="`${entry.folder.bookmark_count} 个直接书签`">{{ entry.folder.bookmark_count }}</span></span>
        </div>
      </li>
    </ul>
    <div v-if="dialogMode" class="dialog-backdrop" role="presentation" @click.self="closeDialog">
      <section ref="managementDialog" class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="folder-dialog-title" @keydown="dialogKeydown">
        <h3 id="folder-dialog-title">{{ dialogMode === 'rename' ? '重命名文件夹' : dialogMode === 'move' ? '移动文件夹' : '新建文件夹' }}</h3>
        <form @submit.prevent="submitDialog">
          <label v-if="dialogMode !== 'move'">文件夹名称<input v-model="dialogValue" required maxlength="255" autofocus /></label>
          <label v-else>目标父文件夹
            <select v-model="moveParentId">
              <option :value="null">根层级</option>
              <option v-for="folder in folders.filter(({ id }) => id !== selectedFolder?.id)" :key="folder.id" :value="folder.id">{{ folder.base_name }}</option>
            </select>
          </label>
          <div class="dialog-actions"><button type="button" @click="closeDialog">取消</button><button type="submit" class="primary-button">确认</button></div>
        </form>
      </section>
    </div>
  </nav>
</template>
