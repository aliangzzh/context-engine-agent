// 跨页面共享的会话状态（模块级 ref，等价于一个极简 store）。
import { ref } from 'vue'
import { health } from '../api'

export const sessionId = ref(localStorage.getItem('sessionId') || 'default')
export const backendLabel = ref('连接中…')
export const storageLabel = ref('')
//: 徽章 hover 说明（降级原因）与是否需要标黄告警
export const healthNote = ref('')
export const healthDegraded = ref(false)

export function setSessionId(id: string) {
  sessionId.value = id || 'default'
  localStorage.setItem('sessionId', sessionId.value)
}

export async function refreshHealth() {
  try {
    const h = await health()
    // 徽章必须显示**实际生效**的后端：`chat_backend` / `retrieval_backend` 只是"配置层意愿"。
    // 只填了 .env 的 key、却没装 requirements-llm.txt 时会静默退回离线模型，
    // 而徽章照样写着 qwen_api（踩过这个坑），所以这里以 model / retrieval_effective 为准。
    const chat = h.model || h.chat_backend
    const chatDegraded = chat === 'fake' && h.chat_backend !== 'fake'
    const retrieval = h.retrieval_effective || h.retrieval_backend
    const retrievalDegraded = retrieval === 'bm25' && h.retrieval_backend !== 'bm25'

    backendLabel.value = [
      chatDegraded ? `${chat}（配置 ${h.chat_backend} 未生效）` : chat,
      retrievalDegraded ? `${retrieval}（配置 ${h.retrieval_backend} 降级）` : retrieval,
    ].join(' / ')
    storageLabel.value = `${h.db_backend} + ${h.cache_backend}`
    healthDegraded.value = chatDegraded || retrievalDegraded
    if (chatDegraded) {
      healthNote.value =
        (h.chat_degraded_reason || '真模型没起来，已退回离线回放模型') +
        '\n修复：pip install -r requirements-llm.txt，并用 .venv\\Scripts\\python.exe 启动'
    } else if (retrievalDegraded) {
      healthNote.value = '向量索引不可用或与语料不一致，已自动降级 BM25（/health 的 vector_index 有原因）'
    } else {
      healthNote.value = '后端实际生效的组合（不是配置层意愿）'
    }
    return h
  } catch {
    backendLabel.value = '后端未连接（在 backend/ 下运行 python run.py）'
    storageLabel.value = ''
    healthDegraded.value = true
    healthNote.value = '后端没起来：在 backend/ 用 .venv\\Scripts\\python.exe run.py 启动'
    return null
  }
}
