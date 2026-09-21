# FastAPI 工作场景开发实录

> **这是什么**：把"给 `context-engine-agent` 接 FastAPI"当作一个**真实的工单**，
> 按工作日 + 提交重放整个过程。
>
> **和前面几份的区别**：这份里出现的**每一段代码都是这个项目里的真实代码**
> （出自 `backend/app/main.py`、`api.py`、`schemas.py`、`errors.py`、
> `logging_config.py`、`multipart.py`），不是教学示例。
> 每个工作日末尾还会附上真实的提交信息、评审意见、测试反馈。
>
> 目的是让你看到：**工作里的开发流程长什么样**——不是一路顺风写完，
> 而是有人催、有人挑刺、有人提 bug。

---

## 工单

```
标题：后端接口层引入 FastAPI，替换手写 HTTP 路由
优先级：P1（阻塞前端联调）
提出人：前端 / 测试
负责人：你（后端）
预计：2 周
验收：/docs 可用；12+ 接口全部迁移；旧入口仍可跑；测试全绿
```

**非目标（第一天就写清楚）**：不动 `finetune/` 微调管线、不改前端页面逻辑、
不换数据库、不引入鉴权。

## 相关人员

| 角色 | 会给你带来什么 |
|---|---|
| 前端同事 | 天天催文档；联调时会说"这个字段什么意思" |
| 测试同事 | 会拿着边界值来提 bug |
| 老同事（评审） | 会在 review 时问你"为什么不用 `Depends`" |
| 运维同事 | 上线时会问你"回滚怎么回" |

---

## 总览：10 个工作日

| 工作日 | 提交 | 交付物 | 对应真实代码位置 |
|---|---|---|---|
| 1 | `feat(api): 引入 FastAPI 骨架` | 应用实例 + `/` 路由 | `main.py` 的 `FastAPI(...)` 段 |
| 2 | `feat(api): /health 接入服务栈` | 第一次接线 | `main.py::health` + `api.handle_health` |
| 3 | `feat(api): POST /api/chat` | 请求模型 + 校验 | `schemas.ChatRequest` + `main.py::chat` |
| 4 | `fix(api): 统一错误响应格式` | 三个异常处理器 | `main.py` 三个 `exception_handler` |
| 5 | `feat(api): request_id 中间件 + CORS` | 可观测 + 跨域 | `main.py::request_context` + `CORSMiddleware` |
| 6 | `feat(api): 知识库接口迁移` | 查询/路径参数 | `main.py` 的 kb 四条路由 |
| 7 | `feat(api): 文件上传` | multipart 取舍 | `main.py::upload` + `multipart.py` |
| 8 | `feat(api): SSE 流式` | 流式 + 踩坑 | `main.py::chat_stream` |
| 9 | `feat(api): 补齐剩余接口` | 收尾 | `main.py` 其余路由 |
| 10 | `chore(deploy): 镜像 + 灰度` | 上线 | `Dockerfile` + `nginx.conf` |

---

## 工作日 1 · 立项 + 骨架

### 场景

周一早会。前端同事当着大家说："你们的接口没文档，我联调全靠猜字段名。"

你把这句话翻译成一句需求，写进工单：
> "提供可交互的接口文档 + 统一参数校验 + 统一错误格式。"

**下午两小时**，只做一件事：让空壳跑起来。

### 你写的代码（真实代码）

出处：`backend/app/main.py`

```python
app = FastAPI(
    title=config.APP_TITLE,
    version="1.1.0",
    description=(
        "上下文引擎 + 多 Agent 协作 + RAG 问答的接口文档。\n\n"
        "**统一响应结构**：`{code, msg, data}`；`code=0` 表示业务成功，"
        "非 0 见 `app/errors.py` 的错误码表（40xxx 调用方 / 50xxx 服务端 / 502xx 上游）。"
    ),
    openapi_tags=[
        {"name": "ops", "description": "健康检查与看板统计"},
        {"name": "chat", "description": "对话（含 SSE 流式）与 Agent 规划"},
        {"name": "kb", "description": "知识库：文本入库、文件上传、列表分页、删除"},
        {"name": "feedback", "description": "badcase 反馈的收集与查询"},
    ],
)


@app.get("/", tags=["ops"], summary="服务信息")
async def root() -> dict:
    return api.ok({"name": config.APP_TITLE, "docs": "/docs", "health": "/health"})
```

### 关键决策（这一步就定了后面所有事）

`openapi_tags` 里那四组，**不是随手写的**——它是把 `server.py` 里
`do_GET` / `do_POST` / `do_DELETE` 那堆 `if` 全部列出来后归的类。
这一步叫"摸底"，看着不起眼，但决定后面 9 天有没有返工。

### 自测

```bash
cd backend && uvicorn app.main:app --reload
```

打开 `http://localhost:8000/docs` —— 四组标签、一个 `/` 接口。
点 `Try it out` 能返回 `{"code":0,...}`。

### 提交

```
feat(api): 引入 FastAPI 骨架，声明应用信息与接口分组

- app = FastAPI(...) + openapi_tags 四组分类
- GET / 返回服务信息，用于自检
- 业务逻辑暂未接入，仅验证 /docs 可用
```

### 收工标准

空壳能跑、`/docs` 能开、`X-Request-ID` 还没做。（**不追求一步到位**）

---

## 工作日 2 · 第一次"接线"

### 场景

前端同事上午又来问："文档里怎么只有 `/` ？"

你说"今天给你接第一个真接口"。**选的是 `/health`，不是 `/api/chat`**——
因为 `/health` 最简单，出错了一定是接线的问题，不会跟业务混在一起。

### 你写的代码（真实代码）

出处：`backend/app/main.py`

```python
@app.get("/health", tags=["ops"], summary="健康检查（含实际生效的后端）")
async def health() -> dict:
    status, body = api.handle_health()
    return body
```

出处：`backend/app/api.py`

```python
def handle_health() -> tuple[int, dict]:
    return 200, ok(services().health().model_dump())


def services() -> AppServices:
    global _services
    if _services is None:
        _services = AppServices(seed_kb=True)
    return _services
```

### 这一天你要想明白的三件事

**① `services()` 是什么？**
整个后端的唯一入口。第一次调用时才创建（懒加载），之后复用。
它内部在 `AppServices.__init__` 里把检索器、模型、数据库、上下文引擎全部接好。
**你今天只写了 3 行，但背后连上了 5 个模块。**

**② 返回的 `status` 去哪了？**
上面这段真实代码是 `return body` —— **把状态码丢了**。
今天不炸是因为 `handle_health` 恒返回 200。
**但这是隐患**，工作里欠的债迟早要还（第 10 天会被测试提出来）。

**③ 为什么这里没写 `run_in_threadpool`？**
因为 `handle_health` 几乎不耗时。等第 3 天接 `/api/chat` 就必须加了——
它会读数据库、查检索索引、调模型，**全是阻塞操作**。

### 自测

```bash
curl http://localhost:8000/health
```

返回：

```json
{"code": 0, "msg": "ok", "data": {
  "status": "ok", "chat_backend": "fake", "retrieval_backend": "bm25",
  "model": "fake", "db_backend": "sqlite", "cache_backend": "lru"}}
```

**看到 `db_backend` / `cache_backend` 就说明接线成功了。**

### 提交

```
feat(api): /health 接入服务栈，返回实际生效的后端

复用 app/api.py 的框架无关 handler，FastAPI 只做 HTTP 适配。
```

---

## 工作日 3 · 接 `POST /api/chat`（重头戏）

### 场景

前端同事发来消息："聊天接口给我，我这边页面等着联调。"

### 第一步：先定契约，不写路由

出处：`backend/app/schemas.py`

```python
class ChatRequest(BaseModel):
    message: str = Field(..., description="The user's question")
    session_id: str = Field(default="default", description="Conversation id")
    stream: bool = Field(default=True, description="Stream tokens when True")
```

出处：`backend/app/schemas.py`（响应模型）

```python
class ChatReply(BaseModel):
    """Structured reply returned to the frontend for the context panel."""

    answer: str
    session_id: str
    context: Context
    agent_trace: list[dict[str, Any]] = Field(default_factory=list)
    used_tools: list[str] = Field(default_factory=list)
    backend: str = "fake"
    tokens_requested: int = 0
    tokens_generated: int = 0
    elapsed_ms: int = 0
```

**工作习惯**：先把 `ChatRequest` 发给前端，说"就这三个字段"。
前端可以立刻照这个写代码，不用等你写完路由。**这就是契约先行。**

### 第二步：写路由

出处：`backend/app/main.py`

```python
@app.post("/api/chat", tags=["chat"], summary="一次性返回完整回答",
          responses={400: {"description": "参数校验失败(40001)"}})
async def chat(payload: ChatRequest) -> dict:
    status, body = await run_in_threadpool(api.handle_chat, payload.model_dump())
    return body
```

出处：`backend/app/api.py`（被调用的 handler）

```python
def handle_chat(payload: dict) -> tuple[int, dict]:
    req = ChatRequest(**payload)
    return 200, ok(services().chat(req).model_dump())
```

### 三个必须看懂的点

| 点 | 说明 |
|---|---|
| `payload.model_dump()` | pydantic 对象转成普通 dict。因为 `api.handle_chat` 是框架无关函数，不认识 pydantic |
| `run_in_threadpool` | 里面是阻塞操作（读库、检索、调模型），不能直接写在 `async def` 里 |
| `return body` | **又是丢 status**。这里更危险，因为 `handle_chat` 将来可能返回非 200 |

### 评审时被问到的问题

> **老同事**："`ChatRequest` 在 `main.py` 校验了一次，`api.py` 里 `ChatRequest(**payload)` 又校验一次，是不是重复了？"

**你怎么答**（真实的回答）：
"是的，重复了。这是'防腐层'的税——`api.py` 要保持框架无关，
不能假设调用方已经校验过。**当前选择是忍受一次重复校验，换取业务层零框架依赖。**
如果要优化，可以给 `api.py` 加一组信任 typed 对象的变体。"

> 工作里被问到这种问题，**不要急着改**。说清楚取舍就行。

### 提交

```
feat(api): POST /api/chat 接入业务链路

- 新增 ChatRequest / ChatReply 契约模型
- 路由仅做 HTTP 适配，业务复用 api.handle_chat
- 阻塞调用走 run_in_threadpool，避免卡事件循环
```

---

## 工作日 4 · 统一错误格式

### 场景

**这是被前端逼出来的。** 前端同事说：

> "我传错参数的时候，你返回的是 `{"detail":[{"loc":["body","message"],...}]}`，
> 但正常返回是 `{code,msg,data}`。**我要写两套解析。**"

这就是第 3 天留下的坑。今天补上。

### 你写的代码（真实代码）

出处：`backend/app/errors.py`（先有错误码体系）

```python
class ErrorCode(IntEnum):
    OK = 0
    # 40xxx：调用方的问题
    BAD_REQUEST = 40000
    VALIDATION_ERROR = 40001
    NOT_FOUND = 40400
    PAYLOAD_TOO_LARGE = 41300
    UNSUPPORTED_MEDIA = 41500
    RATE_LIMITED = 42900
    # 50xxx：服务端的问题
    INTERNAL_ERROR = 50000
    DB_ERROR = 50001
    STORAGE_ERROR = 50002
    # 502xx：依赖的上游（大模型 / 向量检索 / 外部工具）
    UPSTREAM_ERROR = 50200
    MODEL_ERROR = 50201
```

出处：`backend/app/main.py`（三个异常处理器）

```python
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.http_status, content=fail(exc.code, exc.msg, exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    detail = [{"field": ".".join(str(p) for p in e.get("loc", ())), "msg": e.get("msg", "")}
              for e in exc.errors()]
    return JSONResponse(
        status_code=400,
        content=fail(ErrorCode.VALIDATION_ERROR, "参数校验失败", detail),
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    log(logger, 40, "http.error", path=request.url.path, error=exc.__class__.__name__)
    return JSONResponse(status_code=500, content=fail(ErrorCode.INTERNAL_ERROR, "服务器内部错误"))
```

出处：`backend/app/errors.py`（统一响应体）

```python
def ok(data: Any = None, msg: str = "ok") -> dict:
    return {"code": int(ErrorCode.OK), "msg": msg, "data": data}


def fail(code: "ErrorCode | int", msg: str, detail: Any = None) -> dict:
    c = _coerce(code)
    body: dict = {"code": int(c), "msg": msg, "data": None}
    if detail is not None:
        body["detail"] = detail
    return body
```

### 为什么要三个处理器

| 处理器 | 接住谁 | 映射 |
|---|---|---|
| `AppError` | 你自己 `raise AppError(...)` | 它自带的错误码 |
| `RequestValidationError` | pydantic 自动抛 | 400 / 40001 |
| `Exception` | 任何漏网的 bug | 500 / 50000，**不泄露堆栈** |

### 自测

在 `/docs` 里故意删掉 `message` 字段发请求，现在返回：

```json
{"code": 40001, "msg": "参数校验失败", "data": null,
 "detail": [{"field": "body.message", "msg": "Field required"}]}
```

**格式统一了。** 给前端回消息："错误格式统一了，你只用写一套。"

### 提交

```
fix(api): 统一错误响应格式为 {code,msg,data}

- AppError / RequestValidationError / 未知异常 三路收敛
- 未知异常只写日志，不向调用方暴露堆栈
```

---

## 工作日 5 · request_id 中间件 + CORS

### 场景 1：排查之痛

测试同事报了一个 bug，你问："什么时间、哪个请求？" 他说"就刚才，大概三点多"。
**你翻日志翻了 20 分钟。** 今天必须解决。

出处：`backend/app/main.py`

```python
@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = set_request_id(request.headers.get("X-Request-ID"))
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001 - 兜底成统一响应
        status, body = error_from_exception(exc)
        log(logger, 40, "http.unhandled", path=request.url.path, error=exc.__class__.__name__)
        response = JSONResponse(status_code=status, content=body)
    response.headers["X-Request-ID"] = rid
    log(
        logger,
        20,
        "http",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return response
```

出处：`backend/app/logging_config.py`（id 靠 contextvars 传递）

```python
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def set_request_id(rid: Optional[str] = None) -> str:
    rid = rid or new_request_id()
    request_id_var.set(rid)
    return rid
```

**为什么要用 `contextvars` 而不是普通全局变量？**
因为要跨线程。`run_in_threadpool` 会把活丢到别的线程，
普通全局变量在多请求并发时会串号，`contextvars` 不会。

**从此的排查流程**：用户报错 → 看响应头 `X-Request-ID` → 日志里搜这个编号 → 整条链路。

### 场景 2：前端说"我一个请求都发不出去"

前端跑在 `5173`，后端在 `8000`，**端口不同 = 跨域**，浏览器直接拦。

出处：`backend/app/main.py`

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
```

**排查经验**：这种情况下**后端日志里什么都没有**（请求根本没发出去），
错误在浏览器控制台。新手常犯的错是去后端日志里找。

**`expose_headers` 为什么必须有？** 浏览器默认只让 JS 读少数标准响应头，
自定义的 `X-Request-ID` 必须显式暴露，否则前端拿不到。

### 提交

```
feat(api): 增加 request_id 中间件与 CORS

- 每请求分配 X-Request-ID，写入响应头并贯穿日志
- 开放 5173 跨域，暴露 X-Request-ID 供前端读取
```

---

## 工作日 6 · 知识库接口迁移

### 场景

测试同事说"知识库页面还连不上"。今天是搬运日，**一次搬一条，搬完即测**。

出处：`backend/app/main.py`

```python
@app.post("/api/kb/ingest", tags=["kb"], summary="文本入库（JSON）")
async def ingest(payload: dict) -> dict:
    status, body = await run_in_threadpool(api.handle_ingest, payload)
    return JSONResponse(status_code=status, content=body)


@app.get("/api/kb/list", tags=["kb"], summary="知识库文档列表（分页 + 搜索）")
async def kb_list(page: int = 1, size: int = 10, q: str = "") -> dict:
    status, body = await run_in_threadpool(api.handle_kb_list, {"page": page, "size": size, "q": q})
    return JSONResponse(status_code=status, content=body)


@app.delete("/api/kb/{source}", tags=["kb"], summary="按来源删除文档（同时清理检索索引）",
            responses={404: {"description": "来源不存在(40400)"}})
async def kb_delete(source: str) -> dict:
    status, body = await run_in_threadpool(api.handle_kb_delete, source)
    return JSONResponse(status_code=status, content=body)
```

### 注意：这三条写了 `JSONResponse(status_code=status, ...)`

**和第 2、3 天的 `/health`、`/api/chat` 不一致！** 那两条是 `return body`。

这就是工作里的真实情况：**同一个人、同一个文件，前后不一致。**
因为这几天你更熟练了，知道状态码必须传。
**正确做法是回头把那两条也改掉**（这就是技术债，第 10 天会被翻出来）。

### 参数类型的三种写法

| 写法 | 类型 | 例子 |
|---|---|---|
| `payload: dict` | 请求体（这里是裸 dict，因为要兼容旧接口） | `POST /api/kb/ingest` |
| `page: int = 1` | 查询参数 | `/api/kb/list?page=2` |
| `source: str` + 路由里 `{source}` | 路径参数 | `DELETE /api/kb/尺码推荐.txt` |

**关键**：`page: int = 1` 里的 `int` **不是装饰**。
前端传 `?page=abc`，FastAPI 自动返回 400，**你的函数根本不会被调用**。

### 提交

```
feat(api): 知识库接口迁移（入库 / 列表 / 删除）

- 列表支持分页与搜索，参数由 FastAPI 自动校验
- 删除按 source 路径参数定位，404 走统一错误码
```

---

## 工作日 7 · 文件上传（这一天有个设计取舍）

### 场景

前端加了拖拽上传，问你"后端用 `UploadFile` 还是怎么着"。

**标准答案**是用 FastAPI 的 `UploadFile`：

```python
# FastAPI 的写法 —— 这个项目故意没用
from fastapi import UploadFile, File

@app.post("/api/kb/upload")
async def upload(file: UploadFile = File(...)):
    ...
```

**但这条路需要额外安装 `python-multipart`。** 而项目的硬约束是
**"零依赖也能跑"**（`python run.py` 起来的是 stdlib 服务器）。

### 所以真实代码是这样

出处：`backend/app/main.py`

```python
@app.post("/api/kb/upload", tags=["kb"], summary="文件上传入库（multipart/form-data）",
          responses={415: {"description": "不支持的文件类型(41500)"},
                     413: {"description": "文件过大(41300)"}})
async def upload(request: Request):
    body_bytes = await request.body()
    status, envelope = await run_in_threadpool(
        api.handle_upload, request.headers.get("content-type", ""), body_bytes
    )
    return JSONResponse(status_code=status, content=envelope)
```

出处：`backend/app/multipart.py`（自己写的解析器）

```python
"""极简 multipart/form-data 解析（stdlib，不依赖 python-multipart）。

为什么自己写：FastAPI 的 ``UploadFile`` 需要 ``python-multipart``；stdlib 版
``server.py`` 更是没有任何表单解析。项目要求"零依赖也能跑"，所以这里实现一个
够用的解析器（浏览器 ``<input type=file>`` / ``FormData`` 的常规格式），
两个 HTTP 入口（``server.py`` 与 ``app/main.py``）共用同一份代码。

支持：普通字段 + 单文件/多文件；超过 ``max_bytes`` 抛 ``AppError(41300)``。
不支持（用不到）：嵌套 multipart、``Content-Transfer-Encoding``。
"""
```

### 这是全文最该学的一课

> **框架给你的东西，不一定都要用。**
> "用框架现成的最省事"和"少一个依赖"之间，是**取舍**，不是对错。

注释里把"为什么自己写"、"支持什么"、"不支持什么"写得清清楚楚——
**这才是能在评审会上站得住的设计文档。**

评审时如果被问"为什么不用官方的"，你照着注释念就行。

### 提交

```
feat(api): 文件上传接口（multipart，零依赖）

- 不用 FastAPI UploadFile（需 python-multipart），自实现 app/multipart.py
- 两个 HTTP 入口共用同一份解析器，保证行为一致
- 超限 413、类型不支持 415，均返回结构化 envelope
```

---

## 工作日 8 · SSE 流式（最坑的一天）

### 场景

产品说"聊天要打字机效果"。前端说"我要 SSE"。

出处：`backend/app/main.py`

```python
@app.post("/api/chat/stream", tags=["chat"], summary="SSE 流式回答（agent/token/retrieved/done）")
async def chat_stream(payload: ChatRequest):
    status, events = await run_in_threadpool(api.handle_chat_stream, payload.model_dump())

    async def gen():
        for evt in events:
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

出处：`backend/app/services/chat_service.py`（被调用的生成器）

```python
def chat_stream(self, req: ChatRequest) -> Iterator[dict]:
    """SSE 事件流（生成器）。在 done 事件处补一次指标采集。"""
    started = time.perf_counter()
    orch = self._orchestrator(req.session_id)
    for evt in orch.stream_events(req.message, req.session_id):
        if evt.get("type") == "done":
            ...
        yield evt
```

### ❗ 这里有个真实的坑，当天没发现

`events` 是**生成器**。所以：

```python
status, events = await run_in_threadpool(api.handle_chat_stream, ...)
```

**这行只是"拿到生成器就返回了"**，`chat_stream` 的函数体一行都没执行。
真正的模型调用发生在 `for evt in events` 迭代的时候——
那时已经在**事件循环线程**里了。**线程池那一层等于没生效。**

**根源**：Python 生成器函数被调用时**不执行函数体**，只返回一个生成器对象。
这是新手理解生成器最常见的误区。

**正确做法**（以后要改）：
```python
from starlette.concurrency import iterate_in_threadpool
async def gen():
    async for evt in iterate_in_threadpool(events):
        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
```

### 这一天另一个坑：nginx 缓冲

`headers={"X-Accel-Buffering": "no"}` 是给 nginx 看的。
同时 `frontend/nginx.conf` 里还要配 `proxy_buffering off`。
**不配的话，流式 token 会被 nginx 攒起来一起发，前端看到的还是"一次全出来"。**

**本地直接跑 uvicorn 是看不出来的——上线才暴露。**

### 事件协议（这就是契约）

| 事件名 | 什么时候发 | 前端拿来干嘛 |
|---|---|---|
| `agent` | 每个 Agent 步骤 | 渲染"协作链"面板 |
| `retrieved` | 检索完成 | 显示命中的知识 |
| `token` | 每生成一段 | 打字机效果 |
| `done` | 结束 | 收尾 + 拿 trace/context |

**改事件名或删字段 = 撕毁契约。** 加字段是安全的。

### 提交

```
feat(api): SSE 流式回答

- StreamingResponse + text/event-stream
- 事件协议：agent / retrieved / token / done
- 响应头 X-Accel-Buffering:no，配合 nginx proxy_buffering off
```

### 自测

```bash
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"加绒牛仔怎么洗\",\"session_id\":\"t1\"}"
```

`-N` 关掉 curl 自己的缓冲，能看到逐条 `data: {...}` 出来。

---

## 工作日 9 · 补齐剩余接口 + 还技术债

### 补齐（真实代码）

出处：`backend/app/main.py`

```python
@app.get("/api/stats", tags=["ops"], summary="看板统计：知识库规模 / badcase 分布 / 最近请求指标")
async def stats() -> dict:
    status, body = api.handle_stats()
    return body


@app.post("/api/chat/plan", tags=["chat"], summary="只看路由/工具计划（不调用模型）")
async def chat_plan(payload: ChatRequest) -> dict:
    status, body = await run_in_threadpool(api.handle_chat_plan, payload.model_dump())
    return body


@app.post("/api/feedback", tags=["feedback"], summary="提交 badcase 反馈")
async def feedback(payload: FeedbackRequest) -> dict:
    status, body = await run_in_threadpool(api.handle_feedback, payload.model_dump())
    return JSONResponse(status_code=status, content=body)


@app.get("/api/feedback", tags=["feedback"], summary="badcase 列表（分页）")
async def feedback_list(page: int = 1, size: int = 10) -> dict:
    status, body = await run_in_threadpool(api.handle_feedback_list, {"page": page, "size": size})
    return JSONResponse(status_code=status, content=body)


@app.get("/api/context/{session_id}", tags=["chat"], summary="会话历史（上下文面板用）")
async def context(session_id: str) -> dict:
    status, body = await run_in_threadpool(api.handle_context, session_id)
    return body
```

### 技术债清单（今天要认领）

搬完 13 条路由，回头一看：

| 欠的债 | 位置 | 什么时候还 |
|---|---|---|
| `return body` 丢了 status | `/`、`/health`、`/api/stats`、`/api/chat`、`/api/chat/plan`、`/api/context/{id}` | 本周内 |
| 参数校验跑了两遍 | `main.py` + `api.py` | 下个迭代 |
| SSE 线程池没生效 | `/api/chat/stream` | 下个迭代（要配 `iterate_in_threadpool`） |
| OpenAPI 可能漂移 | 全局 | 加契约测试 |

**工作里没有"一次做完美"这回事。** 正确做法是**认领 + 排期**，
而不是假装没有。评审时主动说出来，比被人翻出来强得多。

### 提交

```
feat(api): 补齐看板 / 反馈 / 上下文接口

已知技术债（已登记）：
- 部分路由未透传 status
- SSE 路由的 threadpool 未生效
```

---

## 工作日 10 · 联调、测试、上线

### 上午：联调

前端同事过一遍 `/docs`，确认字段和错误码。**发现一个 bug**：

> "我点知识库列表，`page` 传了个字符串，你返回 400 但我拿到的 `code` 是 40001，
> 前端之前的代码是按 `code==400` 判断的。"

**这是契约没对齐，不是代码 bug。** 改前端判断逻辑（认 `40001` 或"非 0"），
不需要改后端。**这就是"契约先行"省下的成本。**

### 中午：测试

```bash
cd backend
python -m unittest discover -s tests -q
ruff check backend
```

### 下午：部署

出处：`backend/Dockerfile`

```dockerfile
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**注意 `PYTHONUNBUFFERED=1`** —— 不设的话日志会被缓冲，
SSE 场景下你会以为"服务卡住了"。

出处：`frontend/nginx.conf` 的关键点

```nginx
location /api/ {
    proxy_pass http://backend:8000;
    proxy_buffering off;          # ← SSE 必须关，否则前端收不到逐段输出
}
```

### 上线检查单

- [ ] `/health` 返回的 `db_backend` / `cache_backend` 符合预期
- [ ] `/docs` 可访问
- [ ] **SSE 实测是逐段输出**，不是一次性
- [ ] 响应头有 `X-Request-ID`
- [ ] 用 `X-Request-ID` 能在日志里定位到那一条

### 回滚演练

**运维同事问："出问题怎么回？"**

答：`server.py` 那条零依赖入口全程没动过，还在。
环境变量切回 stdlib 入口 / 回滚到上一个镜像 tag，一步到位。
**（这就是第 2 天"旧入口必须还能跑"这条纪律的价值——迁移期全程保留退路。）**

### 晚上的复盘

| 问题 | 结论 |
|---|---|
| 哪个决策最值钱？ | 第 2 天定的"旧入口全程可用"——给了整个迁移期一条退路 |
| 哪里返工了？ | 第 4 天的错误统一。如果第 3 天先想清楚错误格式，能省半天 |
| 有什么没做完？ | 三条技术债，已登记 |
| 流程哪里可以更好？ | 应该在第 1 天就写契约测试，防止 `/docs` 和代码漂移 |

---

## 全文复盘：工作开发流程 vs 学习式开发

| | 学习式开发 | 工作式开发 |
|---|---|---|
| 需求 | 自己想做什么 | 别人被某件事烦到了 |
| 顺序 | 从 hello world 往上堆 | 从已有代码往回接（**摸底优先**） |
| 完成标准 | 能跑就行 | 文档、错误码、测试、回滚，缺一不可 |
| 遇到问题 | 卡住就查文档 | **先认领 + 排期**，别假装没有 |
| 代码质量 | 一次写完美 | **留技术债，但登记在册** |
| 交付 | 自己看到结果 | 前端能联调、测试能断言、运维能回滚 |

### 三条最该带走的工作习惯

**① 每一步都要能跑。**
不是"写三天一起跑"。第 1 天就有能跑的 `/docs`，第 2 天就有能用的 `/health`。

**② 迁移期永远保留退路。**
旧的 `server.py` 全程没动。出了问题一秒切回去。
**这是新手最容易忽略、但老手最在意的事。**

**③ 债要认领，不要藏。**
重复校验、丢状态码、SSE 线程池没生效——
**主动写进提交信息里，比被人翻出来强一百倍。**

---

## 最终交付物清单

| 交付物 | 位置 |
|---|---|
| FastAPI 外壳（13 条路由） | `backend/app/main.py` |
| 框架无关 handler | `backend/app/api.py` |
| 契约模型 | `backend/app/schemas.py` |
| 错误码与统一响应 | `backend/app/errors.py` |
| 零依赖 multipart 解析 | `backend/app/multipart.py` |
| 日志与 request_id | `backend/app/logging_config.py` |
| 零依赖入口（退路） | `backend/server.py` |
| 镜像 | `backend/Dockerfile` |
| 反代（含 SSE 配置） | `frontend/nginx.conf` |
| CI 四道门 | `.github/workflows/ci.yml` |
