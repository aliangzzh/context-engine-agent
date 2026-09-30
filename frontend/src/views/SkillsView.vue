<script setup lang="ts">
// 技能库页（开发经验）：只读展示规则 + 语料同步 + 格式校验结果 + **草稿区**。
//
// 为什么正式技能**只读**：技能正文的唯一真源是仓库里的 skills/<name>/SKILL.md
// （能 review、能 diff、能回滚）。页面上直接编辑会立刻产生"文件和库哪个对"的问题。
//
// 为什么**草稿区可以写**：草稿在 skills/_inbox/ 里 —— 不进检索语料（loader 只认
// */SKILL.md）、不在 Git 里（.gitignore），写坏了没有任何副作用。所以页面可以列、
// 可以移除（其实是归档到 _trash，可后悔），但**不生成正式技能**：那一步必须人工过审。
import { computed, onMounted, ref } from 'vue'
import Modal from '../components/Modal.vue'
import {
  skillDraftRemove, skillDrafts, skillList, skillSync,
  type SkillDraft, type SkillDraftsPayload, type SkillItem, type SkillPayload,
} from '../api'
import { mockSkillDrafts, mockSkillList, useMock } from '../mock'

const data = ref<SkillPayload | null>(null)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const detail = ref<SkillItem | null>(null)

const skills = computed(() => data.value?.skills ?? [])
const skipped = computed(() => data.value?.skipped ?? [])
const stats = computed(() => data.value?.stats)

// --- 草稿区（_inbox/）--------------------------------------------------------------
const draftsOpen = ref(false)
const draftData = ref<SkillDraftsPayload | null>(null)
const draftDetail = ref<SkillDraft | null>(null)
const removeTarget = ref<SkillDraft | null>(null)
const draftBusy = ref(false)
const draftList = computed(() => draftData.value?.drafts ?? [])

async function loadDrafts() {
  try {
    draftData.value = useMock.value ? mockSkillDrafts() : await skillDrafts()
  } catch (e: any) {
    error.value = e?.message || '加载草稿区失败'
  }
}

async function toggleDrafts() {
  draftsOpen.value = !draftsOpen.value
  if (draftsOpen.value) await loadDrafts()
}

async function confirmRemove() {
  const target = removeTarget.value
  if (!target || useMock.value) {
    removeTarget.value = null
    return
  }
  draftBusy.value = true
  try {
    const res = await skillDraftRemove(target.name)
    notice.value = `已移除「${target.name}」（移到 _inbox/_trash/，可手动恢复；归档区现有 ${res.trash_count} 份）`
    removeTarget.value = null
    await loadDrafts()
  } catch (e: any) {
    error.value = e?.message || '移除失败'
  } finally {
    draftBusy.value = false
  }
}

async function load(reload = false) {
  loading.value = true
  error.value = ''
  try {
    if (useMock.value) data.value = mockSkillList()
    else data.value = await skillList(reload)
    await loadDrafts()
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

    <!-- 草稿区：素材区可以写，正式技能仍然只读（真源在 Git 里的 SKILL.md） -->
    <section class="drafts">
      <button class="drafts-head" @click="toggleDrafts">
        <b>草稿区（{{ draftList.length }}）</b>
        <span class="muted">skills/_inbox/ · 不进语料、不参与匹配</span>
        <span class="spacer" />
        <span class="link-btn">{{ draftsOpen ? '收起' : '展开' }}</span>
      </button>
      <p class="muted drafts-hint">
        草稿是**素材**：loader 只认 <code>skills/&lt;名字&gt;/SKILL.md</code>，所以草稿永远不会被检索到。
        人工过三问（真踩过吗 / 验证指向哪 / 和已有技能重复吗）后，再提升为正式技能。
      </p>
      <div v-if="draftsOpen" class="draft-list">
        <div v-for="d in draftList" :key="d.name" class="draft">
          <div class="skill-head">
            <span class="tag">{{ d.source }}</span>
            <b class="name">{{ d.question }}</b>
            <span class="spacer" />
            <span class="muted small">{{ d.modified_at }} · {{ (d.size / 1024).toFixed(1) }} KB</span>
          </div>
          <p v-if="d.duplicate" class="warn small">
            ⚠ 与 {{ d.duplicate[0] }} 相似 {{ d.duplicate[1] }} —— 可能已经有这条经验了，别重复造
          </p>
          <div class="draft-actions">
            <button class="link-btn" @click="draftDetail = d">查看全文</button>
            <button class="link-btn danger" @click="removeTarget = d">移除</button>
          </div>
        </div>
        <p v-if="!draftList.length" class="muted">
          还没有草稿。命令行跑 <code>collect_experience from-chat --write</code>，
          或在<b>对话页</b>点某条回答下的「沉淀为经验」。
        </p>
      </div>
      <p v-if="draftData?.trash_count" class="muted small">
        归档区（_inbox/_trash/）还有 {{ draftData.trash_count }} 份被移除的草稿，需要时手动恢复。
      </p>
    </section>

    <Modal :open="!!detail" :title="detail?.name || '技能正文'" width="760px" @close="detail = null">
      <p class="muted">{{ detail?.description }}</p>
      <p class="muted">文件：{{ detail?.path }}</p>
      <pre class="body">{{ detail?.body }}</pre>
      <template #footer>
        <button class="btn" @click="detail = null">关闭</button>
      </template>
    </Modal>

    <Modal :open="!!draftDetail" :title="draftDetail?.question || '草稿全文'" width="760px" @close="draftDetail = null">
      <p class="muted">
        {{ draftDetail?.name }} · {{ draftDetail?.source }} · ⚠ AI 抽取·未验证，人工过三问后再提升
      </p>
      <pre class="body">{{ draftDetail?.content }}</pre>
      <template #footer>
        <button class="btn" @click="draftDetail = null">关闭</button>
      </template>
    </Modal>

    <Modal :open="!!removeTarget" title="移除这份草稿？" @close="removeTarget = null">
      <p class="modal-sub">{{ removeTarget?.name }}</p>
      <p class="muted">
        会把它移到 <code>_inbox/_trash/</code>（**不是真删**，草稿不在 Git 里，删了无法找回）。
        需要时去那个目录手动恢复。
      </p>
      <template #footer>
        <button class="btn" @click="removeTarget = null">取消</button>
        <button class="btn btn-primary" :disabled="draftBusy" @click="confirmRemove">
          {{ draftBusy ? '处理中…' : '移到归档区' }}
        </button>
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
.small { font-size: 12px; }
.drafts { margin-top: 22px; border-top: 1px solid var(--border); padding-top: 14px; }
.drafts-head {
  display: flex; gap: 10px; align-items: center; width: 100%;
  background: none; border: none; color: var(--text); cursor: pointer; padding: 0 0 6px;
}
.drafts-head b { font-size: 14px; }
.drafts-hint { font-size: 12px; line-height: 1.7; margin: 2px 0 10px; }
.draft-list { display: flex; flex-direction: column; gap: 10px; }
.draft { background: var(--panel); border: 1px dashed var(--border); border-radius: 12px; padding: 10px 14px; }
.draft-actions { display: flex; gap: 14px; margin-top: 6px; }
.link-btn.danger { color: #ff9b9b; }
.link-btn.danger:hover { color: #ff7b7b; }
.body {
  margin: 10px 0 0; padding: 12px; max-height: 380px; overflow: auto;
  background: var(--panel2); border: 1px solid var(--border); border-radius: 8px;
  font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word;
}
</style>
