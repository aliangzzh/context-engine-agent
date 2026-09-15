<script setup lang="ts">
// 弹窗组件：遮罩点击 / ESC 关闭，内容与底部用插槽。
import { onBeforeUnmount, onMounted } from 'vue'

const props = defineProps<{ open: boolean; title?: string; width?: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.open) emit('close')
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-mask" @click.self="emit('close')">
      <div class="modal" :style="{ width: width || '560px' }" role="dialog" aria-modal="true">
        <header class="modal-head">
          <h3>{{ title }}</h3>
          <button class="icon-btn" title="关闭" @click="emit('close')">✕</button>
        </header>
        <div class="modal-body">
          <slot />
        </div>
        <footer v-if="$slots.footer" class="modal-foot">
          <slot name="footer" />
        </footer>
      </div>
    </div>
  </Teleport>
</template>
