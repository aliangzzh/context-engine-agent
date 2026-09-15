<script setup lang="ts">
// 看板页：把「运行指标 / badcase 分布 / 分块长度分布 / 工具调用」画出来。
// 图表是自研 SVG 组件（本机装不了 ECharts）；数据全部来自 /api/stats 的真实统计。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import BarChart, { type BarDatum } from '../components/BarChart.vue'
import DataTable, { type Column } from '../components/DataTable.vue'
import LineChart, { type LinePoint } from '../components/LineChart.vue'
import Pagination from '../components/Pagination.vue'
import { FEEDBACK_REASONS, feedbackList, stats, type FeedbackItem, type StatsPayload } from '../api'
import { usePagination } from '../composables/usePagination'
import { mockFeedbackList, mockStats, useMock } from '../mock'

const data = ref<StatsPayload | null>(null)
const error = ref('')
const loading = ref(false)
let timer: number | undefined

async function load() {
  loading.value = true
  try {
    data.value = useMock.value ? mockStats() : await stats()
    error.value = ''
  } catch (e: any) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
  timer = window.setInterval(load, 5000)
})
onBeforeUnmount(() => window.clearInterval(timer))

const reasonLabel = (r: string) => FEEDBACK_REASONS.find((x) => x.value === r)?.label || r

const tokenSeries = computed<LinePoint[]>(
  () => data.value?.requests.series.map((s) => ({ label: s.ts.slice(0, 5), value: s.tokens })) || [],
)
const latencySeries = computed<LinePoint[]>(
  () => data.value?.requests.series.map((s) => ({ label: s.ts.slice(0, 5), value: s.ms })) || [],
)
const feedbackBars = computed<BarDatum[]>(
  () => data.value?.feedback.distribution.map((d) => ({ label: reasonLabel(d.reason), value: d.count })) || [],
)
const chunkBars = computed<BarDatum[]>(
  () => data.value?.kb.chunk_lengths.map((d) => ({ label: d.bucket, value: d.count })) || [],
)
const toolBars = computed<BarDatum[]>(
  () => Object.entries(data.value?.requests.tool_calls || {}).map(([label, value]) => ({ label, value })),
)

const columns: Column[] = [
  { key: 'created_at', label: '时间', width: '170px' },
  { key: 'reason', label: '类型', width: '110px' },
  { key: 'message', label: '用户问题' },
  { key: 'answer', label: '当时的回答' },
]
const feedbackPage = usePagination<FeedbackItem>(
  (p, s) => (useMock.value ? Promise.resolve(mockFeedbackList(p, s)) : feedbackList(p, s)),
  { size: 5 },
)

const runtime = computed(() => Object.entries(data.value?.runtime || {}))
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>运行看板</h2>
        <p class="muted">每 5 秒自动刷新；指标来自进程内采集 + SQL 聚合（换多实例部署时替换数据源即可）。</p>
      </div>
      <div class="page-actions">
        <button class="btn" :disabled="loading" @click="load">{{ loading ? '刷新中…' : '立即刷新' }}</button>
      </div>
    </div>

    <p v-if="error" class="alert alert-error">{{ error }}</p>

    <div class="cards">
      <div class="card"><span class="card-label">知识库分块</span><b>{{ data?.kb.chunks ?? '-' }}</b>
        <small>来源 {{ data?.kb.sources ?? '-' }} 个</small></div>
      <div class="card"><span class="card-label">badcase 总数</span><b>{{ data?.feedback.total ?? '-' }}</b>
        <small>来自对话页「标记问题」</small></div>
      <div class="card"><span class="card-label">平均耗时</span><b>{{ data?.requests.avg_ms ?? '-' }} ms</b>
        <small>p95 {{ data?.requests.p95_ms ?? '-' }} ms</small></div>
      <div class="card"><span class="card-label">平均 token</span><b>{{ data?.requests.avg_tokens ?? '-' }}</b>
        <small>峰值 {{ data?.requests.max_tokens ?? '-' }}</small></div>
      <div class="card"><span class="card-label">请求数</span><b>{{ data?.requests.requests ?? '-' }}</b>
        <small>最近 100 次滚动窗口</small></div>
    </div>

    <section class="panel">
      <h3>上下文 token 占用（最近请求，虚线为预算）</h3>
      <LineChart :data="tokenSeries" :reference="data?.requests.budget || 0" color="#4f7cff" unit=" tokens" />
    </section>

    <div class="grid-2">
      <section class="panel">
        <h3>badcase 类型分布</h3>
        <BarChart :data="feedbackBars" color="#e0574f" unit=" 条" />
      </section>
      <section class="panel">
        <h3>知识分块长度分布</h3>
        <BarChart :data="chunkBars" color="#22a06b" />
      </section>
    </div>

    <div class="grid-2">
      <section class="panel">
        <h3>工具调用次数</h3>
        <BarChart :data="toolBars" color="#8b5cf6" unit=" 次" />
      </section>
      <section class="panel">
        <h3>请求耗时（ms）</h3>
        <LineChart :data="latencySeries" color="#e08b3c" unit=" ms" />
      </section>
    </div>

    <section class="panel">
      <h3>最近 badcase</h3>
      <DataTable :columns="columns" :rows="feedbackPage.items.value" :loading="feedbackPage.loading.value" empty-text="还没有反馈，去对话页点「标记问题」试试">
        <template #cell-reason="{ value }">
          <span class="tag tag-danger">{{ reasonLabel(value) }}</span>
        </template>
        <template #cell-answer="{ value }">
          <span class="muted">{{ String(value).slice(0, 60) }}</span>
        </template>
      </DataTable>
      <Pagination
        :page="feedbackPage.page.value"
        :pages="feedbackPage.pages.value"
        :total="feedbackPage.total.value"
        :size="feedbackPage.size.value"
        @update:page="feedbackPage.go"
        @update:size="feedbackPage.setSize"
      />
    </section>

    <section class="panel">
      <h3>运行时配置</h3>
      <div class="kv">
        <div v-for="[k, v] in runtime" :key="k" class="kv-item">
          <span class="muted">{{ k }}</span><b>{{ v }}</b>
        </div>
      </div>
    </section>
  </div>
</template>
