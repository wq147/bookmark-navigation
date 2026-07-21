<script setup lang="ts">
import type { ImportSummaryCounts } from '@/types'

defineProps<{ summary: ImportSummaryCounts }>()
</script>

<template>
  <section class="summary-grid" aria-label="导入预览摘要">
    <article><strong data-test="new-count">{{ summary.new }}</strong><span>新增</span></article>
    <article><strong>{{ summary.duplicate }}</strong><span>已存在</span></article>
    <article><strong>{{ summary.conflict }}</strong><span>冲突</span></article>
    <article><strong>{{ summary.suggested_move }}</strong><span>建议移动</span></article>
    <article><strong>{{ summary.unclassified }}</strong><span>未分类</span></article>
  </section>
</template>
