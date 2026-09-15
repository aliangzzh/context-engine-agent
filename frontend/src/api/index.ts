// API 客户端：统一响应体解包 + 错误码 + 各业务接口。
//
// 后端约定（见 backend/app/errors.py）：
//   { code: 0, msg: "ok", data: {...} }        成功
//   { code: 40001, msg: "...", data: null }    失败（code 用来做业务分支）
// 所以这一层负责：fetch -> 解包 data -> 非 0 code 抛 ApiError（带 code/msg/detail）。
// 页面只管 catch 后展示 e.message，不用关心 HTTP 状态码和 envelope 结构。

const BASE = '/api'

export interface ApiEnvelope<T> {
  code: number
  msg: string
  data: T
  detail?: unknown
}

export class ApiError extends Error {
  code: number
  detail?: unknown
  status: number

  constructor(code: number, message: string, status = 0, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.detail = detail
    this.status = status
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(url, init)
  } catch (e: any) {
    throw new ApiError(-1, `网络请求失败：${e?.message || '未知错误'}`, 0)
  }
  let body: ApiEnvelope<T> | null = null
  const text = await resp.text()
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      throw new ApiError(-2, `响应不是合法 JSON（HTTP ${resp.status}）`, resp.status)
    }
  }
  if (!body) {
    throw new ApiError(-2, `空响应（HTTP ${resp.status}）`, resp.status)
  }
  if (body.code !== 0) {
    throw new ApiError(body.code, body.msg || `请求失败(HTTP ${resp.status})`, resp.status, body.detail)
  }
  return body.data
}

const jsonInit = (method: string, payload: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
})

// --- 类型 -------------------------------------------------------------------------
export interface TraceStep {
  node: string
  kind: string
  summary: string
  detail: Record<string, any>
  ts: string
}

export interface ContextSlot {
  kind: string
  content: string
  priority: number
  tokens: number
}

export interface ContextPayload {
  slots: ContextSlot[]
  total_tokens: number
  budget: number
  trimmed: number
  over_budget: boolean
}

export interface StreamDone {
  answer: string
  context: ContextPayload
  trace: TraceStep[]
  used_tools: string[]
  backend: string
}

export interface Health {
  status: 'ok'
  chat_backend: string
  retrieval_backend: string
  model: string
  db_backend: string
  cache_backend: string
}

export interface KbSource {
  source: string
  chunks: number
  created_at: string
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  size: number
  pages: number
}

export interface IngestResult {
  status: string
  chunks: number
  filename: string
  reason: string
}

export interface FeedbackItem {
  id: number
  session_id: string
  message: string
  answer: string
  reason: string
  note: string
  created_at: string
}

export interface StatsPayload {
  kb: { chunks: number; sources: number; chunk_lengths: { bucket: string; count: number }[] }
  feedback: { total: number; distribution: { reason: string; count: number }[] }
  requests: {
    requests: number
    avg_ms: number
    p95_ms: number
    avg_tokens: number
    max_tokens: number
    budget: number
    tool_calls: Record<string, number>
    series: { ts: string; tokens: number; budget: number; ms: number; over_budget: boolean }[]
  }
  runtime: Record<string, string | number>
}

export const FEEDBACK_REASONS = [
  { value: 'answer_wrong', label: '答案不对' },
  { value: 'hallucination', label: '幻觉/编造' },
  { value: 'missing_kb', label: '知识库缺失' },
  { value: 'too_slow', label: '太慢' },
  { value: 'other', label: '其它' },
]

// --- 接口 -------------------------------------------------------------------------
export const health = () => request<Health>('/health')
export const stats = () => request<StatsPayload>(`${BASE}/stats`)

export const kbList = (page = 1, size = 10, q = '') =>
  request<PageResult<KbSource>>(`${BASE}/kb/list?page=${page}&size=${size}&q=${encodeURIComponent(q)}`)

export const kbIngest = (text: string, filename: string) =>
  request<IngestResult>(`${BASE}/kb/ingest`, jsonInit('POST', { text, filename }))

export const kbDelete = (source: string) =>
  request<{ source: string; deleted_chunks: number }>(`${BASE}/kb/${encodeURIComponent(source)}`, { method: 'DELETE' })

export async function kbUpload(file: File): Promise<IngestResult> {
  const form = new FormData()
  form.append('file', file) // 浏览器自动带上 multipart boundary
  return request<IngestResult>(`${BASE}/kb/upload`, { method: 'POST', body: form })
}

export const feedbackCreate = (payload: {
  session_id: string
  message: string
  answer: string
  reason: string
  note?: string
}) => request<{ created_at: string }>(`${BASE}/feedback`, jsonInit('POST', payload))

export const feedbackList = (page = 1, size = 10) =>
  request<PageResult<FeedbackItem>>(`${BASE}/feedback?page=${page}&size=${size}`)

export const contextOf = (sessionId: string) =>
  request<{ session_id: string; turns: number; history: { user: string; assistant: string }[] }>(
    `${BASE}/context/${encodeURIComponent(sessionId)}`,
  )

export const chatOnce = (message: string, sessionId: string) =>
  request<{ answer: string; context: ContextPayload; agent_trace: TraceStep[]; used_tools: string[] }>(
    `${BASE}/chat`,
    jsonInit('POST', { message, session_id: sessionId, stream: false }),
  )

// Stream an SSE chat. Callbacks fire for each event type.
// 注意：SSE 不是 envelope 结构，是逐条事件（agent/token/retrieved/done/error）。
export async function streamChat(
  message: string,
  sessionId: string,
  onAgent: (s: TraceStep) => void,
  onToken: (t: string) => void,
  onDone: (d: StreamDone) => void,
  onRetrieved: (docs: any[]) => void,
  onError?: (code: number, msg: string) => void,
): Promise<void> {
  const res = await fetch(`${BASE}/chat/stream`, jsonInit('POST', { message, session_id: sessionId, stream: true }))
  if (!res.ok && res.headers.get('content-type')?.includes('application/json')) {
    const body = await res.json()
    throw new ApiError(body.code ?? -3, body.msg || `请求失败(${res.status})`, res.status, body.detail)
  }
  if (!res.body) throw new ApiError(-3, '浏览器不支持流式响应')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      const line = raw.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      let evt: any
      try {
        evt = JSON.parse(line.slice(6))
      } catch {
        continue
      }
      if (evt.type === 'agent') onAgent(evt.data)
      else if (evt.type === 'token') onToken(evt.data)
      else if (evt.type === 'retrieved') onRetrieved(evt.data)
      else if (evt.type === 'done') onDone(evt.data)
      else if (evt.type === 'error') onError?.(evt.data?.code ?? -4, evt.data?.msg ?? '服务端流式错误')
    }
  }
}
