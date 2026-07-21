<script setup lang="ts">
defineProps<{
  username: string
  isAdmin: boolean
  query: string
  mode: 'list' | 'card'
  resultCount: number
  activeResult: number
  activeResultId?: string
  error?: string
}>()
const emit = defineEmits<{
  'update:query': [value: string]
  keydown: [event: KeyboardEvent]
  mode: [mode: 'list' | 'card']
  folders: []
  create: []
  logout: []
  result: [index: number]
}>()
</script>

<template>
  <header class="toolbar">
    <div class="brand"><span class="brand-mark">N</span><strong>Navigation</strong></div>
    <button data-test="open-folders" type="button" class="ghost-button mobile-only" @click="emit('folders')">
      文件夹
    </button>
    <RouterLink data-test="mobile-data-management" class="ghost-button mobile-only" to="/import">数据</RouterLink>
    <div class="search-wrap">
      <label class="sr-only" for="global-search">搜索全部书签</label>
      <span class="search-icon" aria-hidden="true">⌕</span>
      <input
        id="global-search"
        data-test="global-search"
        type="search"
        :value="query"
        placeholder="搜索标题、网址、目录或备注"
        autocomplete="off"
        role="combobox"
        :aria-expanded="resultCount > 0"
        aria-controls="search-results"
        :aria-activedescendant="activeResultId"
        @input="emit('update:query', ($event.target as HTMLInputElement).value)"
        @keydown="emit('keydown', $event)"
      />
      <span class="shortcut" aria-hidden="true">/</span>
      <p v-if="error" data-test="search-error" class="search-error" role="alert">{{ error }}</p>
    </div>
    <div class="toolbar-actions">
      <div class="view-toggle" aria-label="视图模式">
        <button
          data-test="view-list"
          type="button"
          :aria-pressed="mode === 'list'"
          aria-label="列表视图"
          @click="emit('mode', 'list')"
        >☷</button>
        <button
          data-test="view-card"
          type="button"
          :aria-pressed="mode === 'card'"
          aria-label="卡片视图"
          @click="emit('mode', 'card')"
        >▦</button>
      </div>
      <button type="button" class="primary-button compact" @click="emit('create')">+新建</button>
      <RouterLink data-test="desktop-data-management" class="ghost-button data-link" to="/import">数据</RouterLink>
      <RouterLink v-if="isAdmin" data-test="admin-users" class="ghost-button data-link" to="/admin/users">用户</RouterLink>
      <RouterLink class="account-link" to="/change-password" :aria-label="`${username}，${isAdmin ? '管理员' : '用户'}，修改密码`"><strong>{{ username }}</strong><small>{{ isAdmin ? '管理员' : '用户' }}</small></RouterLink>
      <button type="button" class="ghost-button logout" @click="emit('logout')">退出</button>
    </div>
    <div v-show="resultCount" id="search-results" class="search-popover" role="listbox">
      <slot name="results" :active-result="activeResult"></slot>
    </div>
  </header>
</template>
