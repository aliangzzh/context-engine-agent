// 列表分页：请求 -> 加载态 -> 翻页/改页大小/刷新。
import { computed, ref } from 'vue'
import type { PageResult } from '../api'

export function usePagination<T>(
  loader: (page: number, size: number) => Promise<PageResult<T>>,
  options: { size?: number; immediate?: boolean } = {},
) {
  const page = ref(1)
  const size = ref(options.size ?? 10)
  const total = ref(0)
  const pages = ref(1)
  const items = ref<T[]>([]) as { value: T[] }
  const loading = ref(false)
  const error = ref('')

  async function load(target = page.value) {
    loading.value = true
    error.value = ''
    try {
      const res = await loader(target, size.value)
      items.value = res.items
      total.value = res.total
      pages.value = res.pages
      page.value = res.page
    } catch (e: any) {
      error.value = e?.message || '加载失败'
      items.value = []
      total.value = 0
    } finally {
      loading.value = false
    }
  }

  function go(target: number) {
    const clamped = Math.min(Math.max(1, target), Math.max(1, pages.value))
    if (clamped === page.value) return load(clamped)
    page.value = clamped
    return load(clamped)
  }

  const canPrev = computed(() => page.value > 1)
  const canNext = computed(() => page.value < pages.value)

  if (options.immediate !== false) void load(1)

  return {
    page, size, total, pages, items, loading, error,
    load, go, reload: () => load(page.value),
    next: () => (canNext.value ? go(page.value + 1) : Promise.resolve()),
    prev: () => (canPrev.value ? go(page.value - 1) : Promise.resolve()),
    setSize: (n: number) => { size.value = n; return go(1) },
    canPrev, canNext,
  }
}
