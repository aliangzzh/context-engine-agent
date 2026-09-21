# FastAPI 从 0 到 1 跟练手册

> **怎么用这份手册**：打开 `backend/`，从 Lab 1 开始，**照着敲、照着跑**。
> 每个 Lab 都是四段：**做什么 → 应该看到什么 → 不对怎么查 → 记住这一句**。
>
> 全程 8 个 Lab，大约 1.5~2 小时。做完你会有一个**能跑通完整链路**的接口文件，
> 而且它和项目里真实的 `app/main.py` 是同一套写法。
>
> 所有"应该看到"的输出都是**真跑出来复制过来的**，不是我编的。

---

# Lab 0 · 开始之前（10 分钟）

## 0.1 确认环境

```powershell
cd F:\shujuf\code\context-engine-agent\backend
python --version
python -c "import fastapi, uvicorn, pydantic; print(fastapi.__version__, uvicorn.__version__, pydantic.VERSION)"
```

**应该看到**（我这里的真实输出）：
```
Python 3.12.7
0.141.1 0.52.4 2.12.5
```

> 版本号不需要一样，只要都能 import 成功就行。
> 如果报 `ModuleNotFoundError`，先在 `.venv` 里装：`pip install fastapi uvicorn`

## 0.2 你会建哪个文件

**只在 `backend/app/` 下建一个练习文件：`main_lab.py`**。

为什么必须放在 `app/` 里？因为从 Lab 3 开始要用 `from . import api` 这种**相对导入**，
它要求文件必须在一个"包"里面。

**不要动项目原有的任何文件。** 练习完直接删掉 `main_lab.py` 就行。

## 0.3 怎么启动、怎么停

**启动**（在 `backend/` 目录下）：
```powershell
uvicorn app.main_lab:app --host 127.0.0.1 --port 8070
```

看到这两行就成功了：
```
INFO:     Uvicorn running on http://127.0.0.1:8070 (Press CTRL+C to quit)
INFO:     Application startup complete.
```

**停**：在同一个窗口按 `Ctrl + C`。

> **改完代码要重启**：`Ctrl + C` 停掉，再按 ↑ 方向键调出上一条命令回车。
> （`--reload` 能自动重启，但它依赖命名管道，某些受限环境会失败——**手动重启永远可行**，
> 新手先用这个。）

**浏览器打开**：`http://127.0.0.1:8070/docs` —— 这是你的操作台，每个 Lab 都会用到。

## 0.4 ⚠️ 一个会让你浪费一小时的坑：PowerShell 里 curl 传 JSON

Windows PowerShell 会把参数里的**双引号吃掉**，导致 curl 收到坏 JSON。
我实测了四种写法：

| 写法 | 命令 | 结果 |
|---|---|---|
| A | `--data-binary '{"message":"hi"}'` | ❌ `{"code":40001,...,"msg":"JSON decode error"}` |
| B | `--data-binary "{\"message\":\"hi\"}"` | ❌ 同样失败 |
| C | `--data-binary '{\"message\":\"hi\"}'` | ✅ **成功** |
| D | `--data-binary "@body.json"`（写文件） | ✅ **成功** |

**结论：在 PowerShell 里用 `curl.exe`，双引号必须反斜杠转义，外层用单引号。**

```powershell
# ✅ 正确写法（中文也没问题，我实测过）
curl.exe -X POST "http://127.0.0.1:8070/api/chat" `
  -H "Content-Type: application/json" `
  --data-binary '{\"message\":\"加绒牛仔怎么洗\",\"session_id\":\"s1\"}'
```

> **更省心的办法**：Lab 1~7 全部用 `/docs` 页面点按钮测试，**完全避开命令行转义**。
> 只在 Lab 8（SSE 流式）才必须用命令行。

---

# Lab 1 · 建空壳，让 `/docs` 能打开（10 分钟）

## 🎯 目标

**只要一个能跑的服务。故意什么业务都不接。**

## 📝 做什么

**步骤 1**：新建 `backend/app/main_lab.py`，敲入：

```python
"""Lab 1：最小空壳。目标只有一个：让 /docs 能打开。"""
from fastapi import FastAPI

app = FastAPI(title="接线练习")


@app.get("/hello")
async def hello() -> dict:
    return {"msg": "hello fastapi"}
```

**步骤 2**：启动
```powershell
uvicorn app.main_lab:app --host 127.0.0.1 --port 8070
```

**步骤 3**：浏览器打开 `http://127.0.0.1:8070/docs`

## ✅ 应该看到

浏览器里是一个标题为"接线练习"的页面，下面列着一个 `/hello` 接口。
点开 `/hello` → 点 **Try it out** → 点 **Execute**：

```json
{"msg": "hello fastapi"}
```

命令行验证（顺便看一个"接口不存在"长什么样）：
```powershell
curl.exe http://127.0.0.1:8070/health
```
**应该看到**：
```
{"detail":"Not Found"}
```
（HTTP 404）

## ❌ 不对就查

| 现象 | 原因 |
|---|---|
| `No module named 'app'` | 你不在 `backend/` 目录下 |
| `Error loading ASGI app. Import string "app.main_lab" must be in format "<module>:<attribute>"` | 少写了 `:app` |
| 浏览器打不开 `/docs` | 端口被占用，换个端口（8071、8072…） |
| `Address already in use` | 上一次的服务没停干净，换端口或找到进程杀掉 |

## 💡 记住这一句

> **先要一个确定能跑的地基。** 这一步看着没用，但它是后面所有事的参照系——
> 出了问题你才能确定"不是我环境坏了"。

---

# Lab 2 · 加一个假的 `/health`（10 分钟）

## 🎯 目标

**先让一个真接口通，内容先写死。** 把"写接口"和"接线"两件陌生的事拆开。

## 📝 做什么

把 `main_lab.py` 改成：

```python
"""Lab 2：加一个假的 /health。先让一个真接口通，内容先写死。"""
from fastapi import FastAPI

app = FastAPI(title="接线练习")


@app.get("/hello")
async def hello() -> dict:
    return {"msg": "hello fastapi"}


@app.get("/health", tags=["ops"], summary="健康检查")
async def health() -> dict:
    return {"code": 0, "msg": "ok", "data": {"status": "ok"}}
```

`Ctrl + C` 停掉，再启动一次。浏览器刷新 `/docs`。

## ✅ 应该看到

**① `/docs` 变了**：多了一个 `ops` 分组，下面有"健康检查"。

**② 命令行**：
```powershell
curl.exe http://127.0.0.1:8070/health
```
```
{"code":0,"msg":"ok","data":{"status":"ok"}}
```

**③ 对比 Lab 1**：同一个 URL，从 `404` 变成了 `200`。

## ❌ 不对就查

| 现象 | 原因 |
|---|---|
| 还是 404 | 没重启服务（改完 Python 必须重启） |
| `/docs` 里没有 ops 分组 | `tags=["ops"]` 拼错，或没重启 |

## 💡 记住这一句

> **`{"code":0,"msg":"ok","data":...}` 这个形状不是随口写的**，
> 它是整个项目的约定（真实项目里写死在 `app/errors.py` 的 `ok()` 函数里）。
> **先定形状，再填内容**——这是新手最该养成的习惯。

---

# Lab 3 · 换成真业务（第一次"接线"）★重点（20 分钟）

## 🎯 目标

**把假数据换成项目里真实的业务函数。** 这一步是整个项目的灵魂。

## 📝 做什么

**步骤 1**：先把项目里要被调用的那个函数看一眼——`backend/app/api.py`：

```python
def handle_health() -> tuple[int, dict]:
    return 200, ok(services().health().model_dump())


def services() -> AppServices:
    global _services
    if _services is None:
        _services = AppServices(seed_kb=True)
    return _services
```

**看懂两件事**：
- `handle_health` 返回**两个值**：`(状态码, 响应体)`
- 它内部调了 `services()`，`services()` 会创建一个叫 `AppServices` 的大对象

**步骤 2**：把 `main_lab.py` 改成：

```python
"""Lab 3：把假数据换成真业务 —— 第一次"接线"。"""
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

**步骤 3**：重启，然后：
```powershell
curl.exe http://127.0.0.1:8070/health
```

## ✅ 应该看到

```json
{"code":0,"msg":"ok","data":{"status":"ok","chat_backend":"fake",
 "retrieval_backend":"bm25","model":"fake","db_backend":"sqlite","cache_backend":"lru"}}
```

**注意多了四个字段**：`chat_backend`、`retrieval_backend`、`db_backend`、`cache_backend`。

**③ 顺手看一眼它到底连了多少东西**（这一步很关键）：
打开 `backend/app/services/chat_service.py`，看 `AppServices.__init__` 那十行——
`get_retriever()`、`get_model_backend()`、`ChatStore(...)`、`ContextEngine(...)`……
**全部都是在你调 `api.handle_health()` 的那一刻被自动创建并连接起来的。**

## ❌ 不对就查

| 现象 | 真实报错 | 原因 |
|---|---|---|
| `ModuleNotFoundError: No module named 'api'` | `import api` | 必须写 `from . import api`（那个点不能少） |
| `ModuleNotFoundError: No module named 'app'` | —— | 不在 `backend/` 目录下启动 |
| `attempted relative import with no known parent package` | —— | 用 `python app/main_lab.py` 启动了，要用 `uvicorn app.main_lab:app` |

我实测的错误原文：
```
File "...\app\main_wrong.py", line 2, in <module>
    import api
ModuleNotFoundError: No module named 'api'
```

## 💡 记住这一句

> **"接线"不是你去 new 一堆东西，而是找到那个已经组装好的入口，调它。**
> 你只写了 3 行，却连上了配置、存储、检索、模型四层。

---

# Lab 4 · 加 `POST /api/chat`，但只做校验（15 分钟）

## 🎯 目标

**验证参数校验能工作，先不接业务。** 把"校验"和"业务"分开验证，出错才好定位。

## 📝 做什么

**步骤 1**：看项目里现成的请求模型，`backend/app/schemas.py`：

```python
class ChatRequest(BaseModel):
    message: str = Field(..., description="The user's question")
    session_id: str = Field(default="default", description="Conversation id")
    stream: bool = Field(default=True, description="Stream tokens when True")
```

**读懂三个符号**：
- `Field(...)` 里三个点 = **必填**
- `Field(default="default")` = 有默认值，可以不传
- `description=` 会显示在 `/docs` 里

**步骤 2**：在 `main_lab.py` 末尾追加：

```python
from .schemas import ChatRequest


@app.post("/api/chat", tags=["chat"], summary="一次性返回完整回答（先只做校验）")
async def chat(payload: ChatRequest) -> dict:
    return {"code": 0, "msg": "ok", "data": {"echo": payload.model_dump()}}
```

（把 `from .schemas import ChatRequest` 挪到文件顶部和其它 import 放一起更规范）

**步骤 3**：重启。在 `/docs` 里找到 `POST /api/chat`：

1. 点 **Try it out**
2. 会看到一个**自动生成的** JSON 请求体示例（**这就是 pydantic 的功劳**）
3. 填 `{"message": "加绒牛仔怎么洗", "session_id": "s1"}` → **Execute**

然后再试一次：**把 `message` 那一行删掉**，再 Execute。

## ✅ 应该看到

**正常请求**：
```json
{"code":0,"msg":"ok","data":{"echo":{"message":"加绒牛仔怎么洗","session_id":"s1","stream":true}}}
```
注意 `stream:true` —— **你没传，它自动补的默认值**。

**少字段的请求**：
```
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"type":"missing","loc":["body","message"],"msg":"Field required","input":{"session_id":"s1"}}]}
```

**⚠️ 记住这个 422 和这个格式，下一步就要改掉它。**

## ❌ 不对就查

| 现象 | 原因 |
|---|---|
| `/docs` 里请求体是空的 | 重启了吗 |
| 提示 `Field required` 但你以为传了 | 检查 JSON 有没有多余逗号、引号是不是半角 |

## 💡 记住这一句

> **你一行校验代码都没写**，FastAPI 靠函数签名上的 `ChatRequest` 就全干了。
> **参数写在函数签名里，不在函数体里取**——这是 FastAPI 最核心的写法。
>
> 但它的**默认错误格式跟你项目约定不一样**，所以有 Lab 5。

---

# Lab 5 · 统一错误格式 ★最值钱（20 分钟）

## 🎯 目标

把刚才那个野生的 `422 + {"detail":[...]}`，改成项目约定的 `400 + {code,msg,data}`。

## 📝 做什么

**步骤 1**：看一眼项目的错误码，`backend/app/errors.py`：

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

**规律**：`40xxx` 是调用方的问题，`50xxx` 是服务端的问题，`502xx` 是上游（模型）的问题。

**步骤 2**：在 `main_lab.py` 里加三个异常处理器：

```python
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .errors import AppError, ErrorCode, fail
from .logging_config import get_logger, log, setup_logging

logger = get_logger("lab.http")


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

**步骤 3**：重启，**再发一次刚才那个"少字段"的请求**（和 Lab 4 一模一样的请求）。

## ✅ 应该看到

**Lab 4（加处理器之前）：**
```
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"type":"missing","loc":["body","message"],"msg":"Field required","input":{"session_id":"s1"}}]}
```

**Lab 5（加处理器之后），同一个请求：**
```
HTTP/1.1 400 Bad Request
{"code":40001,"msg":"参数校验失败","data":null,"detail":[{"field":"body.message","msg":"Field required"}]}
```

**四处变化，每处都有用：**

| 变化 | 从 | 到 | 为什么重要 |
|---|---|---|---|
| 状态码 | 422 | **400** | 你们约定校验失败就是 400 |
| 外层格式 | `{detail:[...]}` | **`{code,msg,data}`** | **前端只写一套解析** |
| 错误码 | 无 | **40001** | 前端按 code 分支，不靠字符串匹配 message |
| 字段路径 | `loc:["body","message"]` | **`field:"body.message"`** | 前端能直接拿去表单回填 |

## ❌ 不对就查

| 现象 | 原因 |
|---|---|
| 还是 422 | 处理器函数名或装饰器写错；看服务启动时有没有报错 |
| 报 `ImportError: cannot import name 'fail'` | `errors.py` 里确实有 `ok`/`fail`，检查拼写 |

## 💡 记住这一句

> **这一步最容易漏，因为它不影响"功能正常"。**
> 接口能通、数据能返回，新手就觉得完事了。
> 但不做这步，前端要写两套错误解析——**这就是"能跑"和"能用"的区别。**
>
> 为什么要三个处理器？因为错误有三个来源：
> 业务自己抛的（`AppError`）、参数校验失败（`RequestValidationError`）、想不到的 bug（`Exception`）。

---

# Lab 6 · 加 request_id 中间件 + CORS（20 分钟）

## 🎯 目标

让**每个请求**都有编号和日志，并且允许前端跨域访问。

## 📝 做什么

**步骤 1**：加中间件。在 `main_lab.py` 顶部补 `import time`，然后加：

```python
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

**步骤 2**：重启。发几个请求：
```powershell
curl.exe -i http://127.0.0.1:8070/health
```

## ✅ 应该看到

**① 响应头里多了一行**（我这里的真实输出）：
```
HTTP/1.1 200 OK
content-type: application/json
x-request-id: b4e88610c138
```

**② 服务端日志**（启动的那个窗口）：

**Lab 1~5 时**：什么都没有。
**Lab 6 开始**：
```
2026-09-18 16:10:09 INFO  practice.http          rid=b4e88610c138 http method=GET path=/health status=200 ms=3.4
2026-09-18 16:10:09 INFO  practice.http          rid=a6f400fa4082 http method=POST path=/api/chat status=200 ms=0.7
2026-09-18 16:10:09 INFO  practice.http          rid=22b4d822141d http method=POST path=/api/chat status=400 ms=0.5
```

## ❌ 不对就查

| 现象 | 原因 |
|---|---|
| 响应头没有 `x-request-id` | 中间件加在 `app = FastAPI()` **之前**了，顺序错了 |
| 日志里没有 `rid=` | 没重启；或者 `setup_logging()` 没调用 |
| 浏览器前端报 CORS 错 | `config.ALLOW_ORIGINS` 里没有前端的地址 |

## 💡 记住这一句

> **中间件 = 每个请求都过的关卡**（类比：小区大门保安）。
> 写一次，**13 个接口全都自动有了**，不用写 13 遍。
>
> **排查链路**：用户截图报错 → 看响应头 `x-request-id` → 日志里搜这个编号
> → 那次请求经过的**所有层**全出来。
>
> 为什么用 `contextvars` 而不是全局变量存 id？因为线程池会换线程，
> 全局变量并发时会串号。

---

# Lab 7 · 真正接上业务（15 分钟）

## 🎯 目标

把 echo 换成真的业务调用。

## 📝 做什么

**步骤 1**：把 `chat` 路由改成：

```python
from starlette.concurrency import run_in_threadpool


@app.post("/api/chat", tags=["chat"], summary="一次性返回完整回答")
async def chat(payload: ChatRequest) -> dict:
    status, body = await run_in_threadpool(api.handle_chat, payload.model_dump())
    return JSONResponse(status_code=status, content=body)
```

**步骤 2**：重启，用 `/docs` 或命令行发：
```powershell
curl.exe -X POST "http://127.0.0.1:8070/api/chat" -H "Content-Type: application/json" --data-binary '{\"message\":\"加绒牛仔怎么洗\",\"session_id\":\"s1\"}'
```

## ✅ 应该看到

```json
{"code":0,"msg":"ok","data":{
  "answer":"【离线演示】根据检索到的资料：[洗涤养护.txt] 加绒牛仔：水温≤30℃，中性洗涤剂，翻面清洗，机洗选轻柔模式，避免长时间浸泡。收纳时折叠平放，避免重压破坏绒层。纯棉保（问题：加绒牛仔怎么洗）",
  "session_id":"s1",
  "context":{
    "slots":[
      {"kind":"system","priority":100,"tokens":64},
      {"kind":"retrieval","priority":110,"tokens":157},
      {"kind":"retrieval","priority":44,"tokens":74}
    ],
    "total_tokens":295,"budget":4096,"trimmed":0,"over_budget":false},
  "backend":"fake", "tokens_requested":295, "tokens_generated":97, "elapsed_ms":7}}
```

**② 看服务端日志的耗时变化**（真实数据）：
```
Lab 6: rid=... path=/api/chat status=200 ms=0.7     ← echo，几乎不耗时
Lab 7: rid=... path=/api/chat status=200 ms=10.4    ← 真业务：读库 + 检索 + 调模型
```

**这 0.7ms → 10.4ms 就是"接上真业务"的量化证据。**

**③ 重点看 `context.slots`**（这是整个项目最值钱的地方）：

| slot | priority | 含义 |
|---|---|---|
| system | 100 | 系统指令，**永不参与裁剪** |
| retrieval | 110 / 44 | 检索到的资料，**优先级按相关度给** |
| history | 25 | 对话历史，**优先级最低 → 预算不够时第一个被裁** |

## ❌ 不对就查

| 现象 | 原因 |
|---|---|
| `TypeError: handle_chat() argument ...` | 忘了 `payload.model_dump()` |
| 服务卡住/其他请求排队 | 忘了 `run_in_threadpool`（**这是最严重的错**） |
| 返回 500 | 看服务端日志的 `rid=` 那一行 |

## 💡 记住这一句（三个必须懂的点）

**① `payload.model_dump()` 为什么要加**
`payload` 是 pydantic 对象，而 `api.handle_chat` 是**框架无关**的普通函数，
它不认识 pydantic。所以转成普通 dict 再传。**这就是"防腐层"的成本。**

**② `run_in_threadpool` 为什么要加**
从这一步开始，代码要读库、检索、调模型——**全是阻塞操作**。
直接写在 `async def` 里会**卡死整个服务**：不是变慢，是其他请求全部排队。
原理：IO 等待时让出事件循环；CPU 密集的活仍受 GIL 限制，所以线程池是对的方向。

**③ 为什么不用 `return body`**
`handle_chat` 返回 `(状态码, 响应体)` 两个值。
**写成 `return body` 就把状态码丢了。**
（项目现在的 `main.py` 里就有这个隐患：`/health`、`/api/chat` 等几条路由丢了 status，
而 `/api/kb/list` 那几条却规规矩矩用了 `JSONResponse(status_code=status, ...)`。
今天不炸是因为它们恒返回 200。）

---

# Lab 8 · SSE 流式（20 分钟）

## 🎯 目标

让回答**一个字一个字往外蹦**（打字机效果）。

## 📝 做什么

**步骤 1**：顶部加 `import json`，把 `StreamingResponse` 加进 import：

```python
from fastapi.responses import JSONResponse, StreamingResponse
```

**步骤 2**：追加一条路由：

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

**步骤 3**：重启。**这一步必须用命令行**（`/docs` 看不出流式效果）：

```powershell
curl.exe -N -X POST "http://127.0.0.1:8070/api/chat/stream" -H "Content-Type: application/json" --data-binary '{\"message\":\"加绒牛仔怎么洗\",\"session_id\":\"s1\"}'
```

（`-N` 关掉 curl 自己的缓冲，不加的话你会看到"一次性全出来"）

## ✅ 应该看到

**一条一条往下打**（真实输出，共 21 个事件）：

```
data: {"type": "agent", "data": {"node": "router", "kind": "router", "summary": "路由判定", "detail": {"plan": ["retrieve"], ...}}}

data: {"type": "agent", "data": {"node": "retrieve", "kind": "retrieve", "summary": "检索到 2 条知识", "detail": {"docs": [...]}}}

data: {"type": "retrieved", "data": [{"text": "加绒牛仔：水温≤30℃...", "score": 5.7095, "source": "洗涤养护.txt"}, ...]}

data: {"type": "token", "data": "【离线演示】"}

data: {"type": "token", "data": "根据检索到的"}

data: {"type": "token", "data": "资料：[洗涤"}

...（共 17 个 token 事件）

data: {"type": "done", "data": {"answer": "...", "context": {...}, "trace": [...], "used_tools": [], "backend": "fake"}}
```

**四种事件的分工（这就是前后端契约）：**

| 事件 | 前端拿来渲染什么 |
|---|---|
| `agent` | "Agent 协作链"面板 |
| `retrieved` | 命中的知识卡片（带 score） |
| `token` | **打字机效果** |
| `done` | 收尾：拿 context / trace / 完整答案 |

**SSE 格式其实很简单**：每条消息就是 `data: {JSON}` 加**两个换行**。就这样。

## ❌ 不对就查

| 现象 | 原因 |
|---|---|
| 一次性全出来，没有逐条 | 忘了 `-N`；或者本地没问题、上线后被 nginx 缓冲了 |
| 报 `'async for' requires ...` | 别用 `for` 迭代异步生成器（这个例子里 events 是同步生成器，`for` 是对的） |
| 中文变乱码 | 命令行的双引号没转义，回去看 Lab 0.4 |

## 💡 记住这一句（这里有个真实的坑）

```python
status, events = await run_in_threadpool(api.handle_chat_stream, payload.model_dump())
```

**`events` 是个生成器。这行只是"拿到生成器就返回了"，函数体一行都没执行。**
真正的模型调用发生在 `for evt in events` 迭代的时候——**那时已经在事件循环线程里了**，
线程池那一层**等于没生效**。

**根源**：Python 生成器函数**被调用时不执行函数体**，只返回一个生成器对象。
这是新手理解生成器最常见的误区。

**为什么这次看不出来？** 因为 `fake` 模型是瞬时的。
换成 `qwen_api`（真实网络调用）并发一上来就会堵住事件循环。

**正确做法**（以后要改）：
```python
from starlette.concurrency import iterate_in_threadpool

async def gen():
    async for evt in iterate_in_threadpool(events):
        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
```

---

# 毕业 · 对照真实的 `main.py`

现在打开 `backend/app/main.py` 从头读一遍，你会发现**每一段你都写过**：

| 你写的 Lab | `main.py` 里的对应位置 |
|---|---|
| Lab 1 的 `FastAPI(title=...)` | 第 34~48 行（多了 `version`、`description`、`openapi_tags`） |
| Lab 6 的中间件 | `@app.middleware("http")` |
| Lab 5 的三个处理器 | `@app.exception_handler(...)` ×3 |
| Lab 4 的请求模型 | `ChatRequest` / `FeedbackRequest` |
| Lab 3 的 `/health` | `health()` 路由 |
| Lab 7 的 `chat` | `chat()` 路由 |
| Lab 8 的 `chat_stream` | `chat_stream()` 路由 |

**197 行，一行都不陌生了。**

## 然后给自己出三道题

1. **把 `/api/chat` 的 `return JSONResponse(status_code=status, ...)` 改成 `return body`**，
   然后用一个会返回非 200 的分支触发它，看响应状态码变成什么。
2. **把 Lab 7 的 `run_in_threadpool` 去掉**，起服务后同时发两个请求，
   看第二个请求要等多久。（能直观感受到"阻塞事件循环"）
3. **给 `ChatRequest` 加一个必填字段** `user_id: str`，
   重启后看 `/docs` 里的请求体示例怎么变、不传会怎样。

---

# 附录 A · 命令速查

```powershell
# 进目录
cd F:\shujuf\code\context-engine-agent\backend

# 启动（换端口避免冲突）
uvicorn app.main_lab:app --host 127.0.0.1 --port 8070

# 健康检查
curl.exe http://127.0.0.1:8070/health

# POST（PowerShell 里双引号必须反斜杠转义）
curl.exe -X POST "http://127.0.0.1:8070/api/chat" `
  -H "Content-Type: application/json" `
  --data-binary '{\"message\":\"加绒牛仔怎么洗\",\"session_id\":\"s1\"}'

# 看响应头（找 x-request-id）
curl.exe -i http://127.0.0.1:8070/health

# SSE 流式（-N 必须加）
curl.exe -N -X POST "http://127.0.0.1:8070/api/chat/stream" `
  -H "Content-Type: application/json" `
  --data-binary '{\"message\":\"加绒牛仔怎么洗\",\"session_id\":\"s1\"}'

# 浏览器
# http://127.0.0.1:8070/docs
```

# 附录 B · 报错速查表

| 报错 / 现象 | 真正的原因 | 怎么改 |
|---|---|---|
| `No module named 'app'` | 不在 `backend/` 目录下 | `cd backend` 再启动 |
| `No module named 'api'` | 用了 `import api` | 改成 `from . import api` |
| `attempted relative import with no known parent package` | 用 `python app/main_lab.py` 启动 | 改用 `uvicorn app.main_lab:app` |
| `Import string "app.main_lab" must be in format "<module>:<attribute>"` | 少写 `:app` | `uvicorn app.main_lab:app` |
| `Address already in use` | 端口被占 | 换端口 8071/8072 |
| 改了代码没生效 | 没重启 | `Ctrl+C` 再启动 |
| `{"code":40001,...,"msg":"JSON decode error"}` | PowerShell 吃掉了双引号 | 双引号写成 `\"`，或用 `/docs` |
| 校验失败返回 422 而不是 400 | Lab 5 的处理器没加 | 回去做 Lab 5 |
| 响应头没有 `x-request-id` | 中间件加在 `app = FastAPI()` 之前 | 中间件必须在 app 创建之后 |
| 前端一个请求都发不出，后端日志干净 | CORS | 去浏览器控制台看，不是后端问题 |

# 附录 C · 收尾清理

```powershell
Remove-Item F:\shujuf\code\context-engine-agent\backend\app\main_lab.py
```

练习文件删掉即可，**项目原有文件全程没动过**。

---

# 最后的最后：整个流程压成四句话

1. **顺序**：能跑 → 接线 → 契约 → 错误 → 横切 → 特殊需求。
   **顺序错了就返工**（比如先做 SSE 再补错误格式，所有流式接口都要回头改）。
2. **每步都起服务打一次**。不是"写三天一起跑"，是"写十行就跑一次"。
3. **接线的本质是找到已经组装好的入口**（`api.handle_*` → `services()`），
   而不是自己去 new 一堆东西。
4. **能跑 ≠ 能用**。状态码、错误格式、日志、跨域，这些"不影响功能"的东西
   才决定它是不是一个能交付的接口。
