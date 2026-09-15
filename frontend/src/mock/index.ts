// Mock 数据开关：接口没就绪时先把页面流程跑通。
//
// 三种打开方式：
//   1) 构建时：VITE_USE_MOCK=1 npm run build
//   2) 运行时：页面右上角勾选「Mock 数据」（写入 localStorage）
//   3) 控制台：localStorage.setItem('useMock', '1')
//
// 打开后，页面照常调用 api 层，但数据来自这里的假数据 —— 组件、分页、校验、
// 图表渲染路径全部走通，等后端接口 ready 只需要把开关关掉。
import { ref } from 'vue'
import type { FeedbackItem, KbSource, PageResult, StatsPayload } from '../api'

const KEY = 'useMock'

export const useMock = ref(
  (import.meta.env.VITE_USE_MOCK as string | undefined) === '1' || localStorage.getItem(KEY) === '1',
)

export function setMock(on: boolean) {
  useMock.value = on
  if (on) localStorage.setItem(KEY, '1')
  else localStorage.removeItem(KEY)
}

function paginate<T>(items: T[], page: number, size: number): PageResult<T> {
  const start = (page - 1) * size
  return {
    items: items.slice(start, start + size),
    total: items.length,
    page,
    size,
    pages: Math.max(1, Math.ceil(items.length / size)),
  }
}

const MOCK_SOURCES: KbSource[] = Array.from({ length: 23 }, (_, i) => ({
  source: `示例文档-${String(i + 1).padStart(2, '0')}.txt`,
  chunks: 1 + (i % 4),
  created_at: `2026-09-${String(10 + (i % 5)).padStart(2, '0')} 10:${String(i * 2).padStart(2, '0')}:00`,
}))

export function mockKbList(page = 1, size = 10, q = ''): PageResult<KbSource> {
  const filtered = q ? MOCK_SOURCES.filter((s) => s.source.includes(q)) : MOCK_SOURCES
  return paginate(filtered, page, size)
}

export function mockFeedbackList(page = 1, size = 10): PageResult<FeedbackItem> {
  const reasons = ['answer_wrong', 'hallucination', 'missing_kb', 'too_slow', 'other']
  const items: FeedbackItem[] = Array.from({ length: 17 }, (_, i) => ({
    id: 100 - i,
    session_id: `mock-${i % 3}`,
    message: `示例问题 ${i + 1}：这个材质能不能机洗？`,
    answer: '【Mock】这是一条用于联调的假回答。',
    reason: reasons[i % reasons.length],
    note: i % 3 === 0 ? '边界问题' : '',
    created_at: `2026-09-14 1${i % 10}:0${i % 6}:00`,
  }))
  return paginate(items, page, size)
}

export function mockStats(): StatsPayload {
  const series = Array.from({ length: 12 }, (_, i) => ({
    ts: `10:${String(i * 3).padStart(2, '0')}:00`,
    tokens: 260 + ((i * 97) % 420),
    budget: 4096,
    ms: 180 + ((i * 53) % 700),
    over_budget: false,
  }))
  return {
    kb: {
      chunks: MOCK_SOURCES.reduce((n, s) => n + s.chunks, 0),
      sources: MOCK_SOURCES.length,
      chunk_lengths: [
        { bucket: '0-100', count: 8 },
        { bucket: '100-200', count: 15 },
        { bucket: '200-300', count: 11 },
        { bucket: '300-500', count: 6 },
        { bucket: '500+', count: 2 },
      ],
    },
    feedback: {
      total: 17,
      distribution: [
        { reason: 'answer_wrong', count: 4 },
        { reason: 'hallucination', count: 6 },
        { reason: 'missing_kb', count: 5 },
        { reason: 'too_slow', count: 1 },
        { reason: 'other', count: 1 },
      ],
    },
    requests: {
      requests: 12,
      avg_ms: 421.5,
      p95_ms: 880,
      avg_tokens: 388.4,
      max_tokens: 641,
      budget: 4096,
      tool_calls: { get_weather: 3, calculator: 1 },
      series,
    },
    runtime: {
      chat_backend: 'fake(mock)',
      retrieval_backend: 'bm25',
      db_backend: 'sqlite',
      cache_backend: 'lru',
      context_budget: 4096,
      top_k: 3,
      chunk_size: 500,
      chunk_strategy: 'sentence',
    },
  }
}
