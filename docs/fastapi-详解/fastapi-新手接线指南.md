# FastAPI 接入：新手开发流程 + 接线图

> 面向"第一次把 FastAPI 接进一个已有项目"的人。
>
> 上一份 `fastapi-接入工作流程.md` 讲的是项目经理视角（任务卡、评审、DoD）。
> 这一份讲**代码视角**：从零开始怎么一步步接、FastAPI 和项目其他部分
> 到底靠什么连在一起、一个请求怎么走完全程、你会卡在哪。
>
> 全部结论都来自本仓库的真实代码（`context-engine-agent/`），不是通用教科书。

---

## 0. 先建立三个概念（新手最缺的就是这个）

### 概念一：什么叫"接入"？其实有三层，难度完全不同

| 层次 | 干什么 | 难度 | 新手常犯的错 |
|---|---|---|---|
| **第一层：装依赖** | `pip install fastapi uvicorn` | ⭐ | 以为这就叫接入了 |
| **第二层：挂路由** | 写 `@app.post("/api/chat")`，让 URL 能通 | ⭐⭐ | 以为路由写完就完了 |
| **第三层：接线** | 让路由里的代码能拿到项目已有的检索、模型、数据库、上下文引擎 | ⭐⭐⭐⭐⭐ | **根本不知道还有这一层** |

**90% 的新手卡在第三层。** 路由写法本身是背下来的，难点是：
"我这个 `/api/chat` 要调项目里那个 `AgentOrchestrator`，它需要 retriever、model、history、context_engine 四个东西——这四个从哪来？谁 new 的？什么时候 new？"——这就是"接线"。

### 概念二："连接"只有两种方式

1. **直接 import + 自己 new**：`from ..models import get_model_backend` 然后 `self.model = get_model_backend()`
2. **别人塞给你（依赖注入）**：`def __init__(self, retriever, model, ...)`，谁 new 谁负责凑齐

本仓库两种都用：**工厂函数负责造**（`get_model_backend()`），**构造函数负责收**（`AppServices`、`AgentOrchestrator`）。这是最标准的做法。

### 概念三：一条铁律——依赖只能单向

```
HTTP 层  →  服务层  →  领域层  →  基础设施层
(main.py)  (services)  (agents/context/retrieval)  (storage/models)
```

**反过来不行。** `context/engine.py` 里**绝对不能**出现 `from fastapi import ...`。
一旦出现，你的业务逻辑就被框架绑架了，以后想换框架、想写单测都动不了。

> 本仓库能做到这一点，是因为有个 `app/api.py` 当**防腐层**：
> 它里面的 handler 是纯 Python 函数，不知道 FastAPI 存在。
> 好处你马上能看到——同一个 `api.py`，既被 FastAPI(`main.py`) 调用，
> 又被纯 stdlib 服务器(`server.py`) 调用，逻辑一模一样。

---

## 1. 开发流程：按"每天都能跑起来"切分

新手最容易犯的错是"憋一个大招"——写三天，一跑全是错，不知道从哪查。
正确的节奏是：**每一步都留下一个能跑的东西**。

### Day 1：让空壳跑起来（半天）

**做什么**：建 `app/main.py`，只放 app 实例 + `/health`，不加任何业务。

```python
from fastapi import FastAPI
app = FastAPI(title="Context Engine + Multi-Agent QA")

@app.get("/health")
async def health() -> dict:
    return {"code": 0, "msg": "ok", "data": {"status": "ok"}}
```

**跑**：`cd backend && uvicorn app.main:app --reload`
**验证**：打开 `http://localhost:8000/docs`，能看到接口列表；`/health` 返回 JSON。

**达到什么**：你有了一个能跑的 HTTP 服务。**这一步什么都不接，就是故意的。**

### Day 2：接第一条真实路由（半天）——体会"接线"

**做什么**：把 `/health` 改成调项目里已有的业务代码。

```python
from . import api            # ← 这就是"接线"：连到已有业务
from starlette.concurrency import run_in_threadpool

@app.get("/health")
async def health() -> dict:
    status, body = await run_in_threadpool(api.handle_health)
    return body
```

**你会在这里第一次遇到核心问题**：`api.handle_health` 凭什么能用？
→ 因为它内部会自动把整个服务栈组装起来（见下面第 2 节）。
**这就是"接线"的真面目**：你不需要在路由里 new 任何东西。

**验证**：`/health` 现在返回的 `data` 里有 `chat_backend` / `db_backend` / `cache_backend`，
说明它真的连上了项目的配置和存储层。

### Day 3–4：接一条真实业务路由（1–2 天）——接线重头戏

**做什么**：接 `/api/chat`，要有请求体、校验、错误处理。

顺序很重要，**按这个顺序做**：

1. 先在 `app/schemas.py` 里定义请求模型（pydantic）：
   `class ChatRequest(BaseModel): session_id: str; message: str`
2. 写路由：`async def chat(payload: ChatRequest) -> dict:`
3. 调 handler：`status, body = await run_in_threadpool(api.handle_chat, payload.model_dump())`
4. 加错误处理（`AppError` / 校验失败 / 未知异常三个 exception_handler）

**你会在这里遇到**：`status` 怎么办？handler 返回 `(状态码, 响应体)` 两个值。
新手最容易写成 `return body` 把状态码丢了——**这就是本仓库现在真实的 bug**
（`main.py` 里 `/api/chat`、`/health`、`/api/stats`、`/api/context/{id}` 都丢了，
而 `/api/kb/upload`、`/api/kb/list` 却规规矩矩传了 `JSONResponse(status_code=status, ...)`）。
**正确写法**：`return JSONResponse(status_code=status, content=body)`

### Day 5：接流式（SSE，半天到一天）

**做什么**：`/api/chat/stream` 用 `StreamingResponse`。

```python
@app.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest):
    status, events = await run_in_threadpool(api.handle_chat_stream, payload.model_dump())
    async def gen():
        for evt in events:
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

**你会在这里遇到最坑的一点**：`events` 是个**生成器**。
`run_in_threadpool(api.handle_chat_stream, ...)` **只是拿到生成器就返回了**，
真正的模型调用发生在 `for evt in events` 迭代的时候——那时已经回到事件循环线程了。
**线程池那一层等于没生效。** 本仓库现在就是这样。正确做法是用
`starlette.concurrency.iterate_in_threadpool(events)`，或者干脆用 `def`（同步）路由让 FastAPI 自己处理。

> 为什么你原来的写法"看起来对"？因为生成器函数**调用时不执行函数体**，
> 只返回一个生成器对象。这是新手理解 Python 生成器最常见的误区。

### Day 6：接配置 / 存储 / 缓存（半天）

**做什么**：把硬编码的东西挪到 `config.py`，用环境变量控制。

本仓库已成型，你要理解的是这条链：
`config.py`（读环境变量）→ `effective_*()` 函数（判断实际生效的后端）→ 各处引用。
`/health` 会把这些真实生效的后端返回出来，**这就是"可观测"的入门做法**。

### Day 7：测试 + 前端联调 + 部署（一天）

- 测试：`cd backend && python -m unittest discover -s tests -q`
- CORS：前端在 5173，后端在 8000，**跨域必须配 `CORSMiddleware`**，否则浏览器直接拦
- 部署：`backend/Dockerfile` 的 `CMD ["uvicorn", "app.main:app", ...]`，nginx 把 `/api` 反代到 `backend:8000`

---

## 2. 接线总图：谁连谁

**这是本文最重要的一张图。** 看懂它，你就懂了整个项目。

```
                    ┌──────────────────────────────────────────┐
  浏览器 / Vue3 ───▶ │  FastAPI 外壳        app/main.py          │
  (frontend/)       │  路由 + CORS + 中间件 + 异常处理 + /docs  │
                    └────────────────┬─────────────────────────┘
                                     │ 调用（唯一的连接方式）
                    ┌────────────────▼─────────────────────────┐
                    │  防腐层 / 框架无关 handler   app/api.py   │
                    │  每个函数: (payload) -> (status, envelope)│
                    │  只有一个全局入口: services()             │
                    └────────────────┬─────────────────────────┘
                                     │
                    ┌────────────────▼─────────────────────────┐
                    │  ★ 组装点（接线的核心）                   │
                    │  services/chat_service.py :: AppServices  │
                    │  在这里把下面所有东西 new 出来并连起来     │
                    └──┬───────┬────────┬────────┬─────────────┘
                       │       │        │        │
        ┌──────────────▼─┐ ┌───▼────┐ ┌─▼──────┐ ┌▼──────────────┐
        │ retrieval/     │ │models/ │ │storage/│ │context/       │
        │ get_retriever()│ │get_    │ │ChatStore│ │ContextEngine  │
        │ BM25 / 向量    │ │model_  │ │KbRepo  │ │+ Reranker     │
        │ + 缓存         │ │backend()│ │FbRepo  │ │+ Summarizer   │
        └────────────────┘ └────────┘ └────────┘ └───────────────┘
                       │       │        │        │
                       └───────┴────┬───┴────────┘
                                    │ 全部塞进构造函数
                    ┌───────────────▼──────────────────────────┐
                    │  AgentOrchestrator   agents/orchestrator  │
                    │  持有 retriever / model / history / engine│
                    │  Router → Retrieve/Tool → ContextEngine   │
                    │  → Model.generate / stream → Trace        │
                    └──────────────────────────────────────────┘
```

### 用一句话说清每一条连接

| 从 | 到 | 靠什么连 | 代码位置 |
|---|---|---|---|
| FastAPI 路由 | 业务 handler | 直接函数调用 | `main.py` → `api.handle_*` |
| handler | 整个服务栈 | **全局单例入口 `services()`** | `api.py::services()` |
| 服务栈 | 各组件 | **构造函数传入（依赖注入）** | `AppServices.__init__` |
| 检索器 | 缓存 | 在 `search()` 里查缓存，`add_chunks()` 后清空 | `retrieval/retriever.py` |
| 模型 | 三种实现 | **工厂函数按配置选** | `models/__init__.py::get_model_backend` |
| 存储 | SQLite/MySQL | **同一个抽象类（`ChatStore`），配置切方言** | `storage/db.py` |
| 上下文引擎 | 模型 | **摘要器要用模型**：`HistorySummarizer(self.model)` | `chat_service.py` |
| 全局 | 配置 | 环境变量 → `config.py` → `effective_*()` | `config.py` |
| 后端 | 前端 | **契约**：`{code,msg,data}` + SSE 事件名 | `frontend/src/api/index.ts` |

### 三个"为什么"（新手最该问的）

**Q1：为什么要有个 `AppServices` 组装点？直接在路由里 new 不行吗？**
不行。因为一个 `AgentOrchestrator` 需要 retriever + model + history + engine 四样，
其中 retriever 和 model 是**重量级、要复用**的（加载索引、持有连接），
而 history 是**每个会话一份**的。如果每个路由各自 new，会出现：
索引被加载 N 次、数据库连接爆炸、配置散落各处。
`AppServices` 把"造一次的东西"和"每请求造的东西"分开管理——**这就是设计**。

**Q2：为什么 `retriever` 是单例，`orchestrator` 是每请求新建？**
看 `AppServices._orchestrator()`：它每次调用都 `return AgentOrchestrator(...)`。
因为每个请求的 `session_id` 不同 → history 不同 → orchestrator 必须重造。
而 retriever 无状态（只查索引），所以 `__init__` 里造一次就够。
**判断标准：这个对象是否持有"本次请求特有"的状态。**

**Q3：为什么 handler 返回 `(status, envelope)` 而不是直接返回 dict？**
因为要**解耦**。HTTP 状态码是网络层的概念（给网关、监控看），
业务 `code` 是业务层的概念（给前端分支用）。
`api.py` 只关心业务，不关心"我上面盖的是 FastAPI 还是 stdlib 服务器"——
所以它把状态码当普通数据返回，让外壳去决定怎么放进 HTTP 响应。
**好处**：同一份 `api.py`，`main.py` 和 `server.py` 都能用。

---

## 3. 一个请求的完整旅程（`POST /api/chat`）

新手理解项目最快的方法：**找一个接口，从头跟到尾**。下面是真实的 14 步。

| 步 | 在哪 | 发生什么 |
|---|---|---|
| 1 | 浏览器 | `frontend/src/api/index.ts` 发 `POST /api/chat`，body 带 `session_id`、`message` |
| 2 | `main.py::chat` | FastAPI 按 `payload: ChatRequest` **自动做参数校验**（pydantic）。字段不对 → 自动 400 |
| 3 | `main.py::chat` | `run_in_threadpool(...)` 把阻塞业务丢进线程池，**不卡住事件循环** |
| 4 | `api.py::handle_chat` | 又 `ChatRequest(**payload)` 校一次（**重复校验，本仓库真实的冗余**） |
| 5 | `api.py::services()` | 第一次调用时 `AppServices(seed_kb=True)`，之后复用同一个实例 |
| 6 | `chat_service.py::chat` | `_history(session_id)` 造历史管理器；`AgentOrchestrator(...)` 造编排器 |
| 7 | `orchestrator.py::prepare` | `_route_steps()`：先 `retriever.search(user_input, k=1)` 看知识库有没有相关内容 |
| 8 | `agents/router.py::route` | 判定意图 → 输出计划，比如 `["retrieve", "writer"]` 或 `["tool:calculator", ...]` |
| 9 | `orchestrator.py` | 按计划执行：`retrieve` → `retriever.search(k=None)` 取知识；`tool:` → `extract_args()` 抽参数 + `tool.run()` |
| 10 | `retriever.search()` | 先查**缓存**（key = `backend+k+query`），没命中才真检索（BM25 或向量） |
| 11 | `context/engine.py::build` | 把「系统指令 + 检索结果 + 对话历史」装配成带优先级的槽位，按 **token 预算裁剪** |
| 12 | `engine.render_messages` | 拼成模型能吃的 `messages` 格式 |
| 13 | `models/*.generate` | 调真实模型（qwen_api / local_ft）或离线 `fake` |
| 14 | 往回走 | `RunResult` → `ChatReply` → `ok()` 包成 `{code,msg,data}` → 回到 `main.py` → JSON 响应 |

**回程还要多做两件事**（别漏）：
- `chat_service.py` 里把这一轮对话**存进数据库**（`history.store.save(...)`）
- `metrics.record(...)` 记录 token 数、耗时、用了哪些工具 → 喂给 `/api/stats` 看板

**跟着走一遍的收益**：你会立刻明白，FastAPI 那 197 行只是**最外面薄薄一层**，
真正的内容全在 `services/` `agents/` `context/` `retrieval/` 里。
**这就是"接入"和"业务"的边界。**

---

## 4. 五种"连接方式"的写法（照抄模板）

新手不用发明设计模式，项目里就这五种，认全就够了。

### 方式一：工厂函数（"造什么由配置决定"）

```python
# models/__init__.py
def get_model_backend(backend: str | None = None) -> ModelBackend:
    backend = backend or config.effective_chat_backend()   # ← 配置决定
    if backend == "qwen_api":
        return _safe(lambda: ...QwenApiModel())
    if backend == "local_ft":
        return _safe(lambda: ...LocalFTModel())
    from .fake import FakeModel
    return FakeModel()                                     # ← 兜底，永远能跑
```

**学到什么**：`_safe()` 包一层 try/except，真实后端挂了就降级到 fake。
**这是"离线也能跑"的实现方式**，新手做项目时非常值得抄。

### 方式二：抽象基类（"换实现不改调用方"）

```python
# models/base.py
class ModelBackend(ABC):
    name: str = "base"
    is_llm: bool = True
    @abstractmethod
    def generate(self, messages: list[dict]) -> str: ...
    @abstractmethod
    def stream(self, messages: list[dict]) -> Iterable[str]: ...
```

三个实现共用同一组方法签名 → **orchestrator 完全不知道背后是哪个模型**。
存储层同理：`ChatStore` 一个抽象，底下 SQLite 或 MySQL。

**学到什么**：连接的双方约定"接口"而不是"实现"，这就是解耦。

### 方式三：组装点（"在这里把线插上"）

```python
# services/chat_service.py
class AppServices:
    def __init__(self, seed_kb: bool = True):
        self.retriever = get_retriever()                    # 单例：重
        self.model = get_model_backend()                    # 单例：重
        self.store = ChatStore(config.DATA_DIR / "chat_history")
        self.kb_repo = KbRepository()
        self.feedback_repo = FeedbackRepository()
        self.metrics = get_metrics()
        self.engine = ContextEngine(
            config.CONTEXT_TOKEN_BUDGET,
            reranker=Reranker(),
            summarizer=HistorySummarizer(self.model),       # ← 注意：引擎要用模型
        )
```

**学到什么**：**整个项目的接线集中在这 10 行。** 想知道"谁连谁"，看这个构造函数就够了。
`HistorySummarizer(self.model)` 这行尤其重要——它说明"上下文引擎"依赖"模型"，
这条依赖就是在组装点被插上的。

### 方式四：全局单例 + 懒加载（"用得着再造，造一次就够"）

```python
# api.py
_services: AppServices | None = None

def services() -> AppServices:
    global _services
    if _services is None:
        _services = AppServices(seed_kb=True)
    return _services

def reset_services() -> None:        # ← 给测试用：清掉重造
    global _services
    _services = None
```

**学到什么**：为什么懒加载？因为"服务启动"和"第一次请求"可能环境不同，
而且这样**没装 fastapi 也能 import 成功**（第 5 节会讲）。
`reset_services()` 说明单例的代价是"测试之间会互相污染"，必须留个重置口子。

### 方式五：契约（"前后端唯一的连接"）

后端和前端之间**没有代码连接**，只有契约：
- 响应体固定 `{code, msg, data}`，`code=0` 成功，非 0 看 `errors.py` 的错误码表
- SSE 事件名固定 `agent` / `retrieved` / `token` / `done`
- 前端 `frontend/src/api/index.ts` 把非 0 的 code 抛成带 code 的 `ApiError`

**学到什么**：**改事件名或删字段 = 改契约 = 前端会静默崩。** 加字段是安全的。

---

## 5. 新手最容易卡住的 8 个点

1. **`ModuleNotFoundError: No module named 'app'`**
   → 必须在 `backend/` 目录下启动：`cd backend && uvicorn app.main:app`。
   `app.main` 这个写法要求"当前目录是 `backend/`"。

2. **相对导入报错 `attempted relative import with no known parent package`**
   → `from . import api` 的 `.` 指"当前包"。直接 `python app/main.py` 会失败，
   必须用 `uvicorn app.main:app` 或 `python -m app.main` 这种**模块方式**启动。

3. **循环导入（Circular import）**
   → A import B，B 又 import A。解法：把 import 挪到函数内部（本仓库
   `models/__init__.py` 里 `__import__("app.models.qwen_api", ...)` 就是这个原因——
   **按需导入**，避免启动时就加载重依赖）。

4. **`async def` 里写了阻塞代码**
   → 检索、SQL、模型调用都是阻塞的。写在 `async def` 里会**卡死整个服务**
   （不是变慢，是其他请求全部排队）。必须 `run_in_threadpool` 或写成 `def`。
   原理：IO 等待时让出事件循环；CPU 密集的活仍受 **GIL** 限制，所以线程池是对的方向。

5. **生成器不会立刻执行**
   → 见 Day 5 那段。`f()` 返回生成器 ≠ 执行了 `f` 的函数体。

6. **全局单例导致测试互相污染**
   → 单测里 A 用例往知识库塞了数据，B 用例就多出几条。
   本仓库的解法：`reset_services()` + 每个测试用独立临时目录。

7. **前端连不上后端**
   → 两个原因：① 端口不对（后端 8000 / 前端 5173）
   ② **CORS 没配**。浏览器控制台会明确报 CORS 错，别去后端日志里找。

8. **改了代码不生效**
   → `--reload` 只对 Python 文件生效；改了 `.env` 要重启；改了前端要重新 build。

---

## 6. 动手练习：从零接一条最小链路

照着做一遍，比看十遍文档有用。目标：**让一个路由成功调用"检索 → 上下文 → 模型"**。

```python
# backend/app/main_min.py   ← 新建一个练手文件，不影响原项目
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel

from . import api                      # ① 连到已有业务
from .schemas import ChatRequest

app = FastAPI(title="接线练习")

class AskIn(BaseModel):                # ② 定义契约
    message: str = "你好"
    session_id: str = "practice"

@app.get("/health")                    # ③ 最小验证：连上服务栈了吗
async def health() -> dict:
    status, body = await run_in_threadpool(api.handle_health)
    return body

@app.post("/ask")                      # ④ 完整链路：检索 -> 上下文 -> 模型
async def ask(payload: AskIn) -> dict:
    req = ChatRequest(message=payload.message, session_id=payload.session_id)
    status, body = await run_in_threadpool(api.handle_chat, req.model_dump())
    return body
```

跑起来：
```bash
cd backend
uvicorn app.main_min:app --reload
# 打开 http://localhost:8000/docs，试 POST /ask
```

**观察这三件事**：
1. `/ask` 的响应里 `data.context` 有 token 预算信息 → 说明**上下文引擎接上了**
2. `data.agent_trace` 有 router/retrieve 步骤 → 说明**多 Agent 接上了**
3. `data.backend` 是 `fake` → 说明**模型工厂降级生效**（没配 key 也能跑）

**然后故意改坏它**：把 `await` 去掉、把 `session_id` 删掉、把 `run_in_threadpool` 换成直接调用——
看分别报什么错。**踩过一遍的错，才是你的。**

---

## 7. 一句话总结开发流程

> **先让空壳能跑 → 再让一条路由连上业务 → 再把参数/错误/状态码补齐 →
> 再接流式 → 再补测试和部署。每一步都留下一个能跑的东西。**

而"FastAPI 怎么和项目其他部分连接"的答案是：

> **FastAPI 只做三件事**——收 HTTP、校验参数、把结果包成响应。
> **它到业务的连接只有一个入口**：`api.services()`。
> **业务内部的连接集中在一个地方**：`AppServices.__init__` 那十行。
> **业务和框架的边界是一条铁律**：`context/` `agents/` `retrieval/` 里不许出现 `fastapi`。
>
> 抓住这一个入口、一个组装点、一条铁律，整个项目就通了。

---

## 附：自己排查"连没连上"的三个问题

新接手一个 FastAPI 项目时，问这三个问题就能摸清接线：

1. **路由函数里第一行调用了什么？** → 那是它连到业务的方式（本仓库：`api.handle_*`）
2. **那个业务对象是从哪来的？** → 顺着找，一定会找到一个组装点（本仓库：`AppServices`）
3. **组装点里 new 的东西，分别是什么层的？** → 那就是这个项目的分层图（本仓库：检索/模型/存储/上下文引擎四层）
