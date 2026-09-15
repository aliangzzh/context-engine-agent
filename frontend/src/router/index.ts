// 极简 hash 路由：路由表 + 动态参数 + 导航守卫 + useRoute/useRouter。
//
// 说明：本机没有外网，装不了 vue-router，所以这里按同样的心智模型实现了一个
// 够用的路由（路由表 / :param / 守卫 / 懒加载 / 编程式导航），API 形如
// vue-router 的 createRouter + useRoute + useRouter。联网后想换成 vue-router，
// 只需把 routes 表原样搬过去（见 docs/frontend.md）。
import { computed, reactive, readonly, shallowRef, type Component } from 'vue'

export type LazyComponent = () => Promise<{ default: Component }>

export interface RouteRecord {
  path: string
  name: string
  title: string
  component: LazyComponent
}

export const routes: RouteRecord[] = [
  { path: '/', name: 'chat', title: '对话', component: () => import('../views/ChatView.vue') },
  { path: '/kb', name: 'kb', title: '知识库', component: () => import('../views/KnowledgeView.vue') },
  { path: '/dashboard', name: 'dashboard', title: '看板', component: () => import('../views/DashboardView.vue') },
]

interface RouteState {
  path: string
  fullPath: string
  name: string
  params: Record<string, string>
  query: Record<string, string>
  matched: RouteRecord | null
}

const state = reactive<RouteState>({
  path: '/',
  fullPath: '/',
  name: 'chat',
  params: {},
  query: {},
  matched: routes[0],
})

const loading = shallowRef(false)

//: 导航守卫：返回 false 阻止跳转（示例里用来挡住"未保存就离开"）
type Guard = (to: RouteState, from: RouteState) => boolean | void
const guards: Guard[] = []
export const beforeEach = (g: Guard) => guards.push(g)

function match(path: string): { record: RouteRecord | null; params: Record<string, string> } {
  for (const record of routes) {
    const rParts = record.path.split('/').filter(Boolean)
    const pParts = path.split('/').filter(Boolean)
    if (rParts.length !== pParts.length) continue
    const params: Record<string, string> = {}
    let ok = true
    for (let i = 0; i < rParts.length; i++) {
      if (rParts[i].startsWith(':')) params[rParts[i].slice(1)] = decodeURIComponent(pParts[i])
      else if (rParts[i] !== pParts[i]) { ok = false; break }
    }
    if (ok) return { record, params }
  }
  return { record: null, params: {} }
}

function parseHash(): string {
  const raw = window.location.hash.replace(/^#/, '')
  return raw || '/'
}

function apply(fullPath: string) {
  const [path, qs = ''] = fullPath.split('?')
  const { record, params } = match(path)
  const query: Record<string, string> = {}
  new URLSearchParams(qs).forEach((v, k) => (query[k] = v))
  state.path = path
  state.fullPath = fullPath
  state.params = params
  state.query = query
  state.matched = record
  state.name = record?.name ?? 'not-found'
}

export async function navigate(to: string, opts: { replace?: boolean } = {}): Promise<void> {
  const target = to.startsWith('/') ? to : `/${to}`
  const next = match(target.split('?')[0])
  const nextState: RouteState = {
    ...state,
    path: target,
    fullPath: target,
    name: next.record?.name ?? 'not-found',
    params: next.params,
  }
  for (const guard of guards) {
    if (guard(nextState, state) === false) return
  }
  loading.value = true
  try {
    if (opts.replace) window.location.replace(`#${target}`)
    else window.location.hash = target
    if (parseHash() === target) apply(target) // hash 没变时也要同步一次状态
  } finally {
    loading.value = false
  }
}

export function startRouter() {
  apply(parseHash())
  window.addEventListener('hashchange', () => apply(parseHash()))
}

export function useRoute() {
  return readonly(state) as Readonly<RouteState>
}

export function useRouter() {
  return {
    push: (to: string) => navigate(to),
    replace: (to: string) => navigate(to, { replace: true }),
    currentRoute: computed(() => state),
    routes,
  }
}

export const isNavigating = computed(() => loading.value)
