<script setup lang="ts">
import { computed } from 'vue'
import type { ContextPayload } from '../api'

const props = defineProps<{ context: ContextPayload | null }>()

const usedPct = computed(() => {
  if (!props.context || !props.context.budget) return 0
  return Math.min(100, Math.round((props.context.total_tokens / props.context.budget) * 100))
})

const kindLabels: Record<string, string> = {
  system: '系统指令',
  summary: '摘要压缩',
  retrieval: '检索上下文',
  history: '对话历史',
  tool: '工具结果',
}
</script>

<template>
  <div class="panel">
    <h3>Context Engine 上下文分配</h3>

    <div v-if="!context" class="empty">
      发送消息后，这里展示模型实际拿到的上下文（各片段优先级与 token 用量）。
    </div>

    <template v-else>
      <div class="budget">
        <div class="bar">
          <div class="fill" :style="{ width: usedPct + '%' }"></div>
        </div>
        <div class="meta">
          <span>
            {{ context.total_tokens }} / {{ context.budget }} tokens
            <span v-if="context.trimmed > 0" class="trim">（裁剪 {{ context.trimmed }}）</span>
          </span>
          <span class="pct">{{ usedPct }}%</span>
        </div>
      </div>

      <div v-if="context.over_budget" class="note">
        ⚠️ 上下文超出预算：{{ context.total_tokens }} / {{ context.budget }} tokens（已裁剪 {{ context.trimmed }}）
      </div>

      <div class="slots">
        <div v-for="(s, i) in context.slots" :key="i" class="slot">
          <div class="slot-head">
            <span class="tag" :class="'t-' + s.kind">{{ kindLabels[s.kind] || s.kind }}</span>
            <span class="prio">prio {{ s.priority }}</span>
            <span class="tok">{{ s.tokens }} tok</span>
          </div>
          <div class="slot-body">{{ s.content }}</div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.panel { display: flex; flex-direction: column; gap: 12px; }
h3 { margin: 0 0 4px; font-size: 15px; color: var(--accent); }
.empty { color: var(--muted); font-size: 13px; line-height: 1.6; }

.budget { display: flex; flex-direction: column; gap: 6px; }
.bar { height: 10px; background: var(--panel2); border-radius: 6px; overflow: hidden; }
.fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent2)); transition: width .3s; }
.meta { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); }
.trim { color: #ff9a6b; }
.note { font-size: 12px; color: #ffb36b; background: #2a2415; padding: 8px 10px; border-radius: 8px; }

.slots { display: flex; flex-direction: column; gap: 8px; max-height: 420px; overflow: auto; }
.slot { background: var(--panel2); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; }
.slot-head { display: flex; gap: 8px; align-items: center; margin-bottom: 4px; font-size: 11px; }
.tag { padding: 1px 7px; border-radius: 4px; background: #2a3355; color: var(--text); }
.tag.t-retrieval { background: #23425f; color: #9ed3ff; }
.tag.t-history { background: #3a2a55; color: #c9a9ff; }
.tag.t-summary { background: #553a2a; color: #ffc9a9; }
.tag.t-tool { background: #2f5542; color: #a9ffcb; }
.prio { color: var(--muted); }
.tok { color: var(--muted); }
.slot-body { font-size: 12px; line-height: 1.5; color: #cfd6ee; max-height: 60px; overflow: hidden; }
</style>
