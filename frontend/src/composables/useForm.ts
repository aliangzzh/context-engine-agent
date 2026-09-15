// 表单校验：字段规则 -> 错误信息。
//
// 用法：
//   const form = useForm({
//     filename: { label: '文档名', rules: [required('请填写文档名'), maxLen(40)] },
//     text:     { label: '内容',   rules: [required(), minLen(5, '至少 5 个字')] },
//   })
//   form.values.filename / form.errors.filename / await form.validate() / form.reset()
import { computed, reactive } from 'vue'

export type Rule = (value: any, values: Record<string, any>) => string

export interface FieldDef {
  label: string
  rules?: Rule[]
}

export type FieldMap = Record<string, FieldDef>

export const required = (msg = '必填') => (v: any) => (String(v ?? '').trim() ? '' : msg)
export const minLen = (n: number, msg?: string) => (v: any) =>
  String(v ?? '').trim().length >= n ? '' : msg || `至少 ${n} 个字符`
export const maxLen = (n: number, msg?: string) => (v: any) =>
  String(v ?? '').trim().length <= n ? '' : msg || `最多 ${n} 个字符`
export const pattern = (re: RegExp, msg = '格式不正确') => (v: any) =>
  !String(v ?? '').trim() || re.test(String(v)) ? '' : msg

export function useForm(fields: FieldMap, initial: Record<string, any> = {}) {
  const values = reactive<Record<string, any>>({ ...initial })
  for (const name of Object.keys(fields)) if (!(name in values)) values[name] = ''
  const errors = reactive<Record<string, string>>({})
  const touched = reactive<Record<string, boolean>>({})
  const submitting = reactive({ value: false })

  function validateField(name: string): string {
    const def = fields[name]
    if (!def) return ''
    for (const rule of def.rules || []) {
      const msg = rule(values[name], values)
      if (msg) return msg
    }
    return ''
  }

  function touch(name: string) {
    touched[name] = true
    errors[name] = validateField(name)
  }

  function validate(): boolean {
    let ok = true
    for (const name of Object.keys(fields)) {
      touched[name] = true
      const msg = validateField(name)
      errors[name] = msg
      if (msg) ok = false
    }
    return ok
  }

  function reset(next: Record<string, any> = {}) {
    for (const name of Object.keys(fields)) {
      values[name] = next[name] ?? ''
      errors[name] = ''
      touched[name] = false
    }
  }

  const hasErrors = computed(() => Object.values(errors).some(Boolean))

  return { values, errors, touched, submitting, validate, validateField, touch, reset, hasErrors, fields }
}
