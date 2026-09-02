<script setup lang="ts">
import { onMounted, ref } from 'vue'
import ContextPanel from './components/ContextPanel.vue'
import AgentPanel from './components/AgentPanel.vue'
import { streamChat, health, ingest, type TraceStep, type ContextPayload, type StreamDone } from './api'

interface Msg { role: 'user' | 'assistant'; content: string }

const messages = ref<Msg[]>([])
const input = ref('')
const sessionId = ref('default')
const backend = ref('')
const streaming = ref(false)
const error = ref('')
const context = ref<ContextPayload | null>(null)
const trace = ref<TraceStep[]>([])
const usedTools = ref<string[]>([])
const retrievedCount = ref(0)

onMounted(async () => {
  try {
    const h = await health()
    backend.value = `${h.chat_backend} / ${h.retrieval_backend}`
  } catch (e) {
    error.value = '后端未连接，请先运行 uvicorn'
  }
})

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value) return
  error.value = ''
  messages.value.push({ role: 'user', content: text })
  input.value = ''
  trace.value = []
  context.value = null
  usedTools.value = []
  retrievedCount.value = 0

  const assistant: Msg = { role: 'assistant', content: '' }
  messages.value.push(assistant)
  streaming.value = true

  try {
    await streamChat(
      text,
      sessionId.value,
      (s) => trace.value.push(s),
      (t) => { assistant.content += t },
      (d: StreamDone) => {
        context.value = d.context
        usedTools.value = d.usedTools
        backend.value = d.backend
      },
      (docs) => { retrievedCount.value = docs.length },
    )
  } catch (e: any) {
    error.value = '请求失败：' + (e?.message || '未知错误')
  } finally {
    streaming.value = false
  }
}
</script>

<template>
  <div class="layout">
    <header>
      <div class="brand">
        <span class="logo">🧠</span>
        <div>
          <h1>Context Engine + Multi-Agent QA</h1>
          <p class="sub">上下文引擎 · 多 Agent 协作 · RAG · LoRA 微调</p>
        </div>
      </div>
      <div class="badges">
        <span class="badge">{{ backend || 'connecting…' }}</span>
        <button class="suggest" @click="input = '针织毛衣如何保养？'">示例：毛衣保养</button>
      </div>
    </header>

    <main>
      <section class="chat">
        <div class="messages">
          <div v-if="messages.length === 0" class="hint">
            输入一个知识类问题（如「毛衣怎么洗？」）或调用工具（如「上海天气」「3*4+2」），
            观察左侧的多 Agent 协作链与右侧的上下文分配。
          </div>
          <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
            <div class="bubble">{{ m.content }}</div>
          </div>
        </div>

        <div class="inputbar">
          <textarea
            v-model="input"
            rows="1"
            placeholder="输入问题（如：尺码推荐 / 上海天气 / 计算 3*4+2）"
            @keydown.enter.exact.prevent="send"
          />
          <button class="send" :disabled="streaming" @click="send">
            {{ streaming ? '…' : '发送' }}
          </button>
        </div>
        <p v-if="error" class="error">{{ error }}</p>
      </section>

      <aside class="side">
        <div class="tabbar">
          <span class="tab active">上下文</span>
          <span class="tab">Agent 链</span>
        </div>
        <div class="panels">
          <ContextPanel :context="context" />
          <AgentPanel :trace="trace" :used-tools="usedTools" :backend="backend" />
        </div>
      </aside>
    </main>
  </div>
</template>

<style scoped>
.layout { display: flex; flex-direction: column; height: 100vh; }

header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 22px; border-bottom: 1px solid var(--border); background: var(--panel);
}
.brand { display: flex; align-items: center; gap: 12px; }
.logo { font-size: 28px; }
h1 { margin: 0; font-size: 18px; color: var(--text); }
.sub { margin: 2px 0 0; font-size: 12px; color: var(--muted); }
.badges { display: flex; gap: 10px; align-items: center; }
.badge { font-size: 12px; background: var(--panel2); border: 1px solid var(--border); padding: 4px 10px; border-radius: 12px; color: var(--accent2); }
.suggest { font-size: 12px; background: #2a3355; color: var(--text); border: none; border-radius: 8px; padding: 6px 10px; cursor: pointer; }
.suggest:hover { background: #33406b; }

main { display: flex; flex: 1; overflow: hidden; }
.chat { flex: 1; display: flex; flex-direction: column; border-right: 1px solid var(--border); }
.messages { flex: 1; overflow-y: auto; padding: 22px; display: flex; flex-direction: column; gap: 14px; }
.hint { color: var(--muted); font-size: 13px; line-height: 1.7; max-width: 460px; }
.msg { display: flex; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 70ch; padding: 10px 14px; border-radius: 14px; font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
.msg.user .bubble { background: var(--accent); color: #fff; border-bottom-right-radius: 4px; }
.msg.assistant .bubble { background: var(--panel2); border: 1px solid var(--border); border-bottom-left-radius: 4px; }

.inputbar { display: flex; gap: 10px; padding: 14px 22px; background: var(--panel); border-top: 1px solid var(--border); }
textarea { flex: 1; resize: none; background: var(--panel2); color: var(--text); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; font-size: 14px; min-height: 42px; }
textarea:focus { outline: none; border-color: var(--accent); }
.send { background: var(--accent); color: #fff; border: none; border-radius: 10px; padding: 0 20px; font-size: 14px; cursor: pointer; }
.send:disabled { opacity: .5; cursor: not-allowed; }
.error { color: #ff7b7b; font-size: 12px; padding: 0 22px; margin: 0 0 8px; }

.side { width: 400px; display: flex; flex-direction: column; background: var(--panel); }
.tabbar { display: flex; gap: 8px; padding: 12px 16px 0; }
.tab { font-size: 13px; color: var(--muted); padding: 6px 12px; border-radius: 8px 8px 0 0; }
.tab.active { color: var(--accent); background: var(--panel2); }
.panels { flex: 1; overflow-y: auto; padding: 14px 16px; display: flex; flex-direction: column; gap: 20px; }

@media (max-width: 900px) {
  .side { display: none; }
}
</style>
