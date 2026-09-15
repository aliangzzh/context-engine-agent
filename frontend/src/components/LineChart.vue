<script setup lang="ts">
// 折线图（纯 SVG）：用于最近若干次请求的 token 占用趋势 / 耗时趋势。
import { computed } from 'vue'

export interface LinePoint {
  label: string
  value: number
}

const props = withDefaults(
  defineProps<{
    data: LinePoint[]
    height?: number
    color?: string
    /** 参考线（例如 token 预算），画一条虚线 */
    reference?: number
    unit?: string
  }>(),
  { height: 190, color: '#22a06b', unit: '' },
)

const padLeft = 42
const padBottom = 26
const width = computed(() => Math.max(320, props.data.length * 44 + padLeft + 16))
const plotHeight = computed(() => props.height - padBottom - 12)
const max = computed(() => {
  const values = props.data.map((d) => d.value)
  if (props.reference) values.push(props.reference)
  return Math.max(1, ...values)
})

function x(i: number) {
  if (props.data.length <= 1) return padLeft + 20
  return padLeft + (i * (width.value - padLeft - 20)) / (props.data.length - 1)
}
function y(v: number) {
  return 12 + plotHeight.value - (v / max.value) * plotHeight.value
}
const path = computed(() => props.data.map((d, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(d.value)}`).join(' '))
const refY = computed(() => (props.reference ? y(props.reference) : 0))
</script>

<template>
  <div class="chart">
    <svg :viewBox="`0 0 ${width} ${height}`" :height="height" preserveAspectRatio="xMinYMin meet">
      <line :x1="padLeft" :y1="12 + plotHeight" :x2="width - 8" :y2="12 + plotHeight" stroke="#d9dee8" />
      <line :x1="padLeft" y1="12" :x2="padLeft" :y2="12 + plotHeight" stroke="#d9dee8" />
      <text :x="padLeft - 6" y="18" text-anchor="end" class="chart-label">{{ max }}</text>
      <text :x="padLeft - 6" :y="12 + plotHeight" text-anchor="end" class="chart-label">0</text>

      <g v-if="reference">
        <line :x1="padLeft" :y1="refY" :x2="width - 8" :y2="refY" stroke="#e08b3c" stroke-dasharray="4 4" />
        <text :x="width - 10" :y="refY - 4" text-anchor="end" class="chart-label">
          预算 {{ reference }}{{ unit }}
        </text>
      </g>

      <path :d="path" fill="none" :stroke="color" stroke-width="2" />
      <g v-for="(d, i) in data" :key="i">
        <circle :cx="x(i)" :cy="y(d.value)" r="3.5" :fill="color">
          <title>{{ d.label }}：{{ d.value }}{{ unit }}</title>
        </circle>
        <text :x="x(i)" :y="height - 8" text-anchor="middle" class="chart-label">{{ d.label }}</text>
      </g>
      <text v-if="!data.length" x="50%" :y="plotHeight / 2" text-anchor="middle" class="chart-label">暂无数据</text>
    </svg>
  </div>
</template>
