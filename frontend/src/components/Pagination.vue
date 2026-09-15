<script setup lang="ts">
// 分页条：页码 + 每页条数 + 总数。
import { computed } from 'vue'

const props = defineProps<{ page: number; pages: number; total: number; size: number }>()
const emit = defineEmits<{
  (e: 'update:page', value: number): void
  (e: 'update:size', value: number): void
}>()

const numbers = computed(() => {
  const out: number[] = []
  const start = Math.max(1, props.page - 2)
  const end = Math.min(props.pages, start + 4)
  for (let i = start; i <= end; i++) out.push(i)
  return out
})
</script>

<template>
  <div class="pager">
    <span class="pager-total">共 {{ total }} 条 / {{ pages }} 页</span>
    <select
      class="pager-size"
      :value="size"
      @change="emit('update:size', Number(($event.target as HTMLSelectElement).value))"
    >
      <option v-for="n in [5, 10, 20]" :key="n" :value="n">{{ n }} 条/页</option>
    </select>
    <button class="btn btn-sm" :disabled="page <= 1" @click="emit('update:page', page - 1)">上一页</button>
    <button
      v-for="n in numbers"
      :key="n"
      class="btn btn-sm"
      :class="{ 'btn-primary': n === page }"
      @click="emit('update:page', n)"
    >
      {{ n }}
    </button>
    <button class="btn btn-sm" :disabled="page >= pages" @click="emit('update:page', page + 1)">下一页</button>
  </div>
</template>
