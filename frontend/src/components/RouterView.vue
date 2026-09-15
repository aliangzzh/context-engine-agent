<script setup lang="ts">
// 路由出口：按当前路由懒加载页面组件（等价于 vue-router 的 <router-view>）。
import { computed, defineAsyncComponent } from 'vue'
import { useRoute } from '../router'

const route = useRoute()
const cache = new Map<string, ReturnType<typeof defineAsyncComponent>>()

const view = computed(() => {
  const record = route.matched
  if (!record) return null
  if (!cache.has(record.name)) cache.set(record.name, defineAsyncComponent(record.component))
  return cache.get(record.name)!
})
</script>

<template>
  <component :is="view" v-if="view" :key="route.name" />
  <div v-else class="panel not-found">
    <h2>404</h2>
    <p>没有这个页面：{{ route.path }}</p>
  </div>
</template>
