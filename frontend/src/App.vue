<script setup lang="ts">
// 应用外壳：导航（路由）+ 后端状态 + Mock 开关 + 页面出口。
import { onMounted } from 'vue'
import RouterView from './components/RouterView.vue'
import { backendLabel, refreshHealth, sessionId, setSessionId, storageLabel } from './composables/useSession'
import { setMock, useMock } from './mock'
import { useRoute, useRouter } from './router'

const route = useRoute()
const router = useRouter()

onMounted(() => {
  void refreshHealth()
  window.setInterval(refreshHealth, 15000)
})
</script>

<template>
  <div class="shell">
    <header class="app-head">
      <div class="brand">
        <span class="logo">🧠</span>
        <div>
          <h1>Context Engine + Multi-Agent QA</h1>
          <p class="sub">上下文引擎 · 多 Agent 协作 · RAG · 知识库管理 · 运行看板</p>
        </div>
      </div>

      <nav class="nav">
        <a
          v-for="r in router.routes"
          :key="r.name"
          class="nav-link"
          :class="{ active: route.name === r.name }"
          :href="`#${r.path}`"
          @click.prevent="router.push(r.path)"
        >
          {{ r.title }}
        </a>
      </nav>

      <div class="badges">
        <input
          class="input input-xs"
          :value="sessionId"
          title="会话 id（写入 URL 里的会话/上下文）"
          @change="setSessionId(($event.target as HTMLInputElement).value)"
        />
        <span class="badge">{{ backendLabel }}</span>
        <span v-if="storageLabel" class="badge">{{ storageLabel }}</span>
        <label class="switch" title="接口未就绪时用假数据把页面流程跑通">
          <input type="checkbox" :checked="useMock" @change="setMock(($event.target as HTMLInputElement).checked)" />
          Mock 数据
        </label>
      </div>
    </header>

    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>
