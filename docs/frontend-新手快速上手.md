# 前端新手快速上手（Vue3 + TS + Vite）

> 面向第一次接触这个项目的人。目标：**10 分钟内把页面跑起来，并看懂一条请求从头到尾怎么走。**
> 想先跑起来只看第 2 节；想看代码从第 4 节开始。

---

## 1. 这个前端是什么

一句话：**三个页面的纯前端 SPA，通过 `/api` 跟 Python 后端说话。**

| 页面 | 路由 | 干什么 |
|---|---|---|
| 对话 | `#/` | SSE 流式问答 + 右侧显示本次的「上下文分配」和「Agent 协作链」+ 把回答标记成 badcase |
| 知识库 | `#/kb` | 上传文件 / 文本入库（带表单校验）/ 列表分页搜索 / 删除确认弹窗 |
| 看板 | `#/dashboard` | token 占用折线、badcase 分布柱状、分块长度分布、工具调用次数 + 运行时配置 |

**技术栈只有 4 个依赖**（`package.json`）：`vue` + `vite` + `typescript` + `vue-tsc`。

### ⚠️ 最重要的一件事：这里的路由、组件库、图表都是自研的

`docs/frontend.md` 说明了原因：作者当时在**离线环境**，`npm install` 装不了三方包，所以用等价的自研实现顶上了：

| 主流方案 | 这个项目里的替代品 | 文件 |
|---|---|---|
| `vue-router` | 自研 hash 路由（API 刻意仿 vue-router） | `src/router/index.ts` |
| `element-plus` 的表格/弹窗/分页/上传 | 自研轻量组件（合计不到 400 行） | `src/components/` |
| `echarts` | 自研 SVG 图表 | `src/components/BarChart.vue`、`LineChart.vue` |

**这不是"写得土"，是刻意的取舍**——props/emit 设计对齐了 Element Plus，联网后换成主流库的改动范围写在 `docs/frontend.md` 末尾。你如果第一次见 Vue，**建议先按现在这样学**，因为代码量小、没有黑盒，反而更容易看懂路由和组件通信是怎么回事。

---

## 2. 跑起来（三步）

前置：Node.js ≥ 18、Python ≥ 3.9，都已具备（实测 Node v24.19.0 / Python 3.12.7）。

### 第 1 步：起后端（必须先起，前端要它提供数据）

```powershell
cd F:\shujuf\code\context-engine-agent\backend
python run.py
```

- 零依赖，**不需要 pip install**（`server.py` 是纯 stdlib HTTP 服务器）。
- 成功标志：窗口停住不报错，然后另开一个终端验证：

```powershell
curl.exe http://localhost:8000/health
# {"code": 0, "msg": "ok", "data": {"status": "ok", "chat_backend": "fake", ...}}
```

### 第 2 步：装前端依赖（只需一次）

```powershell
cd F:\shujuf\code\context-engine-agent\frontend
npm install          # 实测 47 个包，几秒钟
```

### 第 3 步：起前端

```powershell
npm run dev
```

看到这段就成功了：

```
  VITE v5.4.21  ready in 297 ms
  ➜  Local:   http://localhost:5173/
```

### 第 4 步：打开浏览器

👉 **http://localhost:5173/**

> 🔴 **务必用 `localhost`，不要用 `127.0.0.1`！**
> 实测 Vite 只监听了 IPv6 的 `::1`，敲 `http://127.0.0.1:5173` 会「无法连接」。
> 如果你确实想用 `127.0.0.1`：`npm run dev -- --host 127.0.0.1`

### 一键启动（可选）

项目根目录有 `start_all.bat`，双击会开两个窗口分别起后端和前端，再自动打开浏览器。**新手建议先按上面 4 步手动来一遍**，出问题时能看清是哪个环节挂了。

---

## 3. 零基础验证清单（确认真的跑通了）

按顺序做，每步都该有反应：

1. 打开 http://localhost:5173/ → 顶部右上角徽标显示 **`fake / bm25`** 和 **`sqlite + lru`**（不是「后端未连接」）。
2. 对话页输入 `计算 3*4+2` → 回车 → 回答逐字流式出现，右侧 Agent 链出现 `router` 节点。
3. 输入 `上海天气` → 右侧 Agent 链应该出现工具调用，`used_tools` 有 `get_weather`。
4. 随便对一条回答点「**标记问题**」→ 选类型提交 → 切到「看板」页，badcase 总数 +1。
5. 切到「知识库」页 → 「＋ 文本入库」→ 文档名填 `测试.txt`、正文随便写 10 个字以上 → 提交 → 列表里出现这一条。
6. 回到对话页问 `测试` 相关的问题 → 回答里应该能引用到刚才的知识。

**第 1 步没通过**（显示「后端未连接」）→ 看第 6 节的「坑 2」。

---

## 4. 代码从哪看起（推荐顺序）

```
frontend/
├── index.html            # 唯一的 HTML 入口，只有一个 <div id="app">
├── vite.config.ts        # dev server + /api、/health 代理到 8000
├── package.json          # 4 个脚本：dev / build / preview / typecheck
├── tsconfig.json         # strict: true（类型检查是严格的）
├── eslint.config.js      # 扁平配置（⚠️ 依赖没装，npm run lint 目前会失败，见坑 4）
├── nginx.conf            # 生产环境：托管 dist/ + 反代 + 关 SSE 缓冲
├── Dockerfile            # 多阶段：node 构建 → nginx 托管
├── static/index.html     # ⚠️ 不是 Vue 应用！是后端 server.py 单独托管的另一套单文件 UI
└── src/
    ├── main.ts              # ① 入口：startRouter() → createApp(App).mount('#app')
    ├── App.vue              # ② 外壳：顶部导航 + 后端状态徽标 + Mock 开关
    ├── style.css            #    设计变量（--accent / --panel …）+ 通用类
    ├── router/index.ts      # ③ 自研 hash 路由
    ├── api/index.ts         # ④ ★ 所有 HTTP 调用 + 响应解包 + SSE 手写解析
    ├── mock/index.ts        #    Mock 开关与假数据
    ├── composables/         # ⑤ useForm 校验 / usePagination 分页 / useSession 会话
    ├── components/          # ⑥ Modal / DataTable / Pagination / Uploader / 图表
    └── views/               # ⑦ ChatView / KnowledgeView / DashboardView
```

**阅读顺序建议**：`main.ts` → `App.vue` → `router/index.ts` → `api/index.ts` → `ChatView.vue` → 其余。

前四个文件加起来不到 400 行，看完你就掌握了这个前端的全部骨架。

---

## 5. 一条请求的完整链路（最重要的心智模型）

以对话页输入「上海天气」为例，跟着代码走一遍：

| # | 位置 | 发生了什么 |
|---|---|---|
| 1 | `views/ChatView.vue` `send()` | 把用户消息 push 进 `messages`，并 push 一个**空的 assistant 气泡** |
| 2 | `api/index.ts` `streamChat()` | `fetch('/api/chat/stream', { method:'POST', body: JSON.stringify(...) })` |
| 3 | `vite.config.ts` | dev server 把 `/api` 开头的请求**代理**到 `http://localhost:8000` |
| 4 | 后端 | 返回 `Content-Type: text/event-stream`，逐条推 SSE 事件 |
| 5 | `api/index.ts:222-244` | `res.body.getReader()` + `TextDecoder` 手动按 `\n\n` 切事件，逐行 `JSON.parse` |
| 6 | 回调分发 | `agent`→`trace`、`token`→追加到气泡、`retrieved`→检索数、`done`→上下文、`error`→错误提示 |
| 7 | Vue 响应式 | `ref` 一变，模板自动重渲染 |
| 8 | `components/ContextPanel.vue` / `AgentPanel.vue` | 用第 6 步的数据画出右侧两个面板 |
| 9 | 点「标记问题」→ `feedbackCreate()` | `POST /api/feedback` → 落 `feedback` 表 → 看板页 `GROUP BY` 统计 |

### 两个值得单独理解的设计

**① 统一响应体解包（`api/index.ts`）**

后端所有普通接口都返回 `{code, msg, data}`。`request<T>()` 这一层负责：`code !== 0` 就抛 `ApiError(code, msg)`，`code === 0` 就把 `data` 拆出来返回给页面。

好处是**页面只写 `try/catch` 然后展示 `e.message`**，不用管 HTTP 状态码和信封结构。「接口通了但页面空白」这种玄学问题就变成了一条明确的错误码提示。

> 注意：**SSE 是例外**，它不是信封结构，所以 `streamChat()` 单独手写解析。

**② 自研路由（`router/index.ts`）**

只支持 hash 模式（URL 里带 `#`），核心就是三个东西：

- `routes` 数组：`{ path, name, title, component }`，`component` 是懒加载函数
- `match(path)`：把当前 hash 匹配到一条路由，解析 `:param`
- `useRoute()` / `useRouter()`：页面里读路由、跳路由，用法跟 vue-router 一模一样

`components/RouterView.vue` 就是路由出口，用 `defineAsyncComponent` 按需加载页面并缓存。

**加一个新页面只要两步**：写 `views/XxxView.vue`，往 `routes` 里加一条。

---

## 6. 我实测踩到的坑

### 坑 0：`python run.py` 报 `Errno 2: No such file or directory`（最容易犯）

**原因**：`run.py` 在 **`backend/`** 里，但你可能在 `frontend/` 目录下敲了它。

```
PS F:\...\context-engine-agent\frontend> python run.py
   ↑ 在 frontend 目录，但这个文件在 backend
F:\...\python.exe: can't open file 'F:\...\frontend\run.py': [Errno 2] No such file or directory
```

**解决**：注意目录。后端和前端要**两个窗口**分别跑，而且后端窗口会一直占着（它是阻塞运行的服务器）：

| 窗口 | 命令 | 成功标志 |
|---|---|---|
| A（后端） | `cd F:\shujuf\code\context-engine-agent\backend` → `python run.py` | **停住不动**，不报错 |
| B（前端） | `cd F:\shujuf\code\context-engine-agent\frontend` → `npm run dev` | 显示 `Local: http://localhost:5173/` |

也可以用绝对路径 `python F:\shujuf\code\context-engine-agent\backend\run.py`，但**不推荐**——`run.py` 里是 `import server`，靠"当前目录能搜到 `server.py`"，还是 cd 过去最稳。

> 判断当前在哪：看命令行提示符的路径。`...\backend>` 才是对的。

### 坑 1：`127.0.0.1:5173` 连不上

Vite 默认 host 是 `localhost`，在这台机器上解析成了 IPv6 `::1`，所以只监听 `::1`。

**解决**：用 `http://localhost:5173/`；或 `npm run dev -- --host 127.0.0.1`。

### 坑 2：右上角一直显示「后端未连接」，但其实后端是好的 ✅ 已修复

**原因**：`api/index.ts` 的 `health()` 请求的是 `/health`，**不带 `/api` 前缀**。而 `vite.config.ts` 里只配了 `/api` 的代理。于是这个请求打到了 Vite 自己身上，被 SPA fallback 接住返回了 `index.html`（HTTP 200，`Content-Type: text/html`），`JSON.parse` 一个 HTML 当然失败 → `refreshHealth()` 的 catch 触发 → 显示「后端未连接」。

对比一下：`nginx.conf`（生产环境）里 **有** `location /health`，所以这个 bug 只在 dev 下出现。

**已修复**：给 `vite.config.ts` 补上了 `/health` 代理。修复后实测：

```
GET http://localhost:5173/health → 200 application/json
{"code":0,"msg":"ok","data":{"chat_backend":"fake","retrieval_backend":"bm25",...}}
```

> 这个坑挺有代表性：**「接口通了但页面不对」不一定是后端的锅**，先按 F12 看 Network 里那个请求实际返回了什么 —— 这里返回的是 `text/html`，一眼就能看出被前端 dev server 自己吞了。

### 坑 3：`npm install` 结尾的 `vulnerabilities` 和 `allow-scripts` 警告要不要管？

`npm install` 结束时会打印这些，**都不影响运行，可以先不管**：

```
2 vulnerabilities (1 moderate, 1 high)     ← npm audit 的提示
npm warn allow-scripts 1 package has install scripts not yet covered by allowScripts:
npm warn allow-scripts   esbuild@0.21.5 (postinstall: node install.js)
```

**关于 vulnerabilities**：`npm audit` 实际报的是 3 条，全在 `esbuild → vite → @vitejs/plugin-vue` 这条依赖链上：

| 包 | 级别 | 直接依赖？ |
|---|---|---|
| `vite` | high | 是 |
| `esbuild` | moderate | 否（被 vite 引入） |
| `@vitejs/plugin-vue` | moderate | 是 |

漏洞是 [GHSA-67mh-4wv8-2f99](https://github.com/advisories/GHSA-67mh-4wv8-2f99)：esbuild 的**自带 dev server**（`esbuild --serve`）缺少 origin 校验。

- 这个漏洞影响的是 esbuild **自己的 serve 模式**，而 Vite 只把 esbuild 当**转换器/依赖预打包**用，**不会**用到它的 serve 模式。所以对本项目的实际暴露面很低。
- `npm audit` 说 **`No fix available`**，是因为 `package.json` 里锁的是 `vite: ^5.2.0`，而 vite 5.x 全线都用 esbuild `^0.21`（有漏洞）；修好的 esbuild `0.25` 要 vite **6.3.5+** 才用上，属于 semver 大版本升级，npm audit 不会自己建议。
- ⚠️ **不要跑 `npm audit fix --force`** —— 它会擅自把 `vite` 跨大版本改写进 `package.json`，属于破坏性变更。

**想要一份干净的 audit**（可选，联网时再做）：`npm i -D vite@^6.3.5`。现有 `@vitejs/plugin-vue@5` 的 peer 范围同时接受 vite 5 和 6，`vite.config.ts` 不用改。

**关于 allow-scripts**：这是 npm 11 新增的安装脚本白名单提示。esbuild 的 postinstall 需要下载平台二进制。如果 `npm run dev` 报 esbuild 相关的 `spawn` / 找不到二进制的错，按它自己的提示放行再重装：

```powershell
npm approve-scripts esbuild
npm install
```

### 坑 4：`npm run lint` 会失败（exit 1）

`package.json` 里有 `lint` 脚本，`eslint.config.js` 也写好了，但 **eslint 本身没装**（`node_modules` 里没有）。

```
'eslint' is not recognized as an internal or external command
```

这是已知的、被文档记录过的取舍（`eslint.config.js` 头部有说明：不想"配置写了但从没跑过"）。要用就补依赖：

```powershell
npm i -D eslint @eslint/js typescript-eslint eslint-plugin-vue globals vue-eslint-parser
npm run lint
```

### 坑 5：`frontend/static/index.html` 不是这个 Vue 应用

`backend/server.py:36` 把 `frontend/static/index.html` 当静态 UI 托管在 `/`。所以：

- 打开 **http://localhost:8000** → 看到的是那套**单文件 UI**（跟 Vue 无关）
- 打开 **http://localhost:5173** → 才是本节的 **Vue3 应用**

改 `static/index.html` 不会影响 Vue 页面，别改错文件。

### 坑 6：Mock 开关不是全局生效

右上角的「Mock 数据」只对**知识库页**和**看板页**生效（`KnowledgeView.vue:22`、`DashboardView.vue:21,61`）。**对话页不吃 Mock**，聊天始终走真接口。所以后端没起时，勾了 Mock 也只有两个页面能看。

---

## 7. 常用命令

在 `frontend/` 目录下执行：

| 命令 | 作用 | 实测结果 |
|---|---|---|
| `npm install` | 装依赖 | ✅ 47 个包 |
| `npm run dev` | 起开发服务器（热更新） | ✅ http://localhost:5173/ |
| `npm run typecheck` | `vue-tsc` 类型检查 | ✅ 通过（0 错误） |
| `npm run build` | 类型检查 + 打包到 `dist/` | ✅ 48 模块，887ms，总计 ~110KB（gzip ~46KB） |
| `npm run preview` | 本地预览 `dist/` 产物 | — |
| `npm run lint` | eslint | ❌ 需先装 eslint（坑 4） |

> `dist/` 和 `node_modules/` 都已在 `.gitignore` 里，不会污染仓库。

**端口对照**：

| 端口 | 是谁 | 入口 URL |
|---|---|---|
| 8000 | 后端（`backend/python run.py`） | http://localhost:8000（单文件 UI + API） |
| 5173 | 前端 dev server | http://localhost:5173（Vue 应用） |
| 8080 | Docker 部署后的 Nginx | http://localhost:8080 |

---

## 8. 练手任务（由易到难）

1. **加一个页面**：`views/AboutView.vue` + 在 `router/index.ts` 的 `routes` 里加 `{ path: '/about', name: 'about', title: '关于', component: () => import('../views/AboutView.vue') }`。感受"两步加一页"。
2. **改一处 UI**：给知识库列表加一列「字符数」。涉及 `KnowledgeView.vue` 的 `columns` 和 `#cell-xxx` 插槽。
3. **读懂校验**：打开 `composables/useForm.ts`（72 行），规则就是纯函数 `(value, values) => '' | '错误信息'`。试着加一条自定义规则（比如"文档名不能包含空格"）。
4. **加持久化**：让对话页的历史消息存进 `localStorage`，刷新不丢。（提示：参考 `composables/useSession.ts` 里 `sessionId` 的写法）
5. **换主流方案**（联网后）：`npm i vue-router element-plus echarts`，按 `docs/frontend.md` 末尾的对照表逐个替换。**页面组件几乎一行都不用改**——这正是自研实现刻意对齐 API 的价值。

---

## 9. 进阶：后端有「两扇门」，前端可以互换

这个项目有**两个 HTTP 入口**，业务逻辑共用同一份（`app/api.py`）：

| | stdlib 门 | FastAPI 门 |
|---|---|---|
| 文件 | `backend/server.py` | `backend/app/main.py` |
| 启动 | `python run.py` | `uvicorn app.main:app --reload --port 8090` |
| 依赖 | **零依赖**，离线能跑 | 需要 `fastapi` + `uvicorn` |
| 默认端口 | 8000 | 你自己指定 |
| 额外白送 | — | **`/docs` 交互式接口文档** |
| 业务逻辑 | ←── 同一个 `api.handle_*()` ──→ | |

因为**前端只认路径（`/api`、`/health`），不认端口和框架**，所以换后端入口不需要改任何前端代码 —— 改 `vite.config.ts` 里的 `target` 就行。该文件已改成环境变量驱动：

```ts
const target = env.VITE_API_TARGET || 'http://localhost:8000'
```

**切换方式**（`frontend/.env.local` 已在 `.gitignore` 里，不会进版本库）：

```powershell
cd F:\shujuf\code\context-engine-agent\frontend

# 切到 FastAPI 门（8090）
Set-Content .env.local 'VITE_API_TARGET=http://localhost:8090' -Encoding ascii

# 切回默认（stdlib 门 8000）
Remove-Item .env.local
```

写完**不用手动重启** —— Vite 检测到 `.env.local` 变化会自动重启（日志会打印 `[vite] .env.local changed, restarting server...`）。

> ⚠️ 用 `-Encoding ascii` 是故意的：Windows PowerShell 5.1 的 `utf8` 会写入 BOM，可能让 dotenv 解析不到第一个键。

> ⚠️ **切换后要保证对应的后端在跑**。比如 `.env.local` 指向 8090 却只起了 `python run.py`（8000），页面右上角会显示「后端未连接」。

### 怎么判断前端现在连的是哪扇门

两扇门返回的 **JSON 内容逐字相同**，肉眼看不出。但**响应头**留下了指纹：

| 响应头 | stdlib `:8000` | FastAPI `:8090` |
|---|---|---|
| `Server` | `ContextEngine/1.0 Python/3.12.7` | **`uvicorn`** ← 最直观 |
| `Content-Type` | `application/json; charset=utf-8` | `application/json`（无 charset） |
| `X-Request-ID` | `X-Request-ID` | `x-request-id`（小写） |

命令行一条搞定：

```powershell
(Invoke-WebRequest http://localhost:5173/health -UseBasicParsing).Headers['Content-Type']
# 有 charset  -> 连着 8000
# 无 charset  -> 连着 8090
```

浏览器里：`F12` → **Network** → 点 `health` 请求 → 看**「响应标头」**里的 `Server` 和 `Content-Type`。

> 📌 顺带一个真实差异：**FastAPI 不声明 `charset=utf-8`**。浏览器处理 JSON 默认走 UTF-8 所以页面上没事，但严格客户端（PowerShell 5.1、老版 Postman、部分 Python 客户端）会把它猜成 Latin-1，把中文显示成 `å°ºç `。遇到乱码先想这条。

---

## 10. 相关文档

- `docs/frontend.md` —— 前端设计说明 + 换主流方案的迁移步骤（**必读**）
- `README.md` —— 项目全貌、接口一览、Docker 部署、设计取舍与已知限制
- `docs/architecture.md` —— 架构设计与各模块实现要点
- `frontend/eslint.config.js` —— 头部有 lint 依赖的安装说明
