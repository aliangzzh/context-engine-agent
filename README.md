# Context Engine + Multi-Agent QA

一个覆盖 **Context Engine（上下文引擎）→ 多 Agent 协作 → RAG 知识库 → 工具调用 → 模型微调 → 全栈交付 → 容器化部署** 的大模型应用项目。

**开箱即跑**：不配置任何 API key、不安装任何第三方包，也能用离线 `fake` 模型 + BM25 检索把完整链路跑起来。

## 特性

- **上下文引擎**：上下文装配、token 预算裁剪、历史滑窗 + 模型摘要（失败降级）、检索重排/优先级、超预算如实上报。
- **多 Agent 编排**：Router → Retrieve / Tool / Writer，带 middleware 生命周期钩子和完整 trace。
- **RAG + 知识库管理**：BM25 离线检索 / DashScope 向量检索；文档切分策略可切换（句边界 / 定长）；上传、分块列表分页搜索、删除全走 SQL。
- **工具调用**：天气（真实免 key API）/ 计算器 / 时间；从自然语言里抽参数（抽不到就向用户追问），带失败重试与耗时统计。
- **badcase 闭环**：对话页把回答标记为 badcase → 落 `feedback` 表 → 看板统计分布 → 补知识库 → 复测。
- **模型后端可插拔**：`fake`（离线演示）/ `qwen_api`（通义千问 DashScope）/ `local_ft`（本地 LoRA 微调模型）。
- **LoRA/QLoRA 微调**：`Qwen2.5` 领域微调管线 + 前后对比评测 + 导出合并模型。
- **存储与缓存**：`turns` / `kb_chunks` / `feedback` 三张表（默认 SQLite，`DATABASE_URL` 可切 MySQL）+ 检索/聚合缓存（默认 LRU，`REDIS_URL` 可切 Redis），写操作走事务。
- **接口工程化**：统一响应体 `{code,msg,data}` + 分段错误码 + 结构化日志（request_id / 耗时）+ OpenAPI 文档 + 85+ 单元与接口测试。
- **效果评测与回归门**：`backend/eval/` 自带 10 篇独立语料（含 4 篇干扰文档）+ 30 题五类题库（意图路由 / 工具参数 / RAG 召回 / 答案事实 / 兜底拒答）+ 2 套留出集；零依赖跑分器输出分类指标与逐条失败归因，`--check` 与冻结基线对比做 CI 回归门。真实消融数据见 `docs/evaluation.md`（总通过率 0.733 → 1.000）。
- **前端三个页面**：对话（SSE 流式 + 上下文/Agent 面板）、知识库管理（上传 / 表单校验 / 列表分页 / 删除弹窗）、运行看板（图表）。离线环境用自研轻量组件，切换方案见 `docs/frontend.md`。
- **部署**：Dockerfile × 2 + Nginx 反代（SSE 关缓冲）+ docker compose + GitHub Actions（lint / 测试 / 前端构建 / compose 校验）。

## 快速开始

### 1. 后端（Python）

```bash
cd backend

# 建虚拟环境并激活
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux

# 安装依赖
pip install -r requirements.txt

# 启动（零依赖 stdlib 服务器）
python run.py                     # http://localhost:8000
```

- **不配置任何 API key 也能跑通全链路**：默认使用离线 `fake` 模型 + BM25 检索，
  路由 / 上下文引擎（预算裁剪 + 滑窗摘要）/ 工具调用 / SSE 流式 / 运行看板 都能演示。
  注意离线模型的回答会带 `【离线演示】` 前缀——它只回显上下文，不生成真实答案。
- 想要 FastAPI 版（含 `/docs` Swagger 文档）：`pip install fastapi uvicorn` 后
  运行 `uvicorn app.main:app`；逻辑与 `server.py` 完全一致（都调用 `app/api.py`），
  `/docs` 就是可直接交给前端的接口文档。

**接入真模型（通义千问）需要两步，缺一不可：**

```bash
pip install -r requirements-llm.txt      # ① 装依赖
cp .env.example .env                     # ② 填 DASHSCOPE_API_KEY=sk-xxx
```

> ⚠️ **只填 key 而不装依赖，项目会静默退回离线模型**——不报错，界面上仍显示
> `qwen_api`。这是最容易踩的坑。验证方法：`curl http://localhost:8000/health`，
> 看 **`model`** 字段是否为 `qwen_api`；若 `chat_backend` 是 `qwen_api` 但
> `model` 是 `fake`，就说明依赖没装。

### 2. 前端（Node.js / Vue3）

```bash
cd frontend
npm install
npm run dev              # http://localhost:5173
```

页面：`#/` 对话 · `#/kb` 知识库管理 · `#/dashboard` 运行看板。
接口没就绪时可以打开右上角 **Mock 数据** 开关，用假数据把页面流程跑通。

### 3. 微调（可选，需 GPU）

```bash
cd backend
python -m venv .venv-ft && source .venv-ft/bin/activate  # 或用 .venv\Scripts\activate
pip install torch transformers peft trl datasets accelerate bitsandbytes
python finetune/prepare_data.py              # 生成数据集
python finetune/train_lora.py --steps 40 --no-4bit   # 或 --use-4bit 做 QLoRA
python finetune/eval_lora.py                 # 前后对比
python finetune/export_adapter.py            # 合并为独立模型
```

微调完成后把 `config.FINE_TUNE_BASE_MODEL` 指向 base 模型，后端会自动优先使用 `local_ft` 后端。

## Docker 部署（一条命令起整个栈）

本项目提供完整的 Docker 化部署（后端 FastAPI + 前端 Nginx 反向代理 + GitHub Actions CI）。

```bash
# 1) 可选：配置通义千问 key（不填则离线 fake 模型也能跑）
cp backend/.env.example backend/.env        # 在 .env 里填 DASHSCOPE_API_KEY

# 2) 一键构建并启动（前端 http://localhost:8080）
docker compose up --build

# 前端：http://localhost:8080
#   - Nginx 托管 Vue3 构建产物（/ 下的 SPA）
#   - /api 与 /health 反向代理到 backend:8000（SSE 已关闭 proxy_buffering）
# 持久化：backend_data 卷挂在 /app/data，知识库与对话历史不随容器销毁
```

**服务拆分**：
| 服务 | 镜像构建 | 端口 | 说明 |
|---|---|---|---|
| `backend` | `backend/Dockerfile` | 8000（内部 `expose`） | FastAPI + uvicorn，`app.main:app` |
| `frontend` | `frontend/Dockerfile` | 宿主 8080 → 容器 80 | 多阶段：node 构建 → nginx 托管 + 反代 |

**CI（`.github/workflows/ci.yml`）**：push / PR 时跑
1. 后端 Lint（`ruff check backend`）
2. 后端单元测试（`python -m unittest discover -s tests`，含评测回归门）
3. Agent 效果评测回归门（`python -m eval.run --check`）+ 打印两套留出集
4. 前端构建（`vue-tsc` 类型检查 + `vite build`）
5. 校验 `docker compose build` 可成功

> `frontend/package-lock.json` 已提交，所以 Docker / CI 用 `npm ci` 做可复现构建。

## 存储与缓存（SQLite/MySQL + Redis）

对话历史的持久化是**关系型数据库读写**（真正的 `CREATE TABLE / INSERT / SELECT / DELETE`），检索结果另有一层缓存。

| 层 | 默认 | 切外部服务 | 说明 |
|---|---|---|---|
| **会话历史** | SQLite（stdlib `sqlite3`，离线零依赖） | `DATABASE_URL=mysql+pymysql://user:pass@host:3306/dbname` | `turns` 表一张一行（session_id / user_text / assistant_text / created_at），存储被抽象在 `ChatStore` 后面，换后端只改配置 |
| **知识库元数据** | 同上 | 同上 | `kb_chunks` 表：来源 / 分块 / md5 指纹 / 入库时间，管理页的列表、分页、搜索、删除都是 SQL |
| **badcase 反馈** | 同上 | 同上 | `feedback` 表：会话 / 问题 / 回答 / 类型 / 备注，看板按类型 `GROUP BY` 出分布 |
| **缓存** | 进程内 LRU（stdlib，离线零依赖） | `REDIS_URL=redis://localhost:6379/0` | 缓存检索结果（key = backend+k+query）与聚合查询，`add_chunks` 时自动清空失效缓存 |

- 存储层：`backend/app/storage/`（`db.py` 连接 + 建表 + 事务；`history_store.py` 会话历史；`repo.py` 知识库/反馈仓储；`cache.py` LRU/Redis）。
- **写操作走事务**：`save()` 是"先删后写"，中途失败会整体回滚（有专门的回归测试）。
- 跨线程安全：HTTP 服务器是多线程的，SQLite 连接用 `check_same_thread=False` + 锁串行化（也有并发回归测试）。
- `health` 接口返回 `db_backend`（sqlite/mysql）和 `cache_backend`（lru/redis），方便自查。
- 切外部服务需 `pip install pymysql` / `pip install redis`（见 `requirements.txt` 注释）。

## 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查（含实际生效的 chat/retrieval/db/cache 后端） |
| GET | `/api/stats` | 看板数据：知识库规模 / badcase 分布 / 最近请求指标 / 运行时配置 |
| POST | `/api/chat` | 一次性返回完整回答 |
| POST | `/api/chat/stream` | SSE 流式（`agent` / `retrieved` / `token` / `done` / `error` 事件） |
| POST | `/api/chat/plan` | 只看路由与工具计划 |
| POST | `/api/kb/ingest` | 文本入库（JSON） |
| POST | `/api/kb/upload` | **文件上传入库**（multipart/form-data，自研解析，免 `python-multipart`） |
| GET | `/api/kb/list?page&size&q` | 知识库列表（SQL 分页 + 搜索） |
| DELETE | `/api/kb/{source}` | 按来源删除（同时清检索索引与 md5 指纹） |
| POST | `/api/feedback` | 提交 badcase |
| GET | `/api/feedback?page&size` | badcase 列表 |
| GET | `/api/context/{session_id}` | 会话历史（上下文面板用） |

**统一响应体**：成功 `{"code":0,"msg":"ok","data":{...}}`；失败 `{"code":40001,"msg":"...","data":null,"detail":{...}}`。
错误码分段：`40xxx` 调用方 / `50xxx` 服务端 / `502xx` 上游（模型、检索）。HTTP 状态码与业务 `code` 分离。
每个响应带 `X-Request-ID`，与后端日志行里的 `rid=` 对应 —— 排查"接口通了但页面没显示"时先拿这个 id 查日志。

## 测试与 Lint

```bash
cd backend
python -m unittest discover -s tests -q      # 103 个测试：核心 / 存储 / 接口 / 评测
pip install ruff && ruff check backend       # Lint（同一份配置也在 CI 里跑）

python -m eval.run                           # Agent 效果评测（30 题开发集）
python -m eval.run --check                   # 与 baseline.json 比，回退则 exit 1

cd ../frontend
npm run typecheck                            # vue-tsc 类型检查
npm run lint                                 # 需要先装 eslint（见 eslint.config.js 头部说明）
```

测试分三层 + 评测：`test_core.py`（上下文引擎 / 摘要 / 工具参数抽取）、`test_storage.py`
（SQL 读写 / 分页 / 事务回滚 / 缓存 / 跨线程）、`test_api.py`（handler 层 + 真起服务器的 HTTP 层）、
`test_eval.py`（题集完整性 + 回归门 + 每个优化点的定点单测）。

## 目录结构

```
context-engine-agent/
├── backend/
│   ├── app/
│   │   ├── context/      # ① Context Engine（预算裁剪 + 滑窗 + 模型摘要）
│   │   ├── agents/       # ② 多 Agent 编排 + 工具（含参数抽取）
│   │   ├── retrieval/    # RAG 检索（BM25 / DashScope）+ 切分 + 知识库管理
│   │   ├── storage/      # SQLite/MySQL 存储（历史/知识库/badcase）+ LRU/Redis 缓存
│   │   ├── models/       # ③ 模型后端（fake / qwen_api / local_ft）
│   │   ├── errors.py     # 统一错误码与响应体
│   │   ├── logging_config.py  # 结构化日志 + request_id
│   │   ├── decorators.py # @timed / @retry / @cache_result
│   │   ├── multipart.py  # 自研 multipart 解析（免依赖）
│   │   ├── metrics.py    # 看板指标采集
│   │   ├── api.py        # 框架无关的 handler（两个 HTTP 入口共用）
│   │   ├── main.py       # FastAPI（OpenAPI 文档）
│   │   └── services/
│   ├── server.py         # 零依赖 stdlib HTTP 服务器
│   ├── mcp_server.py     # 零依赖 MCP Server（JSON-RPC 2.0 over stdio），复用已有工具
│   ├── finetune/         # ③ LoRA/QLoRA 微调管线
│   ├── eval/             # ⑤ 效果评测：独立语料 + 30 题题库 + 2 套留出集 + 回归门
│   └── tests/            # 单元测试 + 接口测试 + 评测回归测试
├── frontend/             # ④ Vue3 + TS：对话 / 知识库 / 看板三页 + nginx.conf
├── .github/workflows/    # CI：lint + 测试 + 前端构建 + compose 校验
├── docker-compose.yml
├── ruff.toml / .editorconfig
└── docs/                 # 架构、前端、AI 辅助、Code Review
```

## 文档

| 文档 | 内容 |
|---|---|
| `docs/architecture.md` | 架构设计与模块划分 |
| `docs/frontend.md` | 前端实现说明，以及切换主流方案的步骤 |
| `docs/evaluation.md` | **效果评测**：题库与语料设计、指标口径、消融数据（0.733 → 1.000）、留出集与已知边界 |
| `docs/ai-assisted.md` | AI 辅助开发的记录与边界 |
| `docs/code-review.md` | 代码审查记录 |

## 设计取舍

- **上下文引擎**：不做历史全量回灌，而是「预算 + 优先级 + 滑窗 + 摘要压缩」。上下文超限时的裁剪顺序、system 保护、`over_budget` 上报都有明确策略并被测试覆盖。
- **多 Agent**：Router → Retrieve / Tool / Writer 分层编排，middleware 提供生命周期钩子，每次请求留下完整 trace（可对照 LangGraph 的节点 / 边 / 状态 / 检查点理解）。
- **工具调用**：`extract_args` 从自然语言里抽参数，抽不到就向用户追问；带失败重试与耗时统计，而不是把整句话直接塞给工具。
- **badcase 闭环**：标记 → 落库 → 看板分布 → 补知识库 → 复测，形成可度量的迭代回路。
- **效果评测**：语料与线上库解耦（同一 commit 分数可复现）、五类指标分开量而不是一个笼统"准确率"、留出集不参与调参；相关性阈值在开发集上标定并做成环境变量，换语料必须重新标定。
- **接口工程化**：统一响应体 + 分段错误码 + `request_id` 日志 + OpenAPI + 三层测试，出问题能顺着 `request_id` 查到根因。
- **模型微调**：Qwen2.5 + QLoRA（4bit）+ PEFT，保留前后对比数据，评测方法可复现。
- **零依赖优先**：stdlib HTTP 服务器、自研 multipart 解析、进程内 LRU、离线 `fake` 模型后端，目标是在无网络、无第三方包的环境下也能完整演示。

## 已知限制

1. **微调**是「小模型 + 小数据量」的验证性结果，重点在完整管线与评测方法，不代表生产级效果。
2. **MySQL / Redis** 是配置驱动的可选外部服务，代码路径（方言、`AUTO_INCREMENT`、`ex=ttl`）已写好，但**尚未在真实 MySQL / Redis 上实测**，上线前需要实测。
3. **前端**组件库 / 路由 / 图表是离线环境下的自研轻量实现，切换到主流方案的步骤写在 `docs/frontend.md`。
4. **评测**的口径与阈值边界：相关性门控阈值在开发集上标定（`RELEVANCE_MIN_COVERAGE=0.35`），换语料需重新标定；留出集里的边界争议项（`现在北京时间几点？` 被判为工具+检索）如实记录在 `docs/evaluation.md`，没有为它继续调参。
4. `npm run lint` 需要先自行安装 eslint（离线环境默认未装，见 `eslint.config.js` 头部说明）。
