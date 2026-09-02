<script setup lang="ts">
import type { TraceStep } from '../api'

defineProps<{
  trace: TraceStep[]
  usedTools: string[]
  backend: string
}>()

const kindIcon: Record<string, string> = {
  router: '🔀',
  retrieve: '📚',
  tool: '🔧',
  writer: '✍️',
  direct: '➡️',
}
</script>

<template>
  <div class="panel">
    <div class="head">
      <h3>多 Agent 协作链</h3>
      <span class="backend">后端：{{ backend }}</span>
    </div>

    <div v-if="trace.length === 0" class="empty">发送消息查看 Agent 路由与执行链。</div>

    <ol class="steps">
      <li v-for="(s, i) in trace" :key="i" class="step">
        <div class="step-head">
          <span class="icon">{{ kindIcon[s.kind] || '·' }}</span>
          <span class="node">{{ s.node }}</span>
          <span class="summary">{{ s.summary }}</span>
        </div>
        <div v-for="(v, k) in s.detail" :key="k" class="detail">
          <span class="k">{{ k }}</span>
          <span class="v">{{ pretty(v) }}</span>
        </div>
      </li>
    </ol>

    <div v-if="usedTools.length" class="tools">
      <span class="t-label">已用工具</span>
      <span v-for="(t, i) in usedTools" :key="i" class="tool">{{ t }}</span>
    </div>
  </div>
</template>

<script lang="ts">
export default {
  methods: {
    pretty(v: any): string {
      if (Array.isArray(v)) return v.join(', ')
      return String(v)
    },
  },
}
</script>

<style scoped>
.panel { display: flex; flex-direction: column; gap: 10px; }
.head { display: flex; justify-content: space-between; align-items: center; }
h3 { margin: 0; font-size: 15px; color: var(--accent); }
.backend { font-size: 11px; color: var(--muted); background: var(--panel2); padding: 2px 8px; border-radius: 10px; }
.empty { color: var(--muted); font-size: 13px; }

.steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.step { background: var(--panel2); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; }
.step-head { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.icon { font-size: 16px; }
.node { font-weight: 600; color: var(--accent2); }
.summary { color: var(--muted); font-size: 12px; }
.detail { margin-top: 5px; font-size: 11px; display: flex; gap: 6px; color: var(--muted); }
.k { color: #7c86ab; }
.v { color: #cfd6ee; }

.tools { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.t-label { font-size: 12px; color: var(--muted); }
.tool { font-size: 11px; background: #23425f; color: #9ed3ff; padding: 2px 8px; border-radius: 10px; }
</style>
