<script setup lang="ts">
// 文件上传：点击选择 + 拖拽 + 前端校验 + 进度态。
//
// 校验分两层：这里做"格式/大小"的即时反馈（不用等网络），后端还会再校验一次
// （app/multipart.py + app/retrieval/knowledge.py），前端校验只是体验优化。
import { ref } from 'vue'

const props = defineProps<{
  accept?: string
  maxSizeMb?: number
  uploading?: boolean
  resultText?: string
  errorText?: string
}>()
const emit = defineEmits<{ (e: 'select', file: File): void }>()

const accept = props.accept || '.txt,.md,.markdown,.csv,.json,.log'
const maxSize = (props.maxSizeMb ?? 2) * 1024 * 1024
const dragging = ref(false)
const localError = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

function pick() {
  inputRef.value?.click()
}

function check(file: File): string {
  const okExt = accept.split(',').some((ext) => file.name.toLowerCase().endsWith(ext.trim().toLowerCase()))
  if (!okExt) return `只支持 ${accept} 这些文本格式`
  if (file.size > maxSize) return `文件不能超过 ${props.maxSizeMb ?? 2} MB`
  if (file.size === 0) return '文件是空的'
  return ''
}

function handle(file?: File | null) {
  if (!file) return
  const err = check(file)
  localError.value = err
  if (!err) emit('select', file)
}

function onDrop(e: DragEvent) {
  dragging.value = false
  handle(e.dataTransfer?.files?.[0])
}

function onChange(e: Event) {
  const input = e.target as HTMLInputElement
  handle(input.files?.[0])
  input.value = '' // 允许重复选择同一个文件
}
</script>

<template>
  <div
    class="uploader"
    :class="{ dragging }"
    @click="pick"
    @dragover.prevent="dragging = true"
    @dragleave.prevent="dragging = false"
    @drop.prevent="onDrop"
  >
    <input ref="inputRef" type="file" :accept="accept" hidden @change="onChange" />
    <div class="uploader-icon">⬆</div>
    <p class="uploader-title">点击选择文件，或把文件拖到这里</p>
    <p class="uploader-hint">支持 {{ accept }}，单个文件 ≤ {{ maxSizeMb ?? 2 }} MB</p>
    <p v-if="uploading" class="uploader-status">上传中…</p>
    <p v-else-if="localError || errorText" class="uploader-error">{{ localError || errorText }}</p>
    <p v-else-if="resultText" class="uploader-ok">{{ resultText }}</p>
  </div>
</template>
