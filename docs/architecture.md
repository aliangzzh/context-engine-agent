# 架构说明

本项目把 **Context Engine、多 Agent 协作、RAG 知识库、模型微调、全栈交付与容器化部署**串成一个可运行的完整系统。

```
┌────────────────────────────────────────────────────────────┐
│                        前端 (Vue3 / Vite)                   │
│   聊天界面  +  Context 上下文面板  +  Agent 协作链面板        │
└──────────────────────────┬─────────────────────────────────┘
                           │ HTTP / SSE (stream)
┌──────────────────────────▼─────────────────────────────────┐
│                  后端 (Python / FastAPI)                    │
│                                                            │
│   /api/chat        ──全量回答                                │
│   /api/chat/stream ──SSE 流式（agent 步、token、上下文）      │
│   /api/kb/ingest   ──知识入库                                │
│                                                            │
│  ┌──────┐   ┌─────────────┐   ┌─────────────────────────┐  │
│  │Agent │──▶│Context Engine│──▶│  Model Backend          │  │
│  │Orch. │   │ (预算/裁剪)  │   │  fake | qwen_api |      │  │
│  └──┬───┘   └─────────────┘   │  local_ft (LoRA 微调)    │  │
│     │                          └─────────────────────────┘  │
│  ┌──▼───────┐   ┌─────────────┐                             │
│  │Retriever │   │  Tools      │                             │
│  │BM25/Emb  │   │ wthr/calc   │                             │
│  └──────────┘   └─────────────┘                             │
└────────────────────────────────────────────────────────────┘
```

## ① Context Engine

`backend/app/context/`

- **装配**：`ContextEngine.build()` 把「系统指令 / 检索到的知识 / 对话历史（压缩）/ 工具结果」组织成一组带**优先级**的 context slot。
- **Token 预算**：`TokenBudget.allocate()` 按优先级从低到高裁剪，其中 `system` slot **按 kind 受保护、永不参与裁剪**（有几条 system 槽都保得住），数量兜底只留 `min_keep=1`；其余按优先级裁（先裁对话历史，再裁检索/工具结果）。摘要 slot 的优先级高于历史（压缩过的信息密度更高），所以不会再出现"摘要第一个被裁"。**裁剪后仍然超预算时（例如 system 指令本身就超预算）不静默吞掉**：`Context.over_budget` 会如实上报，前端上下文面板据此显示告警条。
- **历史滑窗 + 摘要压缩**：`HistoryManager.trim()` 只保留最近 `max_turns` 轮完整历史，更早的内容折叠成滚动的**摘要 slot**，而不是像常见 demo 那样把全部历史往 prompt 里灌。这一步解决了"对话越长上下文越大、最终爆窗"的问题。摘要由 `HistorySummarizer` 调**同一个模型后端**生成（`AppServices` 注入）；模型调用失败降级为规则模板，**离线 `FakeModel` 也走同一条降级路径**（`is_llm=False`）——假模型不认摘要提示词，会把整段旧对话原样吐回，让摘要槽比原文更长（实测 146 > 87 tokens），那是"重复注入"不是压缩，所以不假装。
- **检索重排 / 优先级**：`Reranker.rerank()` 对检索结果用"原始分数 + 词项重叠"打分并排序，按排名赋予优先级权重。
- 常见 RAG 项目里"多轮记忆 = 全量 JSON 回灌"是短板；这里把它升级成真正的**上下文引擎**。

## ② 多 Agent 协作

`backend/app/agents/`

- **Router**：判定意图，输出执行计划（检索 / 调用工具 / 直接回答）。
- **Retrieve Agent**：从知识库检索上下文。
- **Tool Agent**：调用工具（真实公开免 key 的 Open-Meteo 天气 API、本地计算器、时间）。
- **Writer Agent**：汇总检索 + 工具结果生成最终回答。
- **Middleware**：`before_run / after_run / before_node / after_node` 生命周期钩子，对应 LangChain 的 `before/after_model`、`wrap_tool_call` 等。
- **Trace**：记录每一步的 node/kind/summary，前端据此渲染"Agent 协作链"。

> 我们自研了一个轻量多 Agent 编排器（离线可跑），但它与 LangGraph 一一对应：
> `add_node`（各 agent）→ `add_edge` 与条件边（router 路由）→ `StateGraph`（公共 state）→ `checkpointer`（会话持久化）。当需要真正"框架级"实现时，可无痛迁移到 LangGraph。

## ③ LoRA / QLoRA 微调

`backend/finetune/`

- `prepare_data.py`：把领域知识合成指令问答数据集（Qwen2.5-Instruct 的 messages 格式）。
- `train_lora.py`：`PEFT.LoraConfig` + `TRL.SFTTrainer`，可选 `bitsandbytes` 4bit 量化（**QLoRA**）。在 8GB 显存上对 `Qwen2.5-0.5B-Instruct` 跑小规模（几十步）即可出真实训练曲线和 adapter。
- `eval_lora.py`：在保留样例上对比**微调前 / 微调后**的生成质量（token 级 F1 + 原始输出），量化"有提升"。
- `export_adapter.py`：把 base + adapter 合并成独立模型，供 `LocalFTModel` 推理。
- 与系统打通：微调后的模型作为 `local_ft` 后端，可直接当 Agent 的大脑（`FINE_TUNE_*` 配置）。

## ④ 全栈（Python / Node.js / Git）

- 后端：Python + FastAPI + SSE 流式。
- 前端：Node.js + Vite + Vue3，含聊天、上下文面板、Agent 链面板。
- Git：多提交、前后端分目录、`.gitignore`、README、架构文档。

## ⑤ Docker 部署 / CI

```
client  ──►  frontend (nginx:alpine)  ──/api, /health──►  backend (uvicorn:8000)
             ├─ 托管 /usr/share/nginx/html（Vue3 构建产物）
             └─ try_files → /index.html（SPA 路由回退）
```

- **前端镜像**：多阶段 `node:20-alpine`（`npm ci` → `vue-tsc` 类型检查 + `vite build` → `dist`）+ `nginx:alpine` 托管。
- **后端镜像**：`python:3.11-slim` + `uvicorn app.main:app`，`/app/data` 用命名卷持久化（知识库、对话历史）。
- **SSE 关键点**：Nginx `location /api/` 里 `proxy_buffering off`，否则流式 token 会被缓冲、前端收不到逐段输出。
- **Compose**：`docker compose up --build` 一键起整栈，前端暴露 8080。
- **CI（GitHub Actions）**：push/PR 跑「后端 ruff lint + 后端单元测试 + 前端构建（含类型检查）+ `docker compose build` 校验」四道门。

## ⑥ 存储与缓存（SQLite / MySQL + Redis）

```
                ┌── ChatStore（SQL, 抽象层）──► turns 表
App/Agent ──────┤                （历史持久化）
                └── Retriever.search() ──► Cache（LRU/Redis）
                                    （检索结果，add_chunks 时清空）
```

- **关系型存储**：`backend/app/storage/history_store.py` 用真正的 SQL 读写 `turns` 表（`CREATE TABLE` / 参数化 `INSERT` / `SELECT ... WHERE session_id=? ORDER BY id` / `DELETE` 后整体写回）。接口不变（`load/save/append`），调用方零改动。
- **默认 SQLite / 可切 MySQL**：`db.py` 按 `DATABASE_URL` 选方言（`sqlite` 用 stdlib `sqlite3`；`mysql+pymysql://...` 用 `pymysql`，DDL 相应用 `AUTO_INCREMENT`/`utf8mb4`），换后端只改配置。
- **缓存**：`cache.py` 提供 `RedisCache`（`REDIS_URL` 存在时）或进程内 `LocalLRU`（默认、零依赖、带 TTL + LRU 淘汰）；`Retriever.search()` 以 `backend+k+query` 为键缓存结果，`add_chunks()` 后自动清空，避免命中过期检索。值用 JSON 序列化，同一套代码兼容两种缓存后端。
- **可观测**：`/health` 返回 `db_backend`（sqlite/mysql）与 `cache_backend`（lru/redis），部署后一眼看清用的哪种。

> 相比"轻量 JSON 实现"，这里换成了真正的数据库读写 + 缓存 + 可切外部服务。
> 诚实说明：本地验证一直用 SQLite + 进程内 LRU；MySQL / Redis 是配置驱动的可选外部服务，
> 代码路径（方言、`AUTO_INCREMENT`、`ex=ttl`）已写好但**尚未在真实 MySQL / Redis 上实测**，上线前需要实测。

## ⑦ 接口工程化：统一响应 / 错误码 / 日志 / 装饰器

```
client ──► server.py / app/main.py ──► app/api.py（框架无关 handler）
                    │                        │
                    │  request_id + 访问日志  │  safe_call 统一异常 -> {code,msg,data}
                    ▼                        ▼
              logging_config.py          errors.py（40xxx/50xxx/502xx）
```

- **一处业务逻辑，两个 HTTP 入口**：`app/api.py` 里的 handler 都是
  `(payload) -> (status, envelope)` 的纯函数；stdlib 服务器与 FastAPI 都只是它的外壳。
- **统一响应体**：`{code, msg, data}`；HTTP 状态码表达传输层结果，业务 `code` 表达
  业务结果，前端按 `code` 分支（`frontend/src/api/index.ts` 会抛带 code 的 `ApiError`）。
- **异常处理**：`error_from_exception()` 把 `AppError` / pydantic 校验失败 / 未预期异常
  映射成 400/404/415/500，且**不把堆栈返回给调用方**，只写日志。
- **日志**：`logging_config.py` 输出 `时间 级别 logger rid=xxx 事件 k=v`，`request_id`
  放在 `contextvars` 里，跨线程/跨模块都能带上；密钥字段自动打码。响应头也回 `X-Request-ID`，
  排查时"前端报错 → 拿 id 查日志"一条线走通。
- **装饰器**（`decorators.py`）：`@timed` 记耗时（同时喂给看板）、`@retry` 给外部 API 做
  指数退避重试、`@cache_result` 缓存聚合查询。
- **指标**：`metrics.py` 用环形缓冲记录最近 100 次请求，`/api/stats` 喂给看板图表。

## ⑧ 前端三页与交互

| 页面 | 关键交互 | 说明 |
|---|---|---|
| `#/` 对话 | SSE 流式渲染、上下文面板、Agent 链、**标记 badcase（弹窗 + 表单校验）** | 一次请求结束即可把坏回答送进反馈库 |
| `#/kb` 知识库 | **文件上传（拖拽/multipart）**、文本入库（校验）、**列表 + 分页 + 搜索**、删除确认 | 管理端；所有读都是 SQL |
| `#/dashboard` 看板 | token 占用折线、badcase 分布、分块长度分布、工具调用次数、最近 badcase | 每 5 秒轮询 `/api/stats` |

前端结构、组件清单与"联网后如何换成 vue-router / Element Plus / ECharts"写在
`docs/frontend.md`。
