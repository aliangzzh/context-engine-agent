<script setup lang="ts">
// 表格组件：列定义 + 加载态 + 空态 + 单元格插槽。
export interface Column {
  key: string
  label: string
  width?: string
  align?: 'left' | 'right' | 'center'
}

defineProps<{
  columns: Column[]
  rows: Record<string, any>[]
  loading?: boolean
  emptyText?: string
  rowKey?: string
}>()
</script>

<template>
  <div class="table-wrap">
    <table class="table">
      <thead>
        <tr>
          <th v-for="col in columns" :key="col.key" :style="{ width: col.width, textAlign: col.align || 'left' }">
            {{ col.label }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="loading">
          <td :colspan="columns.length" class="table-empty">加载中…</td>
        </tr>
        <tr v-else-if="!rows.length">
          <td :colspan="columns.length" class="table-empty">{{ emptyText || '暂无数据' }}</td>
        </tr>
        <tr v-else v-for="(row, i) in rows" :key="rowKey ? row[rowKey] : i">
          <td v-for="col in columns" :key="col.key" :style="{ textAlign: col.align || 'left' }">
            <slot :name="`cell-${col.key}`" :row="row" :value="row[col.key]">
              {{ row[col.key] }}
            </slot>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
