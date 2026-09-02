// API client: health + SSE streaming chat + ingestion.
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
}

export interface StreamDone {
  answer: string
  context: ContextPayload
  trace: TraceStep[]
  used_tools: string[]
  backend: string
}

const BASE = '/api'

export function health(): Promise<any> {
  return fetch('/health').then((r) => r.json())
}

export function ingest(text: string, filename: string): Promise<any> {
  return fetch(`${BASE}/kb/ingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, filename }),
  }).then((r) => r.json())
}

// Stream an SSE chat. Callbacks fire for each event type.
export async function streamChat(
  message: string,
  sessionId: string,
  onAgent: (s: TraceStep) => void,
  onToken: (t: string) => void,
  onDone: (d: StreamDone) => void,
  onRetrieved: (docs: any[]) => void,
): Promise<void> {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId, stream: true }),
  })
  if (!res.body) throw new Error('no stream')

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
      const evt = JSON.parse(line.slice(6))
      if (evt.type === 'agent') onAgent(evt.data)
      else if (evt.type === 'token') onToken(evt.data)
      else if (evt.type === 'retrieved') onRetrieved(evt.data)
      else if (evt.type === 'done') onDone(evt.data)
    }
  }
}
