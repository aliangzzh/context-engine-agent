# 前端说明（Vue3 + TypeScript + Vite）

## 页面与路由

| 路由 | 页面 | 干什么 |
|---|---|---|
| `#/` | `views/ChatView.vue` | 对话（SSE 流式渲染）+ 上下文面板 + Agent 协作链 + **把回答标记成 badcase** |
| `#/kb` | `views/KnowledgeView.vue` | 知识库管理：**文件上传**（拖拽/multipart）、**文本入库表单（带校验）**、**列表 + 分页 + 搜索**、**删除确认弹窗** |
| `#/dashboard` | `views/DashboardView.vue` | 运行看板：**图表**（token 占用折线、badcase 分布柱状、分块长度分布、工具调用次数）+ 最近 badcase 列表 + 运行时配置 |

路由表在 `src/router/index.ts`，用法与 vue-router 对应：

```ts
routes = [{ path: '/', name: 'chat', title: '对话', component: () => import('../views/ChatView.vue') }]
useRoute()   // 当前路由（params/query/name）
useRouter()  // push / replace
beforeEach() // 导航守卫
```

新增一个页面只需要两步：写 `views/XxxView.vue`，往 `routes` 里加一条。

## 目录

```
src/
├── api/index.ts          # 统一响应体解包 + 错误码 + 全部接口（含 SSE 手写解析）
├── router/index.ts       # 路由表 / 参数 / 守卫 / 懒加载
├── composables/
│   ├── useForm.ts        # 表单校验（required/minLen/maxLen/pattern + 自定义规则）
│   ├── usePagination.ts  # 列表分页（加载态/错误态/翻页/改页大小）
│   └── useSession.ts     # 跨页面共享的会话 id 与后端状态
├── components/           # Modal / DataTable / Pagination / Uploader / 表单字段 / 两个 SVG 图表
├── views/                # 三个页面
├── mock/index.ts         # Mock 数据开关
└── style.css             # 设计变量与通用样式
```

## 关键实现点

1. **接口联调与排错**：`api/index.ts` 把 `{code,msg,data}` 解包成业务数据，非 0 就抛
   `ApiError(code,msg,detail)`；页面只 `catch` 后展示 `e.message`。所以
   「接口通了但页面没显示」这类问题会变成一条明确的错误码提示，而不是静默空白。
2. **SSE 渲染**：`fetch` + `ReadableStream` + `TextDecoder` 手动按 `\n\n` 切事件，
   逐 token 追加（没用 EventSource，因为要 POST）。
3. **表单校验**：`useForm` 的规则是纯函数 `(value, values) => '' | '错误信息'`，
   blur 时校验单字段、提交时校验全部 —— 前后端都校验（后端是 pydantic + 业务校验）。
4. **文件上传**：`FormData` 由浏览器自动带 multipart boundary；`Uploader` 先做
   扩展名/大小/空文件的即时校验，后端再做一次（`app/multipart.py`）。
5. **Mock 数据**：右上角开关（或 `VITE_USE_MOCK=1`）。打开后知识库页与看板页用
   `src/mock/index.ts` 的假数据，分页、校验、图表渲染路径全部走通 —— 接口没就绪
   也能先把页面交付。

## 离线环境的两点说明（重要）

这台开发机没有外网，`npm install` 装不了三方库，所以：

1. **没有引入组件库**（Element Plus / Ant Design Vue），表格、弹窗、分页、上传、图表
   都是自己写的轻量组件（`src/components/`，合计不到 400 行）。它们的 props/emit
   设计刻意对齐 Element Plus 的用法。
2. **没有引入 vue-router / ECharts**，用等价的自研实现顶上（`router/index.ts`、
   `BarChart.vue`/`LineChart.vue`）。

联网后要换成主流方案，改动范围是可控的：

```bash
npm i vue-router element-plus echarts
```

- 路由：把 `router/index.ts` 的 `routes` 数组搬进 `createRouter({ history: createWebHashHistory(), routes })`，
  `<RouterView>` 换成 vue-router 的同名组件，`useRoute/useRouter` 从 `vue-router` 导入即可，
  页面组件一行不用改（它们只用 `route.name/params/query`）。
- 组件：`DataTable → el-table + el-pagination`、`Modal → el-dialog`、
  `Uploader → el-upload`、`FormField → el-form-item`（`useForm` 的规则可直接映射成 `rules`）。
- 图表：`BarChart/LineChart` 换成 ECharts 的 `bar/line`，`data` 结构（`{label,value}`）不用变。

`eslint.config.js` 也已按 vue + typescript 的扁平配置写好（未接 CI，见文件头说明）。
