<script setup lang="ts">
// 对话页：SSE 流式渲染 + 上下文面板 + Agent 协作链 + badcase 反馈（弹窗 + 表单校验）。
import { computed, ref } from 'vue'
import AgentPanel from '../components/AgentPanel.vue'
import ContextPanel from '../components/ContextPanel.vue'
import FormField from '../components/FormField.vue'
import Modal from '../components/Modal.vue'
import { FEEDBACK_REASONS, feedbackCreate, streamChat, type ContextPayload, type StreamDone, type TraceStep } from '../api'
import { maxLen, required, useForm } from '../composables/useForm'
import { backendLabel, sessionId } from '../composables/useSession'

interface Msg {
  role: 'user' | 'assistant'
  content: string
}

const messages = ref<Msg[]>([])
const input = ref('')
const streaming = ref(false)
const error = ref('')
const context = ref<ContextPayload | null>(null)
const trace = ref<TraceStep[]>([])
const usedTools = ref<string[]>([])
const retrievedCount = ref(0)

// --- badcase 反馈 -----------------------------------------------------------------
const feedbackOpen = ref(false)
const feedbackTarget = ref<{ message: string; answer: string } | null>(null)
const feedbackMsg = ref('')
const feedbackForm = useForm({
  reason: { label: '问题类型', rules: [required('请选择问题类型')] },
  note: { label: '补充说明', rules: [maxLen(200)] },
})

function openFeedback(index: number) {
  const answer = messages.value[index]
  const question = messages.value[index - 1]
  feedbackTarget.value = { message: question?.content || '', answer: answer?.content || '' }
  feedbackForm.reset({ reason: '', note: '' })
  feedbackMsg.value = ''
  feedbackOpen.value = true
}

async function submitFeedback() {
  if (!feedbackForm.validate() || !feedbackTarget.value) return
  feedbackForm.submitting.value = true
  try {
    await feedbackCreate({
      session_id: sessionId.value,
      message: feedbackTarget.value.message,
      answer: feedbackTarget.value.answer,
      reason: feedbackForm.values.reason,
      note: feedbackForm.values.note,
    })
    feedbackMsg.value = '已记录，可在「看板」页看到这条 badcase 的统计。'
    setTimeout(() => (feedbackOpen.value = false), 900)
  } catch (e: any) {
    feedbackMsg.value = `提交失败：${e?.message || '未知错误'}`
  } finally {
    feedbackForm.submitting.value = false
  }
}

// --- 对话 -------------------------------------------------------------------------
const canSend = computed(() => input.value.trim().length > 0 && !streaming.value)

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
        usedTools.value = d.used_tools
      },
      (docs) => { retrievedCount.value = docs.length },
      (code, msg) => { error.value = `服务端错误(${code})：${msg}` },
    )
  } catch (e: any) {
    error.value = `请求失败：${e?.message || '未知错误'}`
    if (!assistant.content) assistant.content = '（没有收到回答）'
  } finally {
    streaming.value = false
  }
}
</script>

<template>
  <div class="chat-page">
    <section class="chat">
      <div class="messages">
        <div v-if="messages.length === 0" class="hint">
          输入一个知识类问题（如「毛衣怎么洗？」）或调用工具（如「上海天气」「计算 3*4+2」），
          右侧会显示本次的上下文分配与 Agent 协作链。回答不对时可以点「标记问题」，
          这条 badcase 会进反馈库并在看板里统计。
        </div>
        <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
          <div class="bubble">
            {{ m.content }}
            <div v-if="m.role === 'assistant' && m.content && !streaming" class="msg-actions">
              <button class="link-btn" @click="openFeedback(i)">标记问题</button>
            </div>
          </div>
        </div>
      </div>

      <div class="inputbar">
        <textarea
          v-model="input"
          rows="1"
          placeholder="输入问题（如：尺码推荐 / 上海天气 / 计算 3*4+2）"
          @keydown.enter.exact.prevent="send"
        />
        <button class="send" :disabled="!canSend" @click="send">{{ streaming ? '…' : '发送' }}</button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
    </section>

    <aside class="side">
      <div class="tabbar">
        <span class="tab active">上下文</span>
        <span class="tab">Agent 链</span>
        <span class="badge">检索 {{ retrievedCount }} 条</span>
      </div>
      <div class="panels">
        <ContextPanel :context="context" />
        <AgentPanel :trace="trace" :used-tools="usedTools" :backend="backendLabel" />
      </div>
    </aside>

    <Modal :open="feedbackOpen" title="标记这条回答有问题（badcase）" @close="feedbackOpen = false">
      <p class="modal-sub">问题：{{ feedbackTarget?.message }}</p>
      <p class="modal-sub muted">回答：{{ feedbackTarget?.answer?.slice(0, 120) }}</p>

      <label class="form-row">
        <span class="form-label">问题类型</span>
        <select v-model="feedbackForm.values.reason" class="input" @blur="feedbackForm.touch('reason')">
          <option value="">请选择</option>
          <option v-for="r in FEEDBACK_REASONS" :key="r.value" :value="r.value">{{ r.label }}</option>
        </select>
        <small v-if="feedbackForm.touched.reason && feedbackForm.errors.reason" class="form-error">
          {{ feedbackForm.errors.reason }}
        </small>
      </label>

      <FormField
        v-model="feedbackForm.values.note"
        label="补充说明（选填，≤200 字）"
        type="textarea"
        :rows="3"
        placeholder="例如：检索到了文档但回答里数字错了"
        :error="feedbackForm.errors.note"
        :touched="feedbackForm.touched.note"
        @blur="feedbackForm.touch('note')"
      />

      <p v-if="feedbackMsg" class="form-hint">{{ feedbackMsg }}</p>

      <template #footer>
        <button class="btn" @click="feedbackOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="feedbackForm.submitting.value" @click="submitFeedback">
          提交反馈
        </button>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
.chat-page { display: flex; flex: 1; overflow: hidden; }
.chat { flex: 1; display: flex; flex-direction: column; border-right: 1px solid var(--border); min-width: 0; }
.messages { flex: 1; overflow-y: auto; padding: 22px; display: flex; flex-direction: column; gap: 14px; }
.hint { color: var(--muted); font-size: 13px; line-height: 1.8; max-width: 520px; }
.msg { display: flex; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 70ch; padding: 10px 14px; border-radius: 14px; font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
.msg.user .bubble { background: var(--accent); color: #fff; border-bottom-right-radius: 4px; }
.msg.assistant .bubble { background: var(--panel2); border: 1px solid var(--border); border-bottom-left-radius: 4px; }
.msg-actions { margin-top: 8px; }
.link-btn { background: none; border: none; color: var(--muted); font-size: 12px; cursor: pointer; padding: 0; text-decoration: underline; }
.link-btn:hover { color: var(--accent2); }

.inputbar { display: flex; gap: 10px; padding: 14px 22px; background: var(--panel); border-top: 1px solid var(--border); }
.inputbar textarea { flex: 1; resize: none; background: var(--panel2); color: var(--text); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; font-size: 14px; min-height: 42px; }
.inputbar textarea:focus { outline: none; border-color: var(--accent); }
.send { background: var(--accent); color: #fff; border: none; border-radius: 10px; padding: 0 20px; font-size: 14px; cursor: pointer; }
.send:disabled { opacity: 0.5; cursor: not-allowed; }
.error { color: #ff7b7b; font-size: 12px; padding: 0 22px; margin: 0 0 8px; }

.side { width: 400px; display: flex; flex-direction: column; background: var(--panel); }
.tabbar { display: flex; gap: 10px; align-items: center; padding: 12px 16px 0; }
.tab { font-size: 13px; color: var(--muted); padding: 6px 12px; border-radius: 8px 8px 0 0; }
.tab.active { color: var(--accent); background: var(--panel2); }
.panels { flex: 1; overflow-y: auto; padding: 14px 16px; display: flex; flex-direction: column; gap: 20px; }
.modal-sub { font-size: 13px; margin: 0 0 6px; color: var(--text); }

@media (max-width: 900px) {
  .side { display: none; }
}
</style>
