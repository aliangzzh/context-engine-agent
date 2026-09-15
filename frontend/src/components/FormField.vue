<script setup lang="ts">
// 表单字段：label + 输入控件 + 校验错误提示（配合 useForm 使用）。
withDefaults(
  defineProps<{
    label: string
    modelValue: string
    error?: string
    touched?: boolean
    type?: 'text' | 'textarea'
    placeholder?: string
    rows?: number
    hint?: string
  }>(),
  { type: 'text', rows: 6 },
)
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void; (e: 'blur'): void }>()
</script>

<template>
  <label class="form-row" :class="{ 'has-error': touched && error }">
    <span class="form-label">{{ label }}</span>
    <textarea
      v-if="type === 'textarea'"
      class="input"
      :rows="rows"
      :placeholder="placeholder"
      :value="modelValue"
      @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
      @blur="emit('blur')"
    />
    <input
      v-else
      class="input"
      :placeholder="placeholder"
      :value="modelValue"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      @blur="emit('blur')"
    />
    <small v-if="touched && error" class="form-error">{{ error }}</small>
    <small v-else-if="hint" class="form-hint">{{ hint }}</small>
  </label>
</template>
