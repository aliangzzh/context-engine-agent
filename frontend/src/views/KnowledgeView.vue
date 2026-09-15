<script setup lang="ts">
// 知识库管理页：文件上传 / 文本入库（表单校验）/ 列表分页搜索 / 删除确认（弹窗）。
import { ref } from 'vue'
import DataTable, { type Column } from '../components/DataTable.vue'
import FormField from '../components/FormField.vue'
import Modal from '../components/Modal.vue'
import Pagination from '../components/Pagination.vue'
import Uploader from '../components/Uploader.vue'
import { kbDelete, kbIngest, kbList, kbUpload, type KbSource } from '../api'
import { maxLen, minLen, required, useForm } from '../composables/useForm'
import { usePagination } from '../composables/usePagination'
import { mockKbList, useMock } from '../mock'

const columns: Column[] = [
  { key: 'source', label: '文档来源' },
  { key: 'chunks', label: '分块数', width: '100px', align: 'right' },
  { key: 'created_at', label: '入库时间', width: '190px' },
  { key: 'actions', label: '操作', width: '110px', align: 'right' },
]

const keyword = ref('')
const page = usePagination<KbSource>((p, s) => (useMock.value ? Promise.resolve(mockKbList(p, s, keyword.value)) : kbList(p, s, keyword.value)))

function search() {
  void page.go(1)
}

// --- 上传弹窗 ---------------------------------------------------------------------
const uploadOpen = ref(false)
const uploading = ref(false)
const uploadResult = ref('')
const uploadError = ref('')

async function onFile(file: File) {
  uploading.value = true
  uploadResult.value = ''
  uploadError.value = ''
  try {
    const res = await kbUpload(file)
    if (res.status === 'ingested') uploadResult.value = `已入库：${res.filename}（${res.chunks} 个分块）`
    else if (res.status === 'skipped') uploadResult.value = `已存在同内容文档，跳过入库（MD5 去重）`
    else uploadError.value = `未入库：${res.status}${res.reason ? ' · ' + res.reason : ''}`
    await page.go(1)
  } catch (e: any) {
    uploadError.value = e?.message || '上传失败'
  } finally {
    uploading.value = false
  }
}

// --- 文本入库表单（带校验） ---------------------------------------------------------
const formOpen = ref(false)
const formMsg = ref('')
const form = useForm({
  filename: { label: '文档名', rules: [required('请填写文档名'), maxLen(40, '不超过 40 字')] },
  text: { label: '正文', rules: [required('请填写正文'), minLen(10, '正文至少 10 个字')] },
})

async function submitForm() {
  if (!form.validate()) return
  form.submitting.value = true
  formMsg.value = ''
  try {
    const res = await kbIngest(form.values.text, form.values.filename)
    formMsg.value = res.status === 'ingested' ? `已入库 ${res.chunks} 个分块` : `未入库：${res.status}`
    if (res.status === 'ingested') {
      form.reset()
      await page.go(1)
    }
  } catch (e: any) {
    formMsg.value = `提交失败：${e?.message || '未知错误'}`
  } finally {
    form.submitting.value = false
  }
}

// --- 删除确认 ---------------------------------------------------------------------
const deleteTarget = ref<KbSource | null>(null)
const deleteMsg = ref('')

async function confirmDelete() {
  if (!deleteTarget.value) return
  try {
    const res = await kbDelete(deleteTarget.value.source)
    deleteMsg.value = ''
    deleteTarget.value = null
    await page.go(page.page.value)
    void res
  } catch (e: any) {
    deleteMsg.value = e?.message || '删除失败'
  }
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>知识库</h2>
        <p class="muted">文档上传 / 文本入库 / 分块列表。删除会同时清理 SQL 记录与检索索引。</p>
      </div>
      <div class="page-actions">
        <input v-model="keyword" class="input input-sm" placeholder="按来源搜索" @keydown.enter="search" />
        <button class="btn" @click="search">搜索</button>
        <button class="btn" @click="page.reload()">刷新</button>
        <button class="btn" @click="formOpen = true">＋ 文本入库</button>
        <button class="btn btn-primary" @click="uploadOpen = true">⬆ 上传文件</button>
      </div>
    </div>

    <p v-if="page.error.value" class="alert alert-error">{{ page.error.value }}</p>

    <DataTable :columns="columns" :rows="page.items.value" :loading="page.loading.value" row-key="source" empty-text="还没有文档，先上传或录入一条">
      <template #cell-chunks="{ value }">
        <span class="tag">{{ value }}</span>
      </template>
      <template #cell-actions="{ row }">
        <button class="link-btn danger" @click="deleteTarget = row as KbSource">删除</button>
      </template>
    </DataTable>

    <Pagination
      :page="page.page.value"
      :pages="page.pages.value"
      :total="page.total.value"
      :size="page.size.value"
      @update:page="page.go"
      @update:size="page.setSize"
    />

    <Modal :open="uploadOpen" title="上传文档入库" @close="uploadOpen = false">
      <Uploader
        :uploading="uploading"
        :result-text="uploadResult"
        :error-text="uploadError"
        @select="onFile"
      />
      <p class="form-hint">上传走 multipart/form-data；后端会做类型、大小、MD5 去重三层校验。</p>
      <template #footer>
        <button class="btn" @click="uploadOpen = false">关闭</button>
      </template>
    </Modal>

    <Modal :open="formOpen" title="新增文本知识" @close="formOpen = false">
      <FormField
        v-model="form.values.filename"
        label="文档名"
        placeholder="例如：洗涤养护.txt"
        :error="form.errors.filename"
        :touched="form.touched.filename"
        @blur="form.touch('filename')"
      />
      <FormField
        v-model="form.values.text"
        label="正文"
        type="textarea"
        :rows="8"
        placeholder="把要入库的知识贴进来，至少 10 个字"
        :error="form.errors.text"
        :touched="form.touched.text"
        @blur="form.touch('text')"
      />
      <p v-if="formMsg" class="form-hint">{{ formMsg }}</p>
      <template #footer>
        <button class="btn" @click="formOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="form.submitting.value" @click="submitForm">提交入库</button>
      </template>
    </Modal>

    <Modal :open="!!deleteTarget" title="确认删除" width="420px" @close="deleteTarget = null">
      <p>确定删除「{{ deleteTarget?.source }}」吗？该文档的 {{ deleteTarget?.chunks }} 个分块会从索引和数据库中一并移除。</p>
      <p v-if="deleteMsg" class="alert alert-error">{{ deleteMsg }}</p>
      <template #footer>
        <button class="btn" @click="deleteTarget = null">取消</button>
        <button class="btn btn-danger" @click="confirmDelete">确认删除</button>
      </template>
    </Modal>
  </div>
</template>
