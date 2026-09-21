# 用项目真实代码 · 从 0 到 1 带练

> **不新建任何文件。** 全程用的就是项目里真实存在的 `backend/app/main.py`（197 行）。
>
> 这份是"带练"：**每一步都告诉你「这一步为什么现在做 → 真实代码在哪几行 → 你现在敲什么命令 → 真实输出是什么」。**
> 你只要跟着敲、跟着看，就能理解这 197 行是怎么从 0 长到 1 的。
>
> 服务已经在跑：`cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8090`
> 浏览器：`http://127.0.0.1:8090/docs`

---

## 先建立一个概念：这 197 行不是一次写完的

`main.py` 已经是"完成态"（1），但它内部有清晰的**施工顺序**（0→1）：

```
1. 建 app           →  /docs 能开
2. 加一条最简路由    →  证明框架工作
3. 接上真业务        →  第一次"接线"
4. 定契约 + 加业务路由
5. 补错误统一        →  第 4 步暴露了问题
6. 补中间件 + CORS   →  请求多了才需要
7. 处理阻塞          →  一有慢操作就必须加
8. 加流式            →  特殊需求，最后做
```

**为什么是这个顺序？** 因为每一步都是被前一步"逼"出来的——
第 5 步是因为第 4 步暴露了错误格式不统一；第 6 步是因为请求多了要排查；
第 7 步是因为第 3 步接上真业务后出现了阻塞。**顺序错了就要返工。**

下面逐步走。每一步都能在**真实服务**上验证。

---

# 第 1 步 · 建 app：让 `/docs` 能开

## 为什么现在做

没有 `app` 这个对象，FastAPI 什么都不是。这一步只解决一件事：**有一个能跑的服务。**

## 真实代码（`main.py` 第 34–48 行）

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
```

## 你现在敲

```powershell
curl.exe http://127.0.0.1:8090/openapi.json -o $env:TEMP\oa.json
python -c "import json,io; d=json.load(io.open(r'$env:TEMP\oa.json',encoding='utf-8')); print('路径数 =', len(d['paths'])); [print('  tag:', t['name']) for t in d['tags']]"
```

（或者更直观：浏览器打开 `http://127.0.0.1:8090/docs` 看页面）

## ✅ 真实输出

```
路径数 = 12
  tag: ops
  tag: chat
  tag: kb
  tag: feedback
```

## 💡 这一步的关键

**`title` / `description` / `openapi_tags` 不是注释，是渲染进 `/docs` 的内容。**

而且 `openapi_tags` 里那四组**不是随手写的**——它是把旧的 `server.py` 里
`do_GET` / `do_POST` / `do_DELETE` 那一堆 `if` 全部列出来后**归的类**。
这一步看着不起眼，但决定了后面 9 天会不会返工。

---

# 第 2 步 · 加一条最简路由：证明框架真的在工作

## 为什么现在做

`/docs` 能开只说明"app 对象建好了"。
**要证明"路由机制在工作"，得真发一个请求拿到响应。**

## 真实代码（`main.py` 第 107–109 行）

```python
@app.get("/", tags=["ops"], summary="服务信息")
async def root() -> dict:
    return api.ok({"name": config.APP_TITLE, "docs": "/docs", "health": "/health"})
```

## 你现在敲

```powershell
curl.exe -i http://127.0.0.1:8090/
```

## ✅ 真实输出

```
HTTP/1.1 200 OK
{"code":0,"msg":"ok","data":{"name":"Context Engine + Multi-Agent QA","docs":"/docs","health":"/health"}}
```

## 💡 这一步的关键

两条：
1. **`@app.get("/")` + 一个函数 = 一条路由。** 不用再写 `if path == "/"` 了
2. 返回的形状 `{code, msg, data}` **是提前定好的约定**，不是随口写的
   （真身在 `app/errors.py` 的 `ok()` 函数里）

**注意**：这一步用了 `api.ok(...)`，说明已经在往项目里接了。但**还没有连任何服务**——
`ok()` 只是个打包字典的工具函数。

---

# 第 3 步 · 第一次"接线"：把路由接上真业务 ★

## 为什么现在做

前两步都是"框架自己的事"。**这一步开始碰项目真正的代码**——
而这一步也是新手最容易卡住的地方。

## 真实代码（`main.py` 第 112–115 行）

```python
@app.get("/health", tags=["ops"], summary="健康检查（含实际生效的后端）")
async def health() -> dict:
    status, body = api.handle_health()
    return body
```

它调的那个函数（`app/api.py`）：

```python
def handle_health() -> tuple[int, dict]:
    return 200, ok(services().health().model_dump())


def services() -> AppServices:
    global _services
    if _services is None:
        _services = AppServices(seed_kb=True)
    return _services
```

## 你现在敲

```powershell
curl.exe http://127.0.0.1:8090/health
```

## ✅ 真实输出

```json
{"code":0,"msg":"ok","data":{"status":"ok","chat_backend":"fake",
 "retrieval_backend":"bm25","model":"fake","db_backend":"sqlite","cache_backend":"lru"}}
```

## 💡 这一步的关键（整份文档最重要的一段）

**路由函数里只有 3 行，一行业务逻辑都没有。**
但返回里冒出了 `chat_backend`、`db_backend`、`cache_backend`、`retrieval_backend`
——说明它连上了**配置层、存储层、检索层、模型层**。

而**你一个 `new` 都没写**。

**为什么？** 因为 `api.handle_health()` 内部调了 `services()`，
而 `services()` 在第一次被调用时会创建 `AppServices`——
打开 `app/services/chat_service.py` 看 `AppServices.__init__` 那十行：

```python
class AppServices:
    def __init__(self, seed_kb: bool = True):
        self.retriever = get_retriever()
        self.model = get_model_backend()
        self.store = ChatStore(config.DATA_DIR / "chat_history")
        self.kb_repo = KbRepository()
        self.feedback_repo = FeedbackRepository()
        self.metrics = get_metrics()
        self.engine = ContextEngine(
            config.CONTEXT_TOKEN_BUDGET,
            reranker=Reranker(),
            summarizer=HistorySummarizer(self.model),
        )
```

**整个项目的线，全插在这 10 行里。**

> **所以"接线"到底是什么意思？**
> 不是你去 new 一堆东西，而是**找到那个已经组装好的入口，调它**。
> 这个项目里的入口就是 `api.services()`。

## ⚠️ 这一步会遇到的报错

| 报错 | 原因 |
|---|---|
| `ModuleNotFoundError: No module named 'api'` | 写成了 `import api`，正确是 `from . import api` |
| `ModuleNotFoundError: No module named 'app'` | 不在 `backend/` 目录下启动 |
| `Error loading ASGI app. Import string "app.main" must be in format "<module>:<attribute>"` | 少写了 `:app` |

---

# 第 4 步 · 定契约 + 加业务路由

## 为什么现在做

`/health` 太简单（没有入参）。**真实接口要收参数**，这时候就需要"契约"。

## 真实代码

**契约**（`app/schemas.py` 第 19–22 行）：

```python
class ChatRequest(BaseModel):
    message: str = Field(..., description="The user's question")
    session_id: str = Field(default="default", description="Conversation id")
    stream: bool = Field(default=True, description="Stream tokens when True")
```

**路由**（`main.py` 第 125–129 行）：

```python
@app.post("/api/chat", tags=["chat"], summary="一次性返回完整回答",
          responses={400: {"description": "参数校验失败(40001)"}})
async def chat(payload: ChatRequest) -> dict:
    status, body = await run_in_threadpool(api.handle_chat, payload.model_dump())
    return body
```

## 你现在敲

```powershell
# 正常请求
curl.exe -X POST "http://127.0.0.1:8090/api/chat" `
  -H "Content-Type: application/json" `
  --data-binary '{\"message\":\"加绒牛仔怎么洗\",\"session_id\":\"walk\"}'

# 故意不传 message
curl.exe -X POST "http://127.0.0.1:8090/api/chat" `
  -H "Content-Type: application/json" `
  --data-binary '{\"session_id\":\"walk\"}'
```

> PowerShell 里双引号必须写成 `\"`，外层用单引号——我实测过四种写法，只有这种不会让 curl 收到坏 JSON。

## ✅ 真实输出

**正常请求**（HTTP 200，节选）：
```json
{"code":0,"msg":"ok","data":{
  "answer":"【离线演示】根据检索到的资料：[洗涤养护.txt] 加绒牛仔：水温≤30℃，中性洗涤剂，翻面清洗，机洗选轻柔模式，避免长时间浸泡。收纳时折叠平放，避免重压破坏绒层。纯棉保（问题：加绒牛仔怎么洗）",
  "context":{"slots":[{"kind":"system","priority":100,"tokens":64},
                      {"kind":"retrieval","priority":110,"tokens":157}, ...],
             "total_tokens":295,"budget":4096,"trimmed":0,"over_budget":false},
  "backend":"fake", "elapsed_ms":7}}
```

**少字段**（HTTP 400）：
```json
{"code":40001,"msg":"参数校验失败","data":null,
 "detail":[{"field":"body.message","msg":"Field required"}]}
```

## 💡 这一步的关键

**① 契约先行。** `ChatRequest` 这个类就是"前端要传什么"的书面约定。
你在 `/docs` 里能看到自动生成的请求体示例，**前端不用问你**。

**② `payload.model_dump()` 为什么要加。**
`payload` 是 pydantic 对象，而 `api.handle_chat` 是**框架无关**的普通函数，
它不认识 pydantic。所以转成普通 dict 再传。**这就是"防腐层"的成本。**

**③ 看 `context.slots` 的 `priority` 列**（这是项目核心）：

| slot | priority | 含义 |
|---|---|---|
| system | 100 | 系统指令，**永不参与裁剪** |
| retrieval | 110 / 44 | 检索资料，**按相关度给优先级** |
| history | 25 | 对话历史，**最低 → 预算不够时第一个被裁** |

---

# 第 5 步 · 补错误统一：被第 4 步逼出来的

## 为什么现在做

第 4 步你会在**没有异常处理器**的情况下，拿到 FastAPI 的**默认错误格式**：

```json
HTTP 422 Unprocessable Entity
{"detail":[{"type":"missing","loc":["body","message"],"msg":"Field required","input":{"session_id":"walk"}}]}
```

（这是我在本会话早前的实验里真实得到的输出）

**前端同事此刻会说**："正常返回是 `{code,msg,data}`，错误返回是 `{detail:[...]}`，**我要写两套解析**。"

所以要补三个异常处理器。

## 真实代码（`main.py` 第 85–103 行）

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

错误码在 `app/errors.py`：

```python
class ErrorCode(IntEnum):
    OK = 0
    BAD_REQUEST = 40000
    VALIDATION_ERROR = 40001
    NOT_FOUND = 40400
    ...
    INTERNAL_ERROR = 50000
    MODEL_ERROR = 50201
```

## 你现在敲（对比两种 404）

```powershell
# 业务 404
curl.exe -i -X DELETE "http://127.0.0.1:8090/api/kb/%E4%B8%8D%E5%AD%98%E5%9C%A8"

# 路径 404（路径本身不存在）
curl.exe -i "http://127.0.0.1:8090/api/nonexistent"
```

## ✅ 真实输出

**业务 404 —— 走了统一格式：**
```
HTTP/1.1 404 Not Found
{"code":40400,"msg":"知识库中没有来源：不存在","data":null}
```

**路径 404 —— 没走统一格式：**
```
HTTP/1.1 404 Not Found
{"detail":"Not Found"}
```

## 💡 这一步的关键（含一个真实发现）

**第 4 步那个 422 现在变成了统一的 400 + 40001**，四处变化都有用：

| 变化 | 从 | 到 | 为什么重要 |
|---|---|---|---|
| 状态码 | 422 | **400** | 约定就是 400 |
| 外层格式 | `{detail:[...]}` | **`{code,msg,data}`** | **前端只写一套解析** |
| 错误码 | 无 | **40001** | 前端按 code 分支，不靠字符串匹配 |
| 字段路径 | `loc:["body","message"]` | **`field:"body.message"`** | 前端能直接表单回填 |

**但上面那两条 404 的对比暴露了一个真实缺陷**：
`main.py` 只注册了 `AppError`、`RequestValidationError`、`Exception` 三个处理器，
而"路径不存在"抛的是 Starlette 的 `HTTPException`——**不归这三个管**，
被 Starlette 默认处理器接走了，所以格式没统一。

**修法是再加一个：**
```python
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.BAD_REQUEST
    return JSONResponse(status_code=exc.status_code, content=fail(code, str(exc.detail)))
```

> **这就是"跑通 ≠ 没问题"的典型例子。**
> 只有真发一个不存在的路径，才能看到这个漏网。

---

# 第 6 步 · 补中间件 + CORS：请求多了才需要

## 为什么现在做

接口多了以后，测试同事来报 bug，你问"什么时间哪个请求"，他说"就刚才三点多"——
**你翻日志翻了 20 分钟。** 这一步解决这个。

## 真实代码（`main.py` 第 50–81 行）

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


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
    log(logger, 20, "http", method=request.method, path=request.url.path,
        status=response.status_code, ms=round((time.perf_counter() - started) * 1000, 1))
    return response
```

## 你现在敲

```powershell
curl.exe -i http://127.0.0.1:8090/health
```

## ✅ 真实输出

**响应头**（真实）：
```
HTTP/1.1 200 OK
date: Fri, 18 Sep 2026 08:22:55 GMT
server: uvicorn
content-length: 152
content-type: application/json
x-request-id: 18f2dc05eedb          ← 就是这个
```

**服务端日志**（真实，节选）：
```
rid=2ff7d6bcec64 http method=GET  path=/                 status=200 ms=0.8
rid=ece8de99659a http method=GET  path=/health           status=200 ms=4.1
rid=483201fcfe3a http method=POST path=/api/chat         status=400 ms=0.5
rid=4959f0cb8447 http method=GET  path=/api/nonexistent  status=404 ms=0.2
```

**注意**：连 400 和 404 也照样有 `rid` 和耗时——
**出错的请求最需要排查，它们也有编号。**

## 💡 这一步的关键

**① 中间件 = 每个请求都过的关卡。** 写一次，13 个接口全都自动有了。

**② `contextvars` 为什么必须用。**
真实日志里有一条**跨 3 个模块**的记录：

```
rid=10a2670b99dd kb.chunk    chars=37 strategy=sentence       ← app.retrieval.knowledge
rid=10a2670b99dd kb.ingested source=checkup.txt chunks=1      ← app.retrieval.knowledge
rid=10a2670b99dd kb.upload   filename=checkup.txt size=89     ← app.api
rid=10a2670b99dd http method=POST path=/api/kb/upload         ← app.http
```

同一个 `rid` 出现在 **4 行、3 个不同模块**里。
因为 `run_in_threadpool` 会把活丢到别的线程，**普通全局变量并发时会串号**，`contextvars` 不会。

**③ CORS 为什么必须有。** 前端 5173、后端 8000，端口不同就是跨域，浏览器直接拦。
**排查提示**：这种情况**后端日志里什么都没有**（请求根本没发出），错误在浏览器控制台。

---

# 第 7 步 · 处理阻塞：一有慢操作就必须加

## 为什么现在做

第 3 步接上真业务后，代码要**读数据库、查检索索引、调模型**——全是阻塞操作。
直接写在 `async def` 里会**卡死整个服务**：不是变慢，是其他请求全部排队。

## 真实代码（`main.py` 第 128 行、134 行、140 行）

```python
status, body = await run_in_threadpool(api.handle_chat, payload.model_dump())
status, body = await run_in_threadpool(api.handle_chat_plan, payload.model_dump())
status, events = await run_in_threadpool(api.handle_chat_stream, payload.model_dump())
```

## 你现在看（对比日志里的耗时）

```powershell
# 先看一眼日志里这两种请求的耗时
```

## ✅ 真实输出（来自本次检测的真实日志）

```
rid=2ff7d6bcec64 http method=GET  path=/            status=200 ms=0.8    ← 只是打包字典
rid=ece8de99659a http method=GET  path=/health      status=200 ms=4.1    ← 读了配置+存储+检索
rid=52acec97bb61 http method=POST path=/api/chat    status=200 ms=6.1    ← 走完 5 个模块
rid=44297a6fa4b3 http method=POST path=/api/kb/ingest status=200 ms=10.1 ← 切分+写库+建索引
```

## 💡 这一步的关键

**原理**：IO 等待时让出事件循环；CPU 密集的活仍受 **GIL** 限制。
所以用线程池是正确方向，而不是"硬扛"或者"全改成 async"。

**判断标准很简单**：
> **这个函数里有没有读文件/读库/发网络请求？有 → 就要丢进 `run_in_threadpool`。**

**⚠️ 但这里有个坑（本次检测确认存在）**：
```python
status, events = await run_in_threadpool(api.handle_chat_stream, payload.model_dump())
```
`handle_chat_stream` 是**生成器**，这行只是"拿到生成器就返回了"，函数体一行没执行。
真正的模型调用发生在迭代时——**那时已经在事件循环线程里，线程池等于没生效。**

**根源**：Python 生成器函数被调用时**不执行函数体**。

**为什么现在看不出来？** 因为 `fake` 模型是瞬时的。换成 `qwen_api` 并发一上来就会堵。

---

# 第 8 步 · 加流式：特殊需求最后做

## 为什么现在做

产品说"聊天要打字机效果"。这是**特殊需求**，前面 7 步是通用骨架，这一步是加花。

## 真实代码（`main.py` 第 138–147 行）

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

## 你现在敲（`-N` 必须加）

```powershell
curl.exe -N -X POST "http://127.0.0.1:8090/api/chat/stream" `
  -H "Content-Type: application/json" `
  --data-binary '{\"message\":\"加绒牛仔怎么洗\",\"session_id\":\"walk\"}'
```

## ✅ 真实输出（共 21 个事件，前 6 条）

```
SSE 事件总数 = 21
data: {"type": "agent", "data": {"node": "router", "kind": "router", "summary": "路由判定", "detail": {"plan": ["retrieve"], ...}}}
data: {"type": "agent", "data": {"node": "retrieve", "kind": "retrieve", "summary": "检索到 2 条知识", ...}}
data: {"type": "retrieved", "data": [{"text": "加绒牛仔：水温≤30℃...", "source": "洗涤养护.txt", ...}]}
data: {"type": "token", "data": "【离线演示】"}
data: {"type": "token", "data": "根据检索到的"}
data: {"type": "token", "data": "资料：[洗涤"}
...
```

## 💡 这一步的关键

**四种事件 = 前后端契约：**

| 事件 | 前端拿来渲染什么 |
|---|---|
| `agent` | "Agent 协作链"面板 |
| `retrieved` | 命中的知识卡片（带 score） |
| `token` | **打字机效果** |
| `done` | 收尾：拿 context / trace / 完整答案 |

**SSE 格式很简单**：每条就是 `data: {JSON}` 加两个换行。

**还有两个上线才暴露的点**：
- `X-Accel-Buffering: no` 是给 nginx 看的
- `frontend/nginx.conf` 里还要 `proxy_buffering off`，否则 token 会被攒起来一起发
- **本地直接跑 uvicorn 看不出来，上线才暴露**

---

# 走完之后：一张总表

| 步 | 真实代码位置 | 这一步的验收（你刚跑过的命令） | 真实结果 |
|---|---|---|---|
| 1 | `main.py` 34–48 | `GET /openapi.json` | 12 条路径 / 4 分组 |
| 2 | `main.py` 107–109 | `GET /` | 200 + `{code:0,...}` |
| 3 | `main.py` 112–115 + `api.py` | `GET /health` | 200 + **4 个后端字段** |
| 4 | `schemas.py` 19–22 + `main.py` 125–129 | `POST /api/chat`（正常/少字段） | 200 真回答 / 400+40001 |
| 5 | `main.py` 85–103 | 两种 404 对比 | 业务 404 统一 ✅ / **路径 404 没统一** ❌ |
| 6 | `main.py` 50–81 | `curl -i /health` | `x-request-id: 18f2dc05eedb` |
| 7 | `main.py` 128 等 | 看日志耗时列 | 0.8ms（打包）→ 6.1ms（真业务） |
| 8 | `main.py` 138–147 | `curl -N .../stream` | **21 个 SSE 事件** |

**剩下的路由（kb 组、feedback 组、context、stats）就是把 1~8 步的套路重复一遍。**

---

# 全流程的三句话

1. **顺序**：建 app → 最简路由 → 接线 → 契约+业务路由 → 错误统一 → 中间件 → 处理阻塞 → 流式。
   **每一步都是被前一步逼出来的**，顺序错了要返工。
2. **接线的本质**：不是 You new 一堆东西，而是**找到已经组装好的入口（`api.services()`）调它**。
   整个项目的线插在 `AppServices.__init__` 那 10 行。
3. **跑通 ≠ 能用**。状态码、错误格式（含 404 漏网）、request_id、跨域、线程池——
   这些"不影响功能"的东西才决定它是不是一个能交付的接口。

---

# 附：你自己完整复现

```powershell
cd F:\shujuf\code\context-engine-agent\backend
uvicorn app.main:app --host 127.0.0.1 --port 8090

# 浏览器
#   http://127.0.0.1:8090/docs

# 1 步
curl.exe http://127.0.0.1:8090/openapi.json
# 2 步
curl.exe -i http://127.0.0.1:8090/
# 3 步
curl.exe http://127.0.0.1:8090/health
# 4 步
curl.exe -X POST "http://127.0.0.1:8090/api/chat" -H "Content-Type: application/json" --data-binary '{\"message\":\"加绒牛仔怎么洗\",\"session_id\":\"walk\"}'
curl.exe -X POST "http://127.0.0.1:8090/api/chat" -H "Content-Type: application/json" --data-binary '{\"session_id\":\"walk\"}'
# 5 步
curl.exe -i -X DELETE "http://127.0.0.1:8090/api/kb/%E4%B8%8D%E5%AD%98%E5%9C%A8"
curl.exe -i "http://127.0.0.1:8090/api/nonexistent"
# 6 步
curl.exe -i http://127.0.0.1:8090/health
# 8 步
curl.exe -N -X POST "http://127.0.0.1:8090/api/chat/stream" -H "Content-Type: application/json" --data-binary '{\"message\":\"加绒牛仔怎么洗\",\"session_id\":\"walk\"}'

# 测试（和 CI 同一条命令）
python -m unittest discover -s tests -q
```
