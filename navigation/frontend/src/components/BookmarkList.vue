<script setup lang="ts">
import type { Bookmark } from '@/types'

defineProps<{
  bookmarks: Bookmark[]
  selectedId: number | null
  mode: 'list' | 'card'
  loading?: boolean
}>()
const emit = defineEmits<{ select: [bookmark: Bookmark]; open: [bookmark: Bookmark] }>()
</script>

<template>
  <div
    data-test="bookmark-list"
    class="bookmark-list"
    :class="mode === 'card' ? 'is-card' : 'is-list'"
    aria-live="polite"
  >
    <p v-if="loading" class="empty-state">正在加载…</p>
    <p v-else-if="!bookmarks.length" class="empty-state">这个文件夹还没有书签。</p>
    <article
      v-for="bookmark in bookmarks"
      v-else
      :key="bookmark.id"
      class="bookmark-item"
      :class="{ selected: selectedId === bookmark.id }"
      tabindex="0"
      @click="emit('select', bookmark)"
      @keydown.enter="emit('select', bookmark)"
    >
      <div class="favicon" aria-hidden="true">{{ bookmark.domain.charAt(0).toUpperCase() || '·' }}</div>
      <div class="bookmark-copy">
        <h3>{{ bookmark.title }}</h3>
        <p class="bookmark-domain">{{ bookmark.domain }}</p>
        <p v-if="bookmark.notes" class="bookmark-notes">{{ bookmark.notes }}</p>
      </div>
      <button type="button" class="open-button" @click.stop="emit('open', bookmark)">
        打开<span class="sr-only"> {{ bookmark.title }}</span> ↗
      </button>
    </article>
  </div>
</template>
