# FastAPI 从 0 到 1 一步步跑通（真实运行记录）

> **这份文档的每一行输出都是真跑出来的。**
> 做法：从空文件开始，一步一步往里加，**每加一步就起一次服务、打同一组探针**，
> 看接口从"不存在"变成"能用"。
>
> - 环境：Python 3.12.7 / FastAPI 0.141.1 / uvicorn 0.52.4 / pydantic 2.12.5
> - 每一步的文件在 `_run_log/steps/step1.py` ~ `step8.py`
> - 每一步都用同一组探针：`GET /health`、`POST /api/chat`（正常）、`POST /api/chat`（少字段）
> - 8 步跑完，8 次启动服务，**每一步的真实响应都记在下面**

---

# 第一部分 · 先大概讲下干了什么

## 一句话

**把"收信、校验、回信"三件烦事交给 FastAPI，你只写业务。**
然后从 0 开始，**每一步只加一点点，加完立刻能跑**。

## 具体做了什么

| 步 | 加什么 | 一句话 |
|---|---|---|
| 1 | 空壳 | 让 `/docs` 能打开 |
| 2 | 一个假的 `/health` | 先有个真接口，内容先写死 |
| 3 | 换成真业务 | **第一次"接线"** |
| 4 | `POST /api/chat` | 只做校验，不接业务 |
| 5 | 三个异常处理器 | **统一错误格式** |
| 6 | 中间件 + CORS | request_id + 跨域 |
| 7 | 真正接上业务 | echo → 真回答 |
| 8 | SSE 流式 | 打字机效果 |

## 8 步的探针演变（这张表就是全部故事）

| 步 | `GET /health` | `POST /api/chat` 正常 | `POST /api/chat` 少字段 | `X-Request-ID` | 服务端 `rid` 日志 |
|---|---|---|---|---|---|
| 1 | **404** | **404** | **404** | 无 | 无 |
| 2 | **200 假数据** | 404 | 404 | 无 | 无 |
| 3 | **200 真实后端信息** | 404 | 404 | 无 | 无 |
| 4 | 200 | **200 echo** | **422 默认格式** | 无 | 无 |
| 5 | 200 | 200 echo | **400 统一格式** | 无 | 无 |
| 6 | 200 | 200 echo | 400 统一 | **✅ 有** | **✅ 有** |
| 7 | 200 | **200 真实回答** | 400 统一 | ✅ | ✅ |
| 8 | 200 | 200 真实回答 | 400 统一 | ✅ | ✅ **+ SSE 21 个事件** |

**注意第 4 步到第 5 步那一格**：`422 默认格式` → `400 统一格式`。
这是全过程最值钱的一个变化，后面详细讲。

---

# 第二部分 · 为什么要这样

## 为什么从空壳开始，而不是直接写 `/api/chat`

因为 `/api/chat` 要串 5 个模块（路由 → 检索 → 上下文 → 模型 → 存储）。
如果第一次就写它，报错了你**根本不知道是哪一层的锅**。

先写空壳、再写 `/health`，**出错一定是接线的问题，范围小到可以一眼看穿**。

## 为什么每一步都要"起服务 + 打探针"

这是新手和专业开发最大的区别：

> **不是"写三天一起跑"，而是"写十行就跑一次"。**

看第 1 步和第 2 步的差别：第 1 步 `/health` 是 404，第 2 步变成 200。
**这个"从不存在到存在"的确认，就是你能继续往下写的信心来源。**

## 为什么第 4 步要"只做校验、不接业务"

因为要**把两类问题分开**：

- 参数校验对不对？→ 第 4 步单独验证
- 业务链路通不通？→ 第 7 步单独验证

混在一起做，出错时你分不清是"字段没传对"还是"模型调不通"。

## 为什么第 5 步（统一错误格式）不能省

第 4 步的实测结果表明：**FastAPI 默认返回 422，而且格式是它自己的：**

```json
{"detail":[{"type":"missing","loc":["body","message"],"msg":"Field required","input":{"session_id":"s1"}}]}
```

而你项目的约定是 `{code, msg, data}`。**前端得写两套解析**。
第 5 步就是把这个格式掰回来。

**这一步最容易漏，因为它不影响"功能正常"**——
接口能通、数据能返回，新手就觉得完事了。

---

# 第三部分 · 8 步具体开发流程（含真实运行结果）

## 第 1 步 · 空壳：让 `/docs` 能打开

### 代码（`_run_log/steps/step1.py`）

```python
"""第 1 步：最小空壳。目标只有一个：让 /docs 能打开。"""
from fastapi import FastAPI

app = FastAPI(title="接线练习")


@app.get("/hello")
async def hello() -> dict:
    return {"msg": "hello fastapi"}
```

### 怎么跑

```bash
cd backend
uvicorn app.main_practice:app --host 127.0.0.1 --port 8041
```

### 真实运行结果

```
[A] GET /health          -> HTTP/1.1 404 Not Found   X-Request-ID=(none)
    {"detail":"Not Found"}
[B] POST /api/chat 正常   -> HTTP/1.1 404 Not Found
    {"detail":"Not Found"}
[C] POST /api/chat 少字段  -> HTTP/1.1 404 Not Found
    {"detail":"Not Found"}
```

### 学到了什么

- 三个探针全是 **404** —— 这就是"接口还不存在"的样子
- 404 的响应体是 FastAPI 默认的 `{"detail":"Not Found"}`
- 打开 `/docs` 能看到 `/hello`，**这就是全部成果**，但它是后面所有事的地基

> **新手要点**：这一步不要觉得"太简单了没必要"。你花 5 分钟换来的，
> 是一个**确定能工作**的地基。

---

## 第 2 步 · 加一个假的 `/health`

### 为什么先写假的

"接线"是陌生的事，"返回一个字典"是熟悉的事。
**先把熟悉的做对，再把陌生的接上去。**

### 代码（`_run_log/steps/step2.py`）

```python
"""第 2 步：加一个假的 /health。先让一个真接口通，内容先写死。"""
from fastapi import FastAPI

app = FastAPI(title="接线练习")


@app.get("/hello")
async def hello() -> dict:
    return {"msg": "hello fastapi"}


@app.get("/health", tags=["ops"], summary="健康检查")
async def health() -> dict:
    return {"code": 0, "msg": "ok", "data": {"status": "ok"}}
```

### 真实运行结果

```
[A] GET /health          -> HTTP/1.1 200 OK   X-Request-ID=(none)
    {"code":0,"msg":"ok","data":{"status":"ok"}}
[B] POST /api/chat 正常   -> HTTP/1.1 404 Not Found
[C] POST /api/chat 少字段  -> HTTP/1.1 404 Not Found
```

### 学到了什么

- **`/health` 从 404 变成 200** —— 这一个变化就是这一步的全部价值
- `tags=["ops"]` 和 `summary=` **直接改变了 `/docs` 的样子**（多了分组和说明）
- 返回的形状 `{"code":0,"msg":"ok","data":...}` 是**提前对齐的契约**，
  不是随口写的。整个项目 13 个接口都长这样

---

## 第 3 步 · 换成真业务（第一次"接线"）

### 代码（`_run_log/steps/step3.py`）

```python
"""第 3 步：把假数据换成真业务 —— 第一次"接线"。"""
from fastapi import FastAPI

from . import api
from .logging_config import setup_logging

setup_logging()

app = FastAPI(title="接线练习")


@app.get("/health", tags=["ops"], summary="健康检查（含实际生效的后端）")
async def health() -> dict:
    status, body = api.handle_health()
    return body
```

### 真实运行结果

```
[A] GET /health          -> HTTP/1.1 200 OK   X-Request-ID=(none)
    {"code":0,"msg":"ok","data":{"status":"ok","chat_backend":"fake",
     "retrieval_backend":"bm25","model":"fake","db_backend":"sqlite","cache_backend":"lru"}}
```

### 学到了什么（这一步最重要）

**只改了 3 行代码**，返回里就冒出了 `chat_backend`、`db_backend`、`cache_backend`。

这说明：**它连上了配置层、存储层、检索层、模型层。**

而你没有 `new` 任何一个对象——`api.handle_health` 内部调了 `services()`，
`services()` 内部在 `AppServices.__init__` 里把整个服务栈组装好了。

> **这就是"接线"的真面目**：不是你去 new 一堆东西，
> 而是**找到那个已经组装好的入口，调它。**

### 这一步含两个新手必踩的点

**① `from . import api` 的点（`.`）**

`.` 表示"当前包"。这样写要求文件被当作模块导入，
所以启动方式必须是 `uvicorn app.main_practice:app`，**而且要在 `backend/` 下**。

如果写成 `import api`，真实报错长这样：

```
File "...\app\main_wrong.py", line 2, in <module>
    import api
ModuleNotFoundError: No module named 'api'
```

如果不在 `backend/` 目录下启动，真实报错：

```
ModuleNotFoundError: No module named 'app'
```

**② 为什么这里不用 `run_in_threadpool`？**

因为 `handle_health` 几乎不耗时。等第 7 步接 `/api/chat`（要读库、检索、调模型）
就**必须**加了。

---

## 第 4 步 · 加 `POST /api/chat`，但只做校验

### 为什么先不接业务

要**把"校验"和"业务"分开验证**。混着做，出错时你分不清是哪一类。

### 代码（`_run_log/steps/step4.py`）

```python
"""第 4 步：加 POST /api/chat —— 先只做校验，不接业务。"""
from fastapi import FastAPI

from . import api
from .logging_config import setup_logging
from .schemas import ChatRequest

setup_logging()

app = FastAPI(title="接线练习")


@app.get("/health", tags=["ops"], summary="健康检查（含实际生效的后端）")
async def health() -> dict:
    status, body = api.handle_health()
    return body


@app.post("/api/chat", tags=["chat"], summary="一次性返回完整回答（先只做校验）")
async def chat(payload: ChatRequest) -> dict:
    return {"code": 0, "msg": "ok", "data": {"echo": payload.model_dump()}}
```

请求模型来自项目已有的 `backend/app/schemas.py`：

```python
class ChatRequest(BaseModel):
    message: str = Field(..., description="The user's question")
    session_id: str = Field(default="default", description="Conversation id")
    stream: bool = Field(default=True, description="Stream tokens when True")
```

### 真实运行结果

```
[A] GET /health          -> 200（真实后端信息）
[B] POST /api/chat 正常   -> HTTP/1.1 200 OK
    {"code":0,"msg":"ok","data":{"echo":{"message":"加绒牛仔怎么洗","session_id":"s1","stream":true}}}
[C] POST /api/chat 少字段  -> HTTP/1.1 422 Unprocessable Entity
    {"detail":[{"type":"missing","loc":["body","message"],"msg":"Field required","input":{"session_id":"s1"}}]}
```

### 学到了什么

**好的一面**：
- 探针 B 出现了 `"echo":{...}`，而且 `stream:true` 是**你没传、它自动补的默认值**
- 你在 `/docs` 里能看到请求体的字段说明（来自 `Field(..., description=...)`）
- **你一行校验代码都没写**

**坏的一面（关键）**：
- 探针 C 返回 **422**，不是 400
- 响应体是 **`{"detail":[{"type":"missing","loc":[...]}]}`**，
  **跟你项目的 `{code,msg,data}` 完全不一样**

> **前端同事此刻会说**："你这个错误格式我要单独写一套解析。"
> → 所以有第 5 步。

---

## 第 5 步 · 统一错误格式（最值钱的一步）

### 代码（`_run_log/steps/step5.py`，只贴新增部分）

```python
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .errors import AppError, ErrorCode, fail
from .logging_config import get_logger, log, setup_logging

logger = get_logger("practice.http")


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.http_status, content=fail(exc.code, exc.msg, exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    detail = [{"field": ".".join(str(p) for p in e.get("loc", ())), "msg": e.get("msg", "")}
              for e in exc.errors()]
    return JSONResponse(status_code=400,
                        content=fail(ErrorCode.VALIDATION_ERROR, "参数校验失败", detail))


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    log(logger, 40, "http.error", path=request.url.path, error=exc.__class__.__name__)
    return JSONResponse(status_code=500, content=fail(ErrorCode.INTERNAL_ERROR, "服务器内部错误"))
```

### 真实运行结果（同一个探针 C，前后对比）

**第 4 步（加了处理器之前）：**
```
[C] POST /api/chat 少字段  -> HTTP/1.1 422 Unprocessable Entity
    {"detail":[{"type":"missing","loc":["body","message"],"msg":"Field required","input":{"session_id":"s1"}}]}
```

**第 5 步（加了处理器之后）：**
```
[C] POST /api/chat 少字段  -> HTTP/1.1 400 Bad Request
    {"code":40001,"msg":"参数校验失败","data":null,"detail":[{"field":"body.message","msg":"Field required"}]}
```

### 学到了什么

**四处变化，每一处都有用**：

| 变化 | 从 | 到 | 为什么重要 |
|---|---|---|---|
| 状态码 | 422 | **400** | 你们约定校验失败是 400 |
| 外层格式 | `{detail:[...]}` | **`{code,msg,data,detail}`** | 前端只写一套解析 |
| 错误码 | 无 | **40001** | 前端按 code 做分支，不靠字符串匹配 message |
| 字段路径 | `loc:["body","message"]` | **`field:"body.message"`** | 前端可直接拿去表单回填 |

**为什么要三个处理器**：错误有三个来源，必须分开接：

| 处理器 | 谁抛的 | 映射到 |
|---|---|---|
| `AppError` | 你自己的业务代码 `raise AppError(...)` | 它自带的错误码 |
| `RequestValidationError` | pydantic 自动抛 | 400 / 40001 |
| `Exception` | 任何漏网的 bug | 500 / 50000（**不泄露堆栈**） |

---

## 第 6 步 · 中间件 + CORS

### 代码（`_run_log/steps/step6.py`，只贴新增部分）

```python
import time
from fastapi.middleware.cors import CORSMiddleware
from . import config
from .errors import error_from_exception
from .logging_config import set_request_id

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
    except Exception as exc:
        status, body = error_from_exception(exc)
        response = JSONResponse(status_code=status, content=body)
    response.headers["X-Request-ID"] = rid
    log(logger, 20, "http", method=request.method, path=request.url.path,
        status=response.status_code, ms=round((time.perf_counter() - started) * 1000, 1))
    return response
```

### 真实运行结果

**探针 A 的响应头，多了一行：**

```
[A] GET /health          -> HTTP/1.1 200 OK   X-Request-ID=b4e88610c138
```

**服务端日志，从"什么都没有"变成：**

**第 1~5 步的日志**：
```
(没有 rid= 日志 —— 中间件尚未加入)
```

**第 6 步开始**：
```
2026-09-18 16:10:09 INFO  practice.http          rid=b4e88610c138 http method=GET path=/health status=200 ms=3.4
2026-09-18 16:10:09 INFO  practice.http          rid=a6f400fa4082 http method=POST path=/api/chat status=200 ms=0.7
2026-09-18 16:10:09 INFO  practice.http          rid=22b4d822141d http method=POST path=/api/chat status=400 ms=0.5
```

### 学到了什么

- **中间件 = 每个请求都过的关卡**（类比：小区大门保安）
- 一次加完，**13 个接口全都自动有了**日志和 request_id，不用写 13 遍
- `X-Request-ID` 同时在**响应头**（给用户看）和**日志**（给你查）
- 排查链路：用户截图响应头 → 搜日志 → 那次请求的完整经过

**为什么用 `contextvars` 而不是全局变量？**
因为 `run_in_threadpool` 会把活丢到别的线程，全局变量并发时会串号。

**CORS 为什么必须有？**
前端在 `5173`、后端在 `8000` → 端口不同 = 跨域 → 浏览器直接拦。
**排查提示**：这种情况后端日志里什么都没有（请求根本没发出），
错误在**浏览器控制台**，别去后端找。

---

## 第 7 步 · 真正接上业务

### 代码（`_run_log/steps/step7.py`，只贴变化的那条路由）

```python
from starlette.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse


@app.post("/api/chat", tags=["chat"], summary="一次性返回完整回答")
async def chat(payload: ChatRequest) -> dict:
    status, body = await run_in_threadpool(api.handle_chat, payload.model_dump())
    return JSONResponse(status_code=status, content=body)
```

### 真实运行结果

**探针 B，从 echo 变成真回答：**

```
[B] POST /api/chat 正常   -> HTTP/1.1 200 OK
    {"code":0,"msg":"ok","data":{
      "answer":"【离线演示】根据检索到的资料：[洗涤养护.txt] 加绒牛仔：水温≤30℃，中性洗涤剂，
                翻面清洗，机洗选轻柔模式，避免长时间浸泡。收纳时折叠平放，避免重压破坏绒层。
                纯棉保（问题：加绒牛仔怎么洗）",
      "session_id":"s1",
      "context":{"slots":[
         {"kind":"system","priority":100,"tokens":64},
         {"kind":"retrieval","priority":110,"tokens":157},
         ...], "total_tokens":607, "budget":4096, "trimmed":0, "over_budget":false},
      "backend":"fake", ...}}
```

**同时服务端日志的耗时变了：**

```
第 6 步: rid=... path=/api/chat status=200 ms=0.7    ← echo，几乎不耗时
第 7 步: rid=... path=/api/chat status=200 ms=10.4   ← 真业务，要读库+检索+调模型
```

### 学到了什么

**① `payload.model_dump()` 为什么必须加**
`payload` 是 pydantic 对象，`api.handle_chat` 是**框架无关**的普通函数，不认识它。
所以转成普通 dict 再传。**这就是"防腐层"的成本。**

**② `run_in_threadpool` 为什么必须加**
第 7 步开始读库、检索、调模型，**全是阻塞操作**。
直接写在 `async def` 里会**卡死整个服务**（不是变慢，是其他请求全排队）。

**③ `status` 为什么不能省**
`handle_chat` 返回 `(状态码, 响应体)` 两个值。
**新手最容易写成 `return body`，状态码就丢了。**
正确写法永远是 `JSONResponse(status_code=status, content=body)`。

**④ 日志耗时从 0.7ms 跳到 10.4ms —— 这就是"接上真业务"的量化证据**

---

## 第 8 步 · SSE 流式

### 代码（`_run_log/steps/step8.py`，只贴新增部分）

```python
import json
from fastapi.responses import StreamingResponse


@app.post("/api/chat/stream", tags=["chat"], summary="SSE 流式回答（agent/token/retrieved/done）")
async def chat_stream(payload: ChatRequest):
    status, events = await run_in_threadpool(api.handle_chat_stream, payload.model_dump())

    async def gen():
        for evt in events:
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

### 真实运行结果

```
[D] POST /api/chat/stream -> 共 21 个事件，前 3 条：
    data: {"type": "agent", "data": {"node": "router", "kind": "router", "summary": "路由判定",
           "detail": {"plan": ["retrieve"], "tools": [...]}}}
    data: {"type": "agent", "data": {"node": "retrieve", "kind": "retrieve",
           "summary": "检索到 2 条知识", "detail": {"docs": [...]}}}
    data: {"type": "retrieved", "data": [{"text": "加绒牛仔：水温≤30℃...", "source": "洗涤养护.txt", ...}]}
```

**服务端日志（第 8 步最后一行，多出了 stream 路由）：**
```
2026-09-18 16:10:22 INFO  practice.http  rid=a24dc1cb603d http method=POST path=/api/chat/stream status=200 ms=3.0
```

21 个事件的构成：2 个 `agent` + 1 个 `retrieved` + 17 个 `token` + 1 个 `done`。

### 学到了什么

**四种事件的分工（这就是前后端契约）：**

| 事件 | 前端拿来渲染什么 |
|---|---|
| `agent` | "Agent 协作链"面板 |
| `retrieved` | 命中的知识卡片（带 score） |
| `token` | **打字机效果**（一个字一个字蹦） |
| `done` | 收尾：拿 context / trace / 完整答案 |

**这一天有个真实的坑（这次没暴露）**：
`events` 是**生成器**，`run_in_threadpool(api.handle_chat_stream, ...)`
**只是拿到生成器就返回了**，函数体一行没执行。
真正的模型调用发生在 `for evt in events` 迭代时，**那时已在事件循环线程里**。

**为什么这次看不出来？** 因为 `fake` 模型是瞬时的。
换成 `qwen_api`（真网络调用）并发一上来就会堵住事件循环。

---

# 第四部分 · 新手一定会卡住的地方（真实报错）

下面三条是**真跑出来的报错原文**，不是猜的。

## ① 相对导入写成绝对导入

```python
# 错
import api
# 对
from . import api
```

真实报错：
```
File "...\app\main_wrong.py", line 2, in <module>
    import api
ModuleNotFoundError: No module named 'api'
```

## ② 不在 `backend/` 目录下启动

真实报错：
```
ModuleNotFoundError: No module named 'app'
```

**原因**：`app.main` 这个写法要求"当前目录能看见 `app` 文件夹"。

## ③ `uvicorn` 少写 `:app`

```
ERROR:    Error loading ASGI app. Import string "app.main" must be in format "<module>:<attribute>".
```

**记法**：`uvicorn 模块路径:变量名` → `uvicorn app.main:app`
（`app/main.py` 文件里的那个叫 `app` 的变量）

## ④ 还有两个不报错但会让你怀疑人生的

- **改了代码不生效** → `--reload` 只对 Python 文件生效；改了 `.env` 要重启
- **前端一个请求都发不出去，后端日志干干净净** → 是 CORS，去浏览器控制台看

---

# 第五部分 · 你自己照做（完整命令）

每一步的文件在 `F:\shujuf\code\_run_log\steps\step1.py` ~ `step8.py`。

```bash
cd backend

# 第 1 步：把 step1.py 内容存成 app/main_practice.py，然后
uvicorn app.main_practice:app --host 127.0.0.1 --port 8041
# 打开 http://127.0.0.1:8041/docs

# 每改一次代码，就重跑这组探针（换端口避免 TIME_WAIT）
curl.exe http://127.0.0.1:8041/health

curl.exe -X POST http://127.0.0.1:8041/api/chat ^
  -H "Content-Type: application/json" ^
  --data-binary "{\"message\":\"加绒牛仔怎么洗\",\"session_id\":\"s1\"}"

# 少字段（看错误格式在 step4 -> step5 之间的变化）
curl.exe -X POST http://127.0.0.1:8041/api/chat ^
  -H "Content-Type: application/json" ^
  --data-binary "{\"session_id\":\"s1\"}"

# 第 8 步看 SSE（-N 关掉 curl 自己的缓冲）
curl.exe -N -X POST http://127.0.0.1:8041/api/chat/stream ^
  -H "Content-Type: application/json" ^
  --data-binary "{\"message\":\"加绒牛仔怎么洗\",\"session_id\":\"s1\"}"
```

**每走一步，先看这四件事**：
1. `GET /health` 的状态码变了没
2. `/docs` 里多没多东西
3. 服务端日志多没多 `rid=` 那一行
4. 少字段的错误格式（**第 4→5 步会从 422 变 400，这是最直观的进步**）

---

# 最后 · 整个过程压成三句话

1. **干了什么**：从空文件开始，8 步——
   空壳 → 假 `/health` → 接线 → 加校验 → 统一错误 → 加中间件 → 接真业务 → 加流式。
   **每步都起服务打探针，看着接口从 404 变成 200。**

2. **为什么要这样**：
   先跑通再填内容（出错范围小）；
   把"校验"和"业务"分开验证（出错好定位）；
   **每一步都能跑，你才一直有退路**。

3. **从 0 到 1 的核心不是语法，是顺序**：
   ```
   能跑  →  接线  →  契约  →  错误  →  横切  →  特殊需求
   ```
   顺序错了就会返工。比如先做 SSE 再补错误格式，
   等于所有流式接口的错误处理都要回头改一遍。
