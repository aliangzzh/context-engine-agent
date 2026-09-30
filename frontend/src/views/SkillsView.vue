<script setup lang="ts">
// 技能库页（开发经验）：只读展示规则 + 语料同步 + 格式校验结果。
//
// 为什么**只读**：技能正文的唯一真源是仓库里的 skills/<name>/SKILL.md
// （能 review、能 diff、能回滚）。页面上直接编辑会立刻产生"文件和库哪个对"的问题，
// 所以这一页只做三件事：看清有哪些技能、正文写了什么、语料和文件是否一致。
import { computed, onMounted, ref } from 'vue'
import Modal from '../components/Modal.vue'
import { skillList, skillSync, type SkillItem, type SkillPayload } from '../api'
import { mockSkillList, useMock } from '../mock'

const data = ref<SkillPayload | null>(null)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const detail = ref<SkillItem | null>(null)

const skills = computed(() => data.value?.skills ?? [])
const skipped = computed(() => data.value?.skipped ?? [])
const stats = computed(() => data.value?.stats)

async function load(reload = false) {
  loading.value = true
  error.value = ''
  try {
    if (useMock.value) data.value = mockSkillList()
    else data.value = await skillList(reload)
  } catch (e: any) {
    error.value = e?.message || '加载技能库失败'
  } finally {
    loading.value = false
  }
}

async function resync() {
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    if (useMock.value) {
      data.value = mockSkillList()
      notice.value = '【Mock】假装同步了一次'
      return
    }
    const res = await skillSync()
    data.value = res
    const s = res.summary
    notice.value = s.rebuilt
      ? `已重建技能语料：变化 ${s.changed.length} 条、移除 ${s.removed.length} 条，共 ${s.chunks} 个分块`
      : '技能语料已是最新（md5 一致），无需重建'
  } catch (e: any) {
    error.value = e?.message || '同步失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>技能库（开发经验）</h2>
        <p class="muted">
          一条技能 = 一个真实踩过的坑（现象 / 根因 / 修复 / 验证）。Agent 命中后把它作为
          <b>行为约束</b>注入上下文；正文真源是仓库里的 <code>skills/&lt;name&gt;/SKILL.md</code>，本页只读。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" :disabled="loading" @click="load(true)">重新加载</button>
        <button class="btn btn-primary" :disabled="loading" @click="resync">重新同步语料</button>
      </div>
    </div>

    <p v-if="error" class="alert alert-error">{{ error }}</p>
    <p v-if="notice" class="alert">{{ notice }}</p>

    <div v-if="stats" class="cards">
      <div class="card">
        <span class="card-label">技能数</span>
        <b>{{ skills.length }}</b>
      </div>
      <div class="card">
        <span class="card-label">语料分块</span>
        <b>{{ stats.chunks }}</b>
      </div>
      <div class="card">
        <span class="card-label">检索后端</span>
        <b>{{ stats.backend }}</b>
      </div>
      <div class="card">
        <span class="card-label">语料 vs 文件</span>
        <b :class="{ warn: stats.needs_sync }">{{ stats.needs_sync ? '需同步' : '一致' }}</b>
      </div>
    </div>

    <p v-if="skipped.length" class="alert alert-error">
      有 {{ skipped.length }} 个技能文件格式有问题、已跳过（不进语料）：
      <span v-for="s in skipped" :key="s.path" class="skip">{{ s.path }} — {{ s.reason }}</span>
    </p>

    <div class="skill-list">
      <div v-for="s in skills" :key="s.name" class="skill" :class="{ off: !s.active }">
        <div class="skill-head">
          <b class="name">{{ s.name }}</b>
          <span class="tag">v{{ s.version }}</span>
          <span class="tag" :class="{ 'tag-danger': !s.active }">{{ s.status || 'active' }}</span>
          <span class="spacer" />
          <button class="link-btn" @click="detail = s">查看正文</button>
        </div>
        <p class="desc">{{ s.description }}</p>
        <div class="meta">
          <span v-if="s.trigger.length" class="line"><i>触发词</i>{{ s.trigger.join(' / ') }}</span>
          <span v-if="s.tags.length" class="line"><i>标签</i>{{ s.tags.join(' / ') }}</span>
          <span class="line"><i>文件</i>{{ s.path }}</span>
        </div>
      </div>
      <p v-if="!skills.length && !loading" class="muted">
        还没有技能。往仓库 <code>skills/&lt;name&gt;/SKILL.md</code> 加一条，再点「重新同步语料」。
      </p>
    </div>

    <Modal :open="!!detail" :title="detail?.name || '技能正文'" width="760px" @close="detail = null">
      <p class="muted">{{ detail?.description }}</p>
      <p class="muted">文件：{{ detail?.path }}</p>
      <pre class="body">{{ detail?.body }}</pre>
      <template #footer>
        <button class="btn" @click="detail = null">关闭</button>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
.skill-list { display: flex; flex-direction: column; gap: 12px; margin-top: 14px; }
.skill { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; }
.skill.off { opacity: .6; }
.skill-head { display: flex; gap: 8px; align-items: center; }
.skill-head .name { font-size: 14px; color: var(--accent2); }
.skill-head .spacer { flex: 1; }
.desc { margin: 6px 0 8px; font-size: 13px; line-height: 1.6; }
.meta { display: flex; flex-direction: column; gap: 3px; }
.line { font-size: 12px; color: var(--muted); word-break: break-all; }
.line i { display: inline-block; width: 44px; font-style: normal; color: var(--border); }
.skip { display: block; margin-top: 4px; font-size: 12px; }
.warn { color: #ffd7a8; }
.body {
  margin: 10px 0 0; padding: 12px; max-height: 380px; overflow: auto;
  background: var(--panel2); border: 1px solid var(--border); border-radius: 8px;
  font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word;
}
</style>
