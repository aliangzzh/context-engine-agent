<script setup lang="ts">
// 柱状图（纯 SVG，不依赖 ECharts）：用于 token 占用、badcase 分布、分块长度分布。
import { computed } from 'vue'

export interface BarDatum {
  label: string
  value: number
  hint?: string
}

const props = withDefaults(defineProps<{ data: BarDatum[]; height?: number; color?: string; unit?: string }>(), {
  height: 180,
  color: '#4f7cff',
  unit: '',
})

const max = computed(() => Math.max(1, ...props.data.map((d) => d.value)))
const barWidth = computed(() => (props.data.length ? Math.min(48, 520 / props.data.length) : 24))
const gap = computed(() => (props.data.length ? 16 : 0))
const width = computed(() => Math.max(240, props.data.length * (barWidth.value + gap.value) + 40))
const plotHeight = computed(() => props.height - 42)

function barHeight(v: number) {
  return Math.max(2, Math.round((v / max.value) * plotHeight.value))
}
</script>

<template>
  <div class="chart">
    <svg :viewBox="`0 0 ${width} ${height}`" :height="height" preserveAspectRatio="xMinYMin meet">
      <line x1="20" :y1="plotHeight" :x2="width - 10" :y2="plotHeight" stroke="#d9dee8" />
      <g v-for="(d, i) in data" :key="d.label">
        <rect
          :x="28 + i * (barWidth + gap)"
          :y="plotHeight - barHeight(d.value)"
          :width="barWidth"
          :height="barHeight(d.value)"
          :fill="color"
          rx="4"
        >
          <title>{{ d.label }}：{{ d.value }}{{ unit }}{{ d.hint ? '（' + d.hint + '）' : '' }}</title>
        </rect>
        <text
          :x="28 + i * (barWidth + gap) + barWidth / 2"
          :y="plotHeight - barHeight(d.value) - 6"
          text-anchor="middle"
          class="chart-value"
        >
          {{ d.value }}
        </text>
        <text
          :x="28 + i * (barWidth + gap) + barWidth / 2"
          :y="plotHeight + 16"
          text-anchor="middle"
          class="chart-label"
        >
          {{ d.label.length > 8 ? d.label.slice(0, 7) + '…' : d.label }}
        </text>
      </g>
      <text v-if="!data.length" x="50%" :y="plotHeight / 2" text-anchor="middle" class="chart-label">暂无数据</text>
    </svg>
  </div>
</template>
