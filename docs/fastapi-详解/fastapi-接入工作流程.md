# FastAPI 接入工作流程（真实任务模拟）

> 这份文档不是 FastAPI 教程，是**把一个真实工程任务跑一遍**：
> 某天你接到"给项目接 FastAPI"这个活，从需求对齐到灰度上线，每一阶段
> 该做什么、产出什么文件、评审会被问什么、什么算做完。
>
> 本文以本仓库为实例展开。注意：**本仓库的接入已经完成**（`backend/app/main.py`
> 就是终态），所以这份流程既是"当时应该怎么走"，也是"如果重做一遍该怎么走"。
> 把仓库名和路径换掉，同样的流程可以直接搬到公司项目上。

---

## 1. 任务卡（Ticket）

真实工作里第一步不是写代码，是把这张卡填出来。填不出来就说明活还没接。

| 项 | 内容 |
|---|---|
| **标题** | 后端接口层引入 FastAPI，替换手写 HTTP 路由 |
| **提出方** | 前端 / 测试 / 运维任一方。**必须问出真实动机**（见下） |
| **背景** | 后端目前由 `backend/server.py`（stdlib `ThreadingHTTPServer`）提供接口，路由是 `do_GET/do_POST/do_DELETE` 里的一长串 `if/elif` |
| **目标** | ① 有可交互的接口文档（`/docs`）② 请求参数自动校验 ③ 统一异常与错误码 ④ 接口层可维护、可测试 ⑤ 不牺牲"离线零依赖可跑" |
| **非目标（明确不做）** | 不动 `finetune/` 微调管线；不改前端页面逻辑；不换数据库；不引入鉴权体系（留到下一个任务卡） |
| **验收标准** | 见第 3 节各阶段 DoD + 第 2 节总表 |
| **估时** | 约 9–11 人日（单人全职） |
| **依赖配合方** | 前端（对齐接口契约）、测试（一致性用例）、运维（镜像与 nginx） |

### 先问动机，再动手

"接 FastAPI"通常不是真需求，真需求是下面某一条。**问不出来就别开工**：

- 前端联调没有文档，靠翻后端代码猜字段 → 真需求是**契约**
- 参数校验散在各 handler，报错信息不统一 → 真需求是**校验与错误模型**
- 出问题查不到是哪个请求 → 真需求是**可观测**
- 代码评审时路由逻辑太长、没法单测 → 真需求是**分层与可测性**

动机决定后面每个决策怎么选。这就是为什么第 0 阶段不能跳过。

---

## 2. 阶段总览

| # | 阶段 | 人日 | 核心产出物 | 完成判据（DoD） |
|---|---|---|---|---|
| 0 | 立项对齐 | 0.5 | 任务卡（上表） | 目标/非目标/验收标准三方认可 |
| 1 | 现状摸底 | 0.5 | 路由清单、错误码表、SSE 事件协议 | 现有接口一条不漏地列出来 |
| 2 | 技术方案设计 | 1.5 | 技术方案 + 决策记录（ADR）+ 请求生命周期图 | 每个决策有"选 A 不选 B"的理由 |
| 3 | 方案评审 | 0.5 | 评审意见表 → 方案 v1.1 | 反对意见都有回应或采纳 |
| 4 | 接口契约先行 | 0.5 | OpenAPI 契约 + 前端 API 层改法 | 前后端对字段/错误码/事件名签字 |
| 5 | 骨架接入 | 0.5 | 能跑的 `app/main.py` 最小骨架 | `uvicorn app.main:app` 起来，`/docs` 可开 |
| 6 | 逐路由迁移 | 3 | 路由对照表 + 一条路由一个测试 | 全部路由迁完，旧入口仍可用 |
| 7 | 测试与一致性 | 1 | 单元测试 + 契约测试 + 双入口一致性测试 | 两个入口同请求响应一致 |
| 8 | 可观测 | 0.5 | request_id 贯穿 + 访问日志 + 指标 | 前端报错能靠 `X-Request-ID` 查到日志 |
| 9 | 部署与灰度 | 1 | Docker/nginx 配置 + 上线检查单 + 回滚手册 | 切流无回滚、有回滚就一把切回 |
| 10 | 复盘 | 0.5 | 复盘记录 | 记录返工点与决策得失 |

> **节奏要点**：第 5 阶段结束就必须能跑起来。工作是"小步可验证"，
> 不是"憋两周憋出个大 PR"。

---

## 3. 各阶段详细

### 阶段 0 · 立项对齐（0.5 人日）

- **动作**：填任务卡；逐个问提出方"你现在的具体痛点是什么、举例给我看"；把痛点写成可验证的句子。
- **产出**：任务卡。
- **反面教材**：接到"接个 FastAPI"就埋头写路由，做完发现前端要的是文档、运维要的是健康检查——返工。

### 阶段 1 · 现状摸底（0.5 人日）

**动作**：把现有接口当作一份"需要保持兼容的对外契约"，一条一条抄下来。

本仓库的摸底结果（这是真实存在的资产，别重写）：

| 现有资产 | 路径 | 摸底结论 |
|---|---|---|
| 框架无关 handler | `backend/app/api.py` | **这是资产，不是负债**。每个 handler 是 `(payload) -> (status, envelope)` 的纯函数 |
| 手写路由 | `backend/server.py` | 这是要被替换的**适配层**：`do_GET`/`do_POST`/`do_DELETE` 里的 `if/elif` |
| 错误码表 | `backend/app/errors.py` | 40xxx 调用方 / 50xxx 服务端 / 502xx 上游，已有统一 `fail()` |
| 日志 | `backend/app/logging_config.py` | request_id 走 `contextvars`，已有 `set_request_id` |
| 练习起点 | `backend/fastapi-practice/hello.py` | 8 行的 Hello World |

**产出物（三张表，缺一不可）**：

1. **路由清单**：方法 + 路径 + 入参 + 出参 + 错误码。例如
   `GET /api/kb/list` → `{page,size,q}` → `{items,total}` → `40001`
2. **错误码表**：`ErrorCode` 全量抄一遍，标注哪几个接口会抛
3. **SSE 事件协议**：`/api/chat/stream` 会推 `agent` / `token` / `retrieved` / `done` 四类事件，**事件名和字段是契约，改它等于改接口**

**本仓库摸底时会发现的三个事实**（这就是"摸底"的价值）：

- **双入口**：`server.py` 和 `app/main.py` 各有一套路由表，业务逻辑共用 `api.py`。好处是零依赖可跑，代价是两套路由必须同步维护。
- **校验会跑两遍**：`main.py` 里 `payload: ChatRequest` 由 pydantic 校验一次，`api.handle_chat` 里又 `ChatRequest(**payload)` 校验一次。
- **状态码处理不一致**：`main.py` 的 `/api/chat`、`/health`、`/api/stats`、`/api/context/{id}` 是 `status, body = ...; return body`，把 status 丢了；而同文件的 `/api/kb/upload`、`/api/kb/list`、`/api/kb/delete`、`/api/feedback` 却规规矩矩 `JSONResponse(status_code=status, ...)`。

**DoD**：拿这份路由清单，随便挑一条，能说出它在旧实现里走哪几行。

### 阶段 2 · 技术方案设计（1.5 人日）

这是整个任务最值钱的部分。**每个决策都要写成 ADR**（一条决策一段：背景 / 选项 / 选择 / 理由 / 代价）。

#### 决策记录（ADR）

| # | 决策点 | 选项 | 本仓库的选择 | 理由与代价 |
|---|---|---|---|---|
| D1 | 入口策略 | ① 单入口只留 FastAPI ② 双入口并存 | **②双入口** | 理由：零依赖可跑是差异化卖点，教学/离线演示场景不能强制 pip install。代价：两套路由表要同步，见 D5 的纪律 |
| D2 | 业务逻辑归属 | ① 搬进路由函数 ② 保留 `api.py` 框架无关 handler | **②防腐层** | 理由：逻辑不被框架绑架，可被 stdlib 入口和单测直接复用。代价：多一层转换、status 传递易出错 |
| D3 | 校验位置 | ① 只 FastAPI 层 ② 两层都校验 | 现状是②（**建议改①**） | 理由：② 是 D2 带来的税，同一份规则跑两遍，错误信息可能两套。改①要给 `api.py` 加"信任 typed 对象"的变体 |
| D4 | 同步/异步 | ① 全 `async def` + `run_in_threadpool` ② `sync def` 交给 FastAPI 线程池 ③ 混合 | 现状偏① | 要点：IO 等待让出事件循环，CPU 密集仍受 GIL 限制，所以用线程池而不是硬扛。**生成器不能这么包**（见 D7） |
| D5 | 状态码策略 | ① handler 的 status 必须透传 ② HTTP 恒 200，只看业务 `code` | **①** | 理由：状态码给网关/监控看，业务 code 给业务分支用，两者分工。纪律：**路由里禁止 `return body` 丢掉 status** |
| D6 | 错误模型 | 三路收敛：`AppError`、pydantic `RequestValidationError`、未知异常 | `main.py` 三个 `exception_handler` 收敛到 `{code,msg,data}` | 要点：**不把堆栈返回给调用方**，只写日志 |
| D7 | SSE 实现 | ① `StreamingResponse` + `run_in_threadpool` ② `iterate_in_threadpool` ③ 直接迭代 | 现状①**有问题** | `chat_service.chat_stream()` 是**生成器**，`run_in_threadpool(api.handle_chat_stream, ...)` 只是拿到生成器就返回了；真正的模型调用发生在迭代阶段、跑在事件循环线程上，**线程池那层没生效**，与 D4 的注释承诺不符 |
| D8 | OpenAPI 归属 | 谁维护 tag/summary/responses、怎么防漂移 | 路由上写 `tags`/`summary`/`responses` | 要点：契约测试对 `/openapi.json` 断言，防止代码改了文档没改 |
| D9 | 依赖注入 | ① 模块级单例 `services()` ② `Depends()` | 现状① | ①简单但难测（靠 `reset_services()` 清全局）；②更 FastAPI 但改动面大。**决议要写清什么时候换成②** |
| D10 | 中间件顺序 | CORS / request_id / 访问日志 / 异常兜底 谁先谁后 | CORS 在 `add_middleware`，request_id+日志在 `@app.middleware("http")` | 要点：`X-Request-ID` 要进响应头、要跨线程传（所以用 `contextvars` 而非 threadlocal） |

#### 产出物

1. 上表（ADR）
2. **请求生命周期图**（一张图，从 socket 到 SSE 字节）：
   `client → uvicorn → 中间件(request_id/日志) → 路由 → 校验 → run_in_threadpool → api.py handler → services/orchestrator → context engine / retriever / model → envelope → JSONResponse/StreamingResponse`
3. **回滚方案**：环境变量开关（默认走 FastAPI，异常时切回 stdlib 入口），以及"DB/知识库数据不因切换而变"的确认。

### 阶段 3 · 方案评审（0.5 人日）

自己过一遍不够，要模拟评审会。**评审该被问的问题清单**：

- 为什么不直接用 Flask / Django？→ 答：异步原生 + pydantic 校验 + OpenAPI 自动生成，正好覆盖前三个真需求
- 没有网络、装不了 fastapi 的环境怎么办？→ 答：D1 的双入口
- 双入口怎么保证行为一致？→ 答：D5 纪律 + 阶段 7 的一致性测试（**这条答不上来方案就别过**）
- SSE 放在 nginx 后面要注意什么？→ 答：`proxy_buffering off` + `X-Accel-Buffering: no`
- 阻塞调用把事件循环卡住怎么办？→ 答：D4 + D7（**这里必须承认 D7 现在的写法没生效**）
- `/docs` 谁维护、会不会漂移？→ 答：D8 + 契约测试
- 上线出问题怎么回滚？→ 答：env 开关 + 回滚手册

**产出**：评审意见表 → 方案 v1.1。**DoD**：每条反对意见有"采纳/驳回+理由"。

### 阶段 4 · 接口契约先行（0.5 人日）

**动作**：先定契约，再写实现。前后端据此并行，不用互相等。

- 冻结：URL、方法、请求字段与类型、响应 `{code,msg,data}`、业务错误码、SSE 事件名与字段
- 前端对照改 `frontend/src/api/index.ts`（它会把非 0 的 `code` 抛成带 code 的 `ApiError`）
- **兼容性规则**：SSE 加字段可以（前端忽略未知字段），改事件名/删字段不行

**产出**：契约表 + 前端改法说明。**DoD**：前端能照着契约先写 mock（`frontend/src/mock/index.ts` 就是干这个的）。

### 阶段 5 · 骨架接入（0.5 人日，必须能跑）

最小可运行骨架，顺序照抄即可：

1. `app = FastAPI(title=..., version=..., description=..., openapi_tags=[...])`
2. `add_middleware(CORSMiddleware, ...)`，`expose_headers=["X-Request-ID"]`
3. `@app.middleware("http")` 做 request_id + 访问日志 + 耗时 + 兜底异常
4. 三个 `exception_handler`：`AppError` / `RequestValidationError` / `Exception`
5. 只实现 `/health` 和 `/`，先跑通

**DoD**：`cd backend && uvicorn app.main:app --reload` 起来；`/docs` 打得开；`/health` 返回 `{code:0,...}` 且带 `X-Request-ID` 响应头。

### 阶段 6 · 逐路由迁移（3 人日）

**纪律**（这是工作流程里最容易崩的地方）：

- 一次只迁**一条**路由，迁完立刻补测试，绿了再迁下一条
- 按 tag 分组迁：`ops` → `chat` → `kb` → `feedback`
- **迁移期旧入口保持可用**（双跑），不要"改一半两边都不能用"
- 每条路由必须**显式透传 status**（D5）：`return JSONResponse(status_code=status, content=body)`

**产出**：路由对照表（旧 `server.py` 分支 ↔ 新 FastAPI 路由 ↔ 测试用例名）。本仓库的对照如下：

| 旧 `server.py` | 新 `app/main.py` | tag |
|---|---|---|
| `do_GET /health` | `@app.get("/health")` | ops |
| `do_GET /api/stats` | `@app.get("/api/stats")` | ops |
| `do_GET /api/kb/list` | `@app.get("/api/kb/list")` | kb |
| `do_GET /api/feedback` | `@app.get("/api/feedback")` | feedback |
| `do_GET /api/context/{sid}` | `@app.get("/api/context/{session_id}")` | chat |
| `do_POST /api/chat` | `@app.post("/api/chat")` | chat |
| `do_POST /api/chat/plan` | `@app.post("/api/chat/plan")` | chat |
| `do_POST /api/chat/stream` | `@app.post("/api/chat/stream")` | chat |
| `do_POST /api/kb/ingest` | `@app.post("/api/kb/ingest")` | kb |
| `do_POST /api/kb/upload` | `@app.post("/api/kb/upload")` | kb |
| `do_DELETE /api/kb/{source}` | `@app.delete("/api/kb/{source}")` | kb |
| `do_POST /api/feedback` | `@app.post("/api/feedback")` | feedback |

**DoD**：12 条路由全部有对照行、全部有测试；`server.py` 仍能启动并响应同一批请求。

### 阶段 7 · 测试与双入口一致性（1 人日）

三层测试，缺一层都不算完：

1. **单元测试**（`tests/test_api.py`，stdlib `unittest`，保持零依赖）——直接打 `api.py` handler，不经过 HTTP
2. **契约测试**——拉 `/openapi.json`，断言关键路径和字段存在；**防止"代码改了文档没改"**
3. **双入口一致性测试**（双入口架构下最重要、最容易漏）——同一请求分别打 `server.py` 和 FastAPI，**比较响应体与状态码是否一致**

**DoD**：`cd backend && python -m unittest discover -s tests -q` 全绿；`ruff check backend` 干净（CI 会跑）。

### 阶段 8 · 可观测（0.5 人日）

- `request_id`：入口取 `X-Request-ID`（没有就生成）→ 塞 `contextvars` → 日志每行带 `rid=` → 响应头回 `X-Request-ID`
- 访问日志字段固定：`method path status ms`
- `metrics.py` 环形缓冲记录最近 100 次请求 → `/api/stats` 喂看板
- **密钥字段自动打码**（`logging_config.py` 已有）

**DoD**：随便造一个 500，能靠响应头里的 `X-Request-ID` 在日志里定位到那一条。

### 阶段 9 · 部署与灰度（1 人日）

- 镜像：`backend/Dockerfile` 用 `python:3.11-slim` + `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- 反代：`frontend/nginx.conf` 里 `/api` 与 `/health` → `backend:8000`，**SSE 必须 `proxy_buffering off`**，同时后端响应头带 `X-Accel-Buffering: no`
- 持久化：`backend_data` 卷挂 `/app/data`（知识库 + 对话历史不随容器销毁）
- 一键起：`docker compose up --build`，前端 `http://localhost:8080`
- **上线检查单**：`/health` 返回的 `db_backend`/`cache_backend` 符合预期；`/docs` 可访问；SSE 实测是逐段输出不是一次性；`X-Request-ID` 有回传
- **回滚手册**：env 开关切回 stdlib 入口 / 回滚到上一个镜像 tag，一步到位

**DoD**：切流过程无中断；演练一次回滚并记录耗时。

### 阶段 10 · 复盘（0.5 人日）

写四个问题：哪个决策最值钱（通常是 D1 和 D5）、哪里返工了（通常是没做阶段 1 摸底）、`/docs` 有没有漂移、回滚演练暴露了什么。

---

## 4. 本仓库照抄清单

```bash
# 骨架起来
cd backend
uvicorn app.main:app --reload            # http://localhost:8000/docs

# 零依赖入口（对拍用）
python run.py                            # stdlib server.py

# 测试与 lint（与 CI 一致）
python -m unittest discover -s tests -q
ruff check backend

# 整栈
docker compose up --build                # 前端 http://localhost:8080
```

关键文件地图：

| 关注点 | 文件 |
|---|---|
| FastAPI 外壳（路由/中间件/异常） | `backend/app/main.py` |
| 框架无关业务 handler | `backend/app/api.py` |
| 请求/响应模型 | `backend/app/schemas.py` |
| 错误码与统一响应 | `backend/app/errors.py` |
| request_id 与日志 | `backend/app/logging_config.py` |
| 手写路由（对拍基准 / 待收口） | `backend/server.py` |
| 前端 API 层 | `frontend/src/api/index.ts` |
| 镜像与反代 | `backend/Dockerfile`、`frontend/nginx.conf` |
| CI 三/四道门 | `.github/workflows/ci.yml` |

---

## 5. 常见翻车点

1. **跳过阶段 1**，凭印象迁路由 → 漏接口、漏错误码，上线才发现
2. **改了 SSE 事件名/字段**，前端静默不渲染 → 契约阶段就该锁死
3. **路由里 `return body` 丢 status** → 网关/监控看到的状态码是错的（本仓库现状已有此隐患）
4. **给生成器套 `run_in_threadpool`** → 以为异步了，其实模型调用还堵在事件循环上
5. **双入口没有一致性测试** → 两边行为慢慢漂移，某天"离线模式"和"正式模式"答案不一样
6. **`/docs` 手工维护** → 三个月后文档和代码对不上，前端不再信任文档
7. **迁移期新旧都不完整** → 要么全绿要么全红，永远保持一条可用路径
8. **只测 happy path** → 400/404/415/500 和 `/api/chat/stream` 报错路径没人测

---

## 6. 这次工作怎么讲清楚

一句话版本：**"我把接口层从手写 stdlib 路由迁到 FastAPI，用防腐层保住业务逻辑不被框架绑架，用双入口 + 一致性测试保住离线可跑，最终拿到 `/docs`、自动校验、统一错误码和可观测。"**

三个能展开的深水点：

- **双入口的代价管理**：不是"两个都留着"，而是"`api.py` 是单一事实源，两个 HTTP 外壳都只是适配器"，并有测试保证不漂移
- **异步与 GIL**：IO 等待让出事件循环，CPU 密集受 GIL 限制，所以阻塞型调用进线程池；并诚实指出 SSE 生成器那一处线程池没生效
- **统一响应模型**：HTTP 状态码给网络层，业务 `code` 给业务层，两者分离且都不丢
