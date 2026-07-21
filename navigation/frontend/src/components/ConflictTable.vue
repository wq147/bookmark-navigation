<script setup lang="ts">
import type { ConflictChoice, ImportItem } from '@/types'

defineProps<{ items: ImportItem[] }>()
const choices = defineModel<ConflictChoice[]>({ required: true })

function choiceFor(id: number): ConflictChoice {
  const choice = choices.value.find(({ item_id }) => item_id === id)
  if (!choice) throw new Error(`Missing conflict choice for item ${id}`)
  return choice
}
</script>

<template>
  <section v-if="items.length" class="conflict-section">
    <div class="section-heading">
      <div><p class="eyebrow">CONFLICTS</p><h2>冲突处理</h2></div>
      <span class="count-pill">{{ items.length }}</span>
    </div>
    <div class="table-scroll">
      <table>
        <thead><tr><th>导入项</th><th>目标文件夹</th><th>覆盖标题</th><th>覆盖文件夹</th><th>覆盖备注</th></tr></thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td><strong>{{ item.title }}</strong><small>{{ item.source_url }}</small></td>
            <td>{{ item.folder_path.join(' / ') }}</td>
            <td><input v-model="choiceFor(item.id).overwrite_title" data-test="overwrite-title" type="checkbox" :aria-label="`覆盖 ${item.title} 的标题`" /></td>
            <td><input v-model="choiceFor(item.id).overwrite_folder" data-test="overwrite-folder" type="checkbox" :aria-label="`覆盖 ${item.title} 的文件夹`" /></td>
            <td><input v-model="choiceFor(item.id).overwrite_notes" data-test="overwrite-notes" type="checkbox" :aria-label="`覆盖 ${item.title} 的备注`" /></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
