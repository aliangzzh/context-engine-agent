# FastAPI 开发流程逐步重放（这个项目的真实演化过程）

> **怎么用这份文档**：不要只是读。每读完一步，就把代码敲进 `backend/fastapi-practice/`
> 下的一个文件里，跑一遍，看一眼 `/docs` 有什么变化。
>
> 全程 12 步。起点是项目里**真实存在**的 `backend/fastapi-practice/hello.py`（8 行），
> 终点是**真实存在**的 `backend/app/main.py`（197 行）。
> 走完你会发现：那 197 行每一段你都知道是怎么来的。

---

## 总的规律（先看这个，再往下走）

整个演化顺序不是随便排的，它遵循一条逻辑：

```
先能跑  →  再接业务  →  再补契约  →  再补错误  →  再补横切  →  最后处理特殊需求
  ①          ②④          ③⑤         ⑥⑦         ⑧⑨          ⑩⑪
```

**每一步都必须能跑起来。** 这是新手最该学的工作习惯：
不是"写三天一起跑"，而是"半小时后就能跑，然后一直保持能跑"。

---

## 第 0 步 · 起点：项目里真实存在的 8 行

文件：`backend/fastapi-practice/hello.py`

```python
from fastapi import FastAPI

app = FastAPI(title="我的第一个 FastAPI")


@app.get("/hello")
def hello():
    return {"msg": "hello fastapi"}
```

**怎么跑**：

```bash
cd backend/fastapi-practice
uvicorn hello:app --reload
```

**看什么**：打开 `http://localhost:8000/docs`，你会看到一个叫"我的第一个 FastAPI"的页面，
里面有一个 `/hello` 接口，点 **Try it out** → **Execute**，就能看到返回。

**新手第一个懵点**：`uvicorn hello:app` 是什么意思？

| 部分 | 含义 |
|---|---|
| `uvicorn` | 服务器程序（负责网络收发） |
| `hello` | 模块名 = `hello.py` 文件 |
| `:app` | 这个文件里那个叫 `app` 的变量 |

**注意**：这个文件能直接跑，是因为它**没有用相对导入**。
一旦你写 `from . import api`，就必须用 `uvicorn app.main:app` 这种模块方式启动，
而且要在 `backend/` 目录下跑。这是新手第一个大坑。

---

## 第 1 步 · 把"应用信息"写上（决定 /docs 长什么样）

真实代码在 `main.py` 开头：

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

**要理解的关键点**（新手最容易以为这些是"注释"）：

`title` / `description` / `openapi_tags` **不是注释，是渲染进 `/docs` 的内容**。
刷新 `/docs`，你会看到页面标题变了、多了四组分类。

**这就是 FastAPI 让人爽的地方**：你写代码的时候顺手把文档写了。
`openapi_tags` 里的四个名字，正好对应你项目 13 条路由的四个分组。

---

## 第 2 步 · 第一个真接口——但先返回假数据

**新手最常犯的错**：一上来就接 `/api/chat`。
结果它要串 5 个模块，报错了你根本不知道是哪一层的问题。

**正确做法**：先接一个最傻的，跑通了再往里面填东西。

```python
@app.get("/health", tags=["ops"], summary="健康检查")
async def health() -> dict:
    return {"code": 0, "msg": "ok", "data": {"status": "ok"}}
```

**看什么**：`/docs` 里 `ops` 分组下出现"健康检查"，点开能试。

**为什么返回 `{"code": 0, "msg": "ok", "data": ...}` 这个形状？**
因为这是整个项目的**统一响应约定**（写死在 `errors.py` 的 `ok()` 里）。
前端只需要认这一个形状，所有接口都一样。**新手要养成"先定形状再写代码"的习惯。**

---

## 第 3 步 · 连上业务（第一次"接线"）

这一步是整个项目的灵魂。把上面返回假数据的 `health` 换成真实的：

```python
from . import api
from starlette.concurrency import run_in_threadpool


@app.get("/health", tags=["ops"], summary="健康检查（含实际生效的后端）")
async def health() -> dict:
    status, body = await run_in_threadpool(api.handle_health)
    return body
```

**看什么**：刷新 `/health`，返回的 `data` 里多了这些东西：

```json
{
  "status": "ok",
  "chat_backend": "fake",
  "retrieval_backend": "bm25",
  "model": "fake",
  "db_backend": "sqlite",
  "cache_backend": "lru"
}
```

**这说明它真的连上了项目的配置层、存储层、检索层。**
而你只写了三行——**这就是"接线"**：你不需要 new 任何东西，
`api.handle_health` 内部会自动把整个服务栈组装好。

**你会在这里冒出三个问题**（都是好问题）：

**Q1：`from . import api` 的点是什么意思？**
`.` 表示"当前包"。这样写在文件被当作模块导入时才能工作，
所以启动方式必须是 `uvicorn app.main:app`（从 `backend/` 目录），
不能是 `python app/main.py`。**这是新手第一大坑。**

**Q2：`api.handle_health` 内部凭什么有数据？**
它调了 `services()`——一个懒加载的全局单例。第一次调用时才创建整个服务栈。
（详见第 6 步之后的"接线总表"）

**Q3：`run_in_threadpool` 为什么要加？**
因为 `handle_health` 里要读数据库、查检索索引，**这些是阻塞操作**。
如果直接写在 `async def` 里，会卡住整个服务，别的请求全部排队。
**记住结论：`async def` 里不能直接写慢操作，要丢进 `run_in_threadpool`。**

---

## 第 4 步 · 加请求模型，先看校验生效

先定义"前端要传什么"（真实代码在 `schemas.py`）：

```python
# app/schemas.py
class ChatRequest(BaseModel):
    message: str = Field(..., description="The user's question")
    session_id: str = Field(default="default", description="Conversation id")
    stream: bool = Field(default=True, description="Stream tokens when True")
```

然后在路由里用它——**但这一步先不接业务，只看校验**：

```python
from .schemas import ChatRequest


@app.post("/api/chat", tags=["chat"], summary="一次性返回完整回答")
async def chat(payload: ChatRequest) -> dict:
    return {"code": 0, "msg": "ok", "data": {"echo": payload.model_dump()}}
```

**看什么**（这一步的观察最值钱）：

1. `/docs` 里 `POST /api/chat` 现在自动出现了**请求体示例**，字段名、类型、说明全都有
2. 点 Try it out，**把 `message` 删掉**再 Execute → 返回 400
3. 把 `message` 填上 → 返回你传的内容

**你一行校验代码都没写，FastAPI 全干了。**
这就是为什么说"参数写在函数签名里，不在函数体里取"。

**但这里有个问题要引出下一步**：这时候返回的 400 长这样：

```json
{"detail": [{"loc": ["body", "message"], "msg": "Field required", ...}]}
```

**这跟你项目的统一格式 `{code, msg, data}` 不一样！** 前端要处理两种错误格式。
→ 所以下一步必须做错误统一。

---

## 第 5 步 · 统一错误格式（新手最容易漏、但价值最高的一步）

真实代码在 `main.py` 里有三个异常处理器：

```python
from fastapi.exceptions import RequestValidationError
from .errors import AppError, ErrorCode, error_from_exception, fail


# ① 业务自己抛的错（AppError）
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.http_status, content=fail(exc.code, exc.msg, exc.detail))


# ② 参数校验失败（pydantic 抛的）
@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    detail = [{"field": ".".join(str(p) for p in e.get("loc", ())), "msg": e.get("msg", "")}
              for e in exc.errors()]
    return JSONResponse(
        status_code=400,
        content=fail(ErrorCode.VALIDATION_ERROR, "参数校验失败", detail),
    )


# ③ 未知异常（兜底，不泄露堆栈）
@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    log(logger, 40, "http.error", path=request.url.path, error=exc.__class__.__name__)
    return JSONResponse(status_code=500, content=fail(ErrorCode.INTERNAL_ERROR, "服务器内部错误"))
```

**为什么要三个？** 因为错误有三个来源：

| 来源 | 谁抛的 | 映射到 |
|---|---|---|
| 业务逻辑发现问题 | 你自己 `raise AppError(...)` | 它自带的错误码 |
| 前端传的参数不对 | pydantic 自动抛 | 400 / 40001 |
| 谁也想不到的 bug | Python 自己抛 | 500 / 50000 |

**看什么**：再回 `/docs` 故意删掉 `message`，现在返回的是：

```json
{"code": 40001, "msg": "参数校验失败", "data": null, "detail": [{"field": "body.message", ...}]}
```

**格式统一了。** 前端从此只需要写一套错误处理。

> **这一步为什么最容易漏？** 因为它不影响"功能正常"——
> 接口能通、数据能返回，新手就觉得完事了。
> 但真实工作里，前端会来找你三次："为什么有的接口报 `detail` 有的报 `msg`？"
> 而且 `detail` 里那个 `loc: ["body","message"]` 前端还得自己解析，很烦。

---

## 第 6 步 · 真的接上业务

现在把第 4 步的"echo"换成真的：

```python
@app.post("/api/chat", tags=["chat"], summary="一次性返回完整回答",
          responses={400: {"description": "参数校验失败(40001)"}})
async def chat(payload: ChatRequest) -> dict:
    status, body = await run_in_threadpool(api.handle_chat, payload.model_dump())
    return JSONResponse(status_code=status, content=body)
```

**三个新手必须看懂的点**：

**① `payload.model_dump()` 是什么？**
`payload` 是 pydantic 对象，`model_dump()` 把它转成普通 dict。
为什么要转？因为 `api.handle_chat` 是**框架无关**的普通函数，它不认识 pydantic。

**② `status` 是什么？为什么不能省？**
`handle_chat` 返回 `(状态码, 响应体)` 两个值。状态码得你自己塞进响应里。
**新手最容易写成 `return body`——这样状态码就丢了。**
（你项目现在真实存在这个问题：`/api/chat`、`/health`、`/api/stats`、`/api/context/{id}`
四条路由丢了 status，而 `/api/kb/upload`、`/api/kb/list` 却传了。
今天不炸是因为这些 handler 恒返回 200。**正确写法永远是 `JSONResponse(status_code=status, ...)`**）

**③ `responses={400: {...}}` 是干嘛的？**
纯文档用途——告诉 `/docs` "这个接口会返回 400"。

---

## 第 7 步 · 加 request_id 中间件（让排查有线索）

```python
@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = set_request_id(request.headers.get("X-Request-ID"))
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:                      # ← 第二道兜底
        status, body = error_from_exception(exc)
        log(logger, 40, "http.unhandled", path=request.url.path, error=exc.__class__.__name__)
        response = JSONResponse(status_code=status, content=body)
    response.headers["X-Request-ID"] = rid        # ← 把编号写回响应头
    log(logger, 20, "http", method=request.method, path=request.url.path,
        status=response.status_code, ms=round((time.perf_counter() - started) * 1000, 1))
    return response
```

**中间件是什么？** 每个请求都会经过的一道关卡。
类比：进出小区都要过的大门保安。

**它解决什么问题？** 用户报错时截图给你，你怎么找到对应的日志？
现在响应头里有 `X-Request-ID`，你在日志里搜这个编号，**那一次请求的完整链路全出来了**。

**看什么**：随便发个请求，在浏览器 F12 的 Network 里看响应头，能看到 `x-request-id`。

**两个细节**：
- `call_next(request)` 是"放行"——让它继续往下走
- 这里的 `try/except` 是**第二道兜底**（第一道是第 5 步的 `@app.exception_handler(Exception)`）

---

## 第 8 步 · 加 CORS（不然前端连不上）

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOW_ORIGINS,      # http://localhost:5173
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],         # ← 让浏览器里的 JS 能读到这个头
)
```

**为什么必须加？** 前端跑在 `5173`，后端跑在 `8000`，**端口不同 = 跨域**，
浏览器默认拦截。不加这个，前端所有请求全失败。

**新手排查技巧**：这种情况**后端日志里什么都没有**（请求根本没发出），
错误在**浏览器控制台**。别在后端找。

**为什么 `expose_headers`？** 浏览器默认只让 JS 读几个标准响应头，
自定义头（比如 `X-Request-ID`）必须显式暴露。

---

## 第 9 步 · 补齐普通路由（路径参数 / 查询参数）

```python
# 查询参数：写在函数参数里，带默认值
@app.get("/api/kb/list", tags=["kb"], summary="知识库文档列表（分页 + 搜索）")
async def kb_list(page: int = 1, size: int = 10, q: str = "") -> dict:
    status, body = await run_in_threadpool(api.handle_kb_list, {"page": page, "size": size, "q": q})
    return JSONResponse(status_code=status, content=body)


# 路径参数：用 {} 写在 URL 里
@app.delete("/api/kb/{source}", tags=["kb"], summary="按来源删除文档（同时清理检索索引）",
            responses={404: {"description": "来源不存在(40400)"}})
async def kb_delete(source: str) -> dict:
    status, body = await run_in_threadpool(api.handle_kb_delete, source)
    return JSONResponse(status_code=status, content=body)
```

**要理解的区别**：

| 类型 | 写法 | 例子 | 什么时候用 |
|---|---|---|---|
| 查询参数 | `page: int = 1` | `/api/kb/list?page=2` | 筛选、分页（可省略） |
| 路径参数 | 路由里写 `{source}` | `/api/kb/尺码推荐.txt` | 定位某个资源（不能省略） |
| 请求体 | `payload: ChatRequest` | JSON body | 数据多、结构复杂 |

**关键点**：`page: int = 1` 里的 `int` **不是装饰**。
前端传 `?page=abc`，FastAPI 自动返回 400 并且**不会调用你的函数**。

---

## 第 10 步 · 文件上传（这里有个设计取舍要理解）

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

**注意这里有个反常的地方**：FastAPI 明明提供了 `UploadFile`，为什么项目没用？

```python
# FastAPI 的写法（这个项目故意没用）
from fastapi import UploadFile, File
async def upload(file: UploadFile = File(...)): ...
```

**因为 `UploadFile` 需要额外安装 `python-multipart`**，
而这个项目要保证"**零依赖也能跑**"（`python run.py` 起来的是 stdlib 服务器）。

所以项目自己写了 `app/multipart.py`（115 行），两个入口共用。

**这是新手最该学的一课**：**框架给你的东西不一定都要用。**
"用框架现成的最省事"和"少一个依赖"之间，是有取舍的。
`multipart.py` 开头那几行注释就写着这个理由。

**这也是"设计"和"抄教程"的区别**——抄教程的人不会想这个问题。

---

## 第 11 步 · SSE 流式输出（最坑的一步）

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

**为什么需要它？** 聊天要"打字机效果"——一个字一个字蹦出来，不是等 5 秒一起出现。

**SSE 的格式很简单**：每条消息就是 `data: {JSON}` 加两个换行。就这样。

**新手最大的坑（这个项目现在就踩了）**：

`events` 是个**生成器**。`run_in_threadpool(api.handle_chat_stream, ...)`
**只是拿到生成器就返回了**，真正的模型调用发生在 `for evt in events` 迭代时——
那时已经回到事件循环线程了。**线程池那一层等于没生效。**

原因：**Python 生成器函数被调用时不执行函数体**，只返回一个生成器对象。
这是新手理解生成器最常见的误区。

正确做法是 `starlette.concurrency.iterate_in_threadpool(events)`，
或者干脆把路由写成同步的 `def`，让 FastAPI 自己处理。

**两个额外细节**：
- `X-Accel-Buffering: no` — 告诉 nginx 别缓冲，否则前端收不到逐段输出
- nginx 那边也要配 `proxy_buffering off`（在 `frontend/nginx.conf`）

---

## 第 12 步 · 补齐剩下的路由，收工

到这里你已经会了所有需要用到的写法，剩下的就是重复劳动：

| tag | 路由 | 用到的新知识 |
|---|---|---|
| ops | `GET /`、`GET /health`、`GET /api/stats` | 最简单 |
| chat | `POST /api/chat`、`POST /api/chat/plan`、`POST /api/chat/stream`、`GET /api/context/{session_id}` | 请求体 / 流式 / 路径参数 |
| kb | `POST /api/kb/ingest`、`POST /api/kb/upload`、`GET /api/kb/list`、`DELETE /api/kb/{source}` | 查询参数 / multipart |
| feedback | `POST /api/feedback`、`GET /api/feedback` | 请求体 / 查询参数 |

**13 条路由，四种标签，全套写完，就是现在的 `main.py`（197 行）。**

---

## 复盘：这张表是全文最该记住的

| 步 | 加了什么 | 学到的概念 | 对应 `main.py` |
|---|---|---|---|
| 0 | hello world | 路由装饰器、`uvicorn 模块:变量` | `fastapi-practice/hello.py` |
| 1 | 应用信息 | `/docs` 是代码生成的 | `FastAPI(...)` 那一段 |
| 2 | 假 `/health` | 先跑通再填内容 | — |
| 3 | 连业务 | **`api.py` 接线、`run_in_threadpool`** | `/health` 路由 |
| 4 | 请求模型 | **pydantic 自动校验** | `ChatRequest` |
| 5 | 三个异常处理器 | **统一错误格式** | `@app.exception_handler` ×3 |
| 6 | 真 `chat` | `model_dump()`、**别丢 status** | `/api/chat` 路由 |
| 7 | 中间件 | **request_id 贯穿** | `@app.middleware("http")` |
| 8 | CORS | 跨域、`expose_headers` | `add_middleware(CORSMiddleware)` |
| 9 | 普通路由 | 查询参数 vs 路径参数 | `/api/kb/list`、`/api/kb/{source}` |
| 10 | 文件上传 | **设计取舍：不用 `UploadFile`** | `/api/kb/upload` + `multipart.py` |
| 11 | SSE 流式 | **生成器陷阱** | `/api/chat/stream` |
| 12 | 补全 13 条 | 重复劳动 | 全文 |

### 三条最该带走的规律

**① 顺序是有道理的**：每一步都依赖前一步。
先能跑 → 再接业务 → 再补契约/错误/横切 → 最后处理特殊需求（上传、流式）。
**不要跳步。** 尤其不要在第 3 步之前就写 `/api/chat`。

**② 最难的不是语法，是"接线"**：
路由装饰器、pydantic、中间件——这些都是查文档就会的。
真正需要设计的是：**业务逻辑放哪、谁来组装、依赖怎么传**。
这就是为什么项目里 `main.py` 只有 197 行，而 `api.py` / `chat_service.py` / `errors.py`
这些"为了让它能接进来"的文件加起来更多。

**③ 每一步都要能跑**：
这是新手和专业开发最大的区别。不是"写三天一起跑"，而是"半小时后就能跑，然后一直保持能跑"。

---

## 现在回到真实的 main.py

打开 `backend/app/main.py` 从头读一遍。你会发现：

- `FastAPI(title=..., openapi_tags=[...])` → 第 1 步
- `@app.middleware("http")` → 第 7 步
- 三个 `exception_handler` → 第 5 步
- `/health`、`/api/chat`、`/api/chat/stream`、`/api/kb/*`…… → 第 2~12 步
- `add_middleware(CORSMiddleware, ...)` → 第 8 步

**197 行，一行都不陌生了。** 这就是你该追求的状态。

---

## 附：照着练的完整命令

```bash
# 从第 0 步开始
cd backend/fastapi-practice
uvicorn hello:app --reload
# 浏览器开 http://localhost:8000/docs

# 后面的步骤，建议在 backend/app/ 下新建一个 main_practice.py
cd backend
uvicorn app.main_practice:app --reload

# 走完全程后，对照真实实现
uvicorn app.main:app --reload
```

**练的时候故意改坏它**，看报什么错：
- 删掉 `await` → 看报什么
- 删掉 `run_in_threadpool` 直接调用 → 感受差别
- 把 `session_id` 从 `ChatRequest` 里删掉不设默认值 → 看 `/docs` 的 Try it out 怎么变
- 把 `JSONResponse(status_code=status, ...)` 改成 `return body` → 观察响应状态码

**踩过一遍的错，才是你的。** 看十遍文档不如踩一次坑。
