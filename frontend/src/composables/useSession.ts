// 跨页面共享的会话状态（模块级 ref，等价于一个极简 store）。
import { ref } from 'vue'
import { health } from '../api'

export const sessionId = ref(localStorage.getItem('sessionId') || 'default')
export const backendLabel = ref('连接中…')
export const storageLabel = ref('')

export function setSessionId(id: string) {
  sessionId.value = id || 'default'
  localStorage.setItem('sessionId', sessionId.value)
}

export async function refreshHealth() {
  try {
    const h = await health()
    backendLabel.value = `${h.chat_backend} / ${h.retrieval_backend}`
    storageLabel.value = `${h.db_backend} + ${h.cache_backend}`
    return h
  } catch {
    backendLabel.value = '后端未连接（先在 backend/ 运行 python run.py）'
    storageLabel.value = ''
    return null
  }
}
