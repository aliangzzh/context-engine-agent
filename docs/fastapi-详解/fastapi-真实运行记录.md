# FastAPI 真实运行记录（结合本项目代码跑一遍）

> 这份不是推演，是**真的跑起来的结果**。
>
> 环境：Python 3.12.7 / FastAPI 0.141.1 / uvicorn 0.52.4 / pydantic 2.12.5
> 命令：`cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8010`
>
> 下面每一条响应都是服务真实返回的原文（中文未做任何修改）。

---

# 第一部分 · 先大概讲干了什么

一句话：**把"收信、校验、回信"这三件烦事交给 FastAPI，自己只写业务。**

整个过程分三层，很多新手只知道第一层：

```
第一层：装框架      pip install fastapi uvicorn          ← 谁都会
第二层：挂路由      @app.post("/api/chat")               ← 查文档就会
第三层：接线        让路由能拿到项目的检索/模型/数据库     ← 真正的难点
```

这次实际做的事，就是**从 0 到 13 条路由**，并按这个顺序：

```
① 建空壳（能跑）
      ↓
② 接第一条路由 /health（第一次接线）
      ↓
③ 接 /api/chat（完整业务链路）
      ↓
④ 补契约（ChatRequest 校验）
      ↓
⑤ 补错误（三个异常处理器 → 统一 {code,msg,data}）
      ↓
⑥ 补横切（request_id 中间件 + CORS）
      ↓
⑦ 特殊需求（文件上传 multipart / SSE 流式）
      ↓
⑧ 补齐 13 条路由 + 部署
```

**跑完之后验证了 8 件事**（下面逐个展示）：

| # | 验证什么 | 结果 |
|---|---|---|
| 1 | 接线是否成功 | ✅ `/health` 返回了真实后端信息 |
| 2 | 文档是否自动生成 | ✅ 12 条路径、4 个分组 |
| 3 | 路由 + Agent 计划 | ✅ 返回 `["retrieve", "writer"]` |
| 4 | 完整业务链路 | ✅ 检索 + 上下文引擎 + 模型全跑通 |
| 5 | 参数校验 | ✅ 400 / 40001 |
| 6 | 类型校验 | ✅ 400 / 40001（query.page） |
| 7 | 业务错误码 | ✅ 404 / 40400 |
| 8 | SSE 流式 | ✅ 逐条 `data:` 事件 |

---

# 第二部分 · 为什么要这样

## 为什么需要 FastAPI（4 个真实痛点）

| 痛点 | 手动写 `server.py` 时 | FastAPI |
|---|---|---|
| 越写越长 | 每加接口就在 `do_POST` 里加一个 `if` | 一个接口 = 一个函数 + 一行装饰器 |
| 没说明书 | 前端只能翻 Python 代码猜字段 | `/docs` 自动生成 |
| 参数错了才发现 | 跑到深处才报错 | 请求进来先校验，**函数根本不会被调用** |
| 重复劳动 | 每个接口手写"读 body→解析→兜异常→写状态码" | 框架全包 |

## 为什么是这个顺序（关键）

**不能一上来就接 `/api/chat`。** 因为它要串 5 个模块，
报错了你根本不知道是哪一层的锅。

正确做法是：**先接最傻的 `/health`，出错一定是接线的问题。**

而且每一步都必须**能跑起来**——不是"写三天一起跑"，
而是"半小时后就能跑，然后一直保持能跑"。

## 为什么要"只换壳不换肉"

项目里的业务逻辑**不在 `server.py` 里**，而在 `app/api.py` 里，
写成了框架无关的纯函数（返回 `(状态码, 内容)`）。

所以接 FastAPI 时：**`api.py` 一个字都不用改**，只换外面那层壳。

```
server.py（手写外壳）      ┐
                           ├──► 都调 app/api.py（业务，零改动）
app/main.py（FastAPI外壳） ┘
```

---

# 第三部分 · 真实跑一遍（8 个场景）

## 场景 1 · `GET /health` —— 验证接线

```bash
curl.exe http://127.0.0.1:8010/health
```

**真实返回**：

```json
{"code":0,"msg":"ok","data":{"status":"ok","chat_backend":"fake","retrieval_backend":"bm25","model":"fake","db_backend":"sqlite","cache_backend":"lru"}}
```

**对应代码**（`backend/app/main.py`）：

```python
@app.get("/health", tags=["ops"], summary="健康检查（含实际生效的后端）")
async def health() -> dict:
    status, body = api.handle_health()
    return body
```

**对应代码**（`backend/app/api.py`）：

```python
def handle_health() -> tuple[int, dict]:
    return 200, ok(services().health().model_dump())
```

**这一步验证了什么**：
路由里**一行业务逻辑都没有**，只有 3 行。但返回里出现了
`db_backend`、`cache_backend`、`retrieval_backend`——
说明它真的连上了配置层、存储层、检索层。

**这就是"接线"**：你不需要 new 任何东西，`services()` 内部全组装好了。

---

## 场景 2 · `GET /openapi.json` —— 文档是代码生成的

```bash
curl.exe http://127.0.0.1:8010/openapi.json
```

**真实结果**：

```
tag: ops       -> 健康检查与看板统计
tag: chat      -> 对话（含 SSE 流式）与 Agent 规划
tag: kb        -> 知识库：文本入库、文件上传、列表分页、删除
tag: feedback  -> badcase 反馈的收集与查询
路径总数: 12
```

**对应代码**（`backend/app/main.py`）：

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

**这一步验证了什么**：
你在代码里写的 `openapi_tags` 那四行中文，**原样出现在了文档里**。
`/docs` 不是手写的，是代码生成的。

**新手最该记住**：`title` / `description` / `tags` **不是注释**，是文档内容。

---

## 场景 3 · `POST /api/chat/plan` —— 只看路由计划，不调模型

```bash
curl.exe -X POST http://127.0.0.1:8010/api/chat/plan \
  -H "Content-Type: application/json" \
  --data-binary '{"message":"加绒牛仔怎么洗","session_id":"demo1"}'
```

**真实返回**：

```json
{"code":0,"msg":"ok","data":{"plan":[
  {"name":"retrieve","desc":"检索 Agent：从知识库检索相关上下文"},
  {"name":"writer","desc":"汇总生成最终回答"}
]}}
```

**这一步验证了什么**：
后端先判断"这个问题要不要查知识库"，得到计划 `["retrieve", "writer"]`，
再按计划执行。

**为什么要有这个接口？** 工作里调试 Agent 时，"它打算怎么干"比"它干了什么"更重要。
单独开一个不上模型的接口，**调试成本从 5 秒降到 1 毫秒**。

---

## 场景 4 · `POST /api/chat` —— 完整链路

```bash
curl.exe -X POST http://127.0.0.1:8010/api/chat \
  -H "Content-Type: application/json" \
  --data-binary '{"message":"加绒牛仔怎么洗","session_id":"demo1"}'
```

**真实返回**（节选关键字段，中文原文）：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "answer": "【离线演示】根据检索到的资料：[洗涤养护.txt] 加绒牛仔：水温≤30℃，中性洗涤剂，翻面清洗，机洗选轻柔模式，避免长时间浸泡。收纳时折叠平放，避免重压破坏绒层。纯棉保（问题：加绒牛仔怎么洗）",
    "session_id": "demo1",
    "context": {
      "slots": [
        {"kind": "system",    "priority": 100, "tokens": 64},
        {"kind": "retrieval", "priority": 110, "tokens": 157},
        {"kind": "retrieval", "priority": 44,  "tokens": 74},
        {"kind": "history",   "priority": 25,  "tokens": 312}
      ],
      "total_tokens": 607,
      "budget": 4096,
      "trimmed": 0,
      "over_budget": false
    },
    "backend": "fake",
    "tokens_requested": 607,
    "tokens_generated": 97,
    "elapsed_ms": 3
  }
}
```

**这一步验证了什么**——这是整个项目最值钱的地方：

**`context.slots` 就是"上下文引擎"的产出。** 看这几个数字：

| slot | priority | tokens | 含义 |
|---|---|---|---|
| system | 100 | 64 | 系统指令，**永不参与裁剪** |
| retrieval | 110 | 157 | 检索到的资料（相关度最高） |
| retrieval | 44 | 74 | 检索到的资料（相关度较低） |
| history | **25** | **312** | 对话历史，**优先级最低** |

**规律**：`priority` 越高越保得住。历史优先级最低（25），
所以**预算不够时第一个被裁的就是它**——这正是"上下文满了怎么办"的答案。

`budget: 4096` 是 token 预算，`trimmed: 0` 表示这次没裁。
如果 `total_tokens > budget`，`over_budget` 会变成 `true`，前端上下文面板会显示告警条。

**为什么这块最值钱**：一般的 demo 是把历史对话全塞进 prompt，
越聊越大最后爆窗。这个项目是"预算 + 优先级 + 滑窗 + 摘要压缩"。

---

## 场景 5 · 故意不传 `message` —— 看参数校验

```bash
curl.exe -X POST http://127.0.0.1:8010/api/chat \
  -H "Content-Type: application/json" \
  --data-binary '{"session_id":"demo1"}'
```

**真实返回**（HTTP 400）：

```json
{"code":40001,"msg":"参数校验失败","data":null,
 "detail":[{"field":"body.message","msg":"Field required"}]}
```

**对应代码**（`backend/app/schemas.py`）：

```python
class ChatRequest(BaseModel):
    message: str = Field(..., description="The user's question")
    session_id: str = Field(default="default", description="Conversation id")
    stream: bool = Field(default=True, description="Stream tokens when True")
```

**对应代码**（`backend/app/main.py`）：

```python
@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    detail = [{"field": ".".join(str(p) for p in e.get("loc", ())), "msg": e.get("msg", "")}
              for e in exc.errors()]
    return JSONResponse(
        status_code=400,
        content=fail(ErrorCode.VALIDATION_ERROR, "参数校验失败", detail),
    )
```

**这一步验证了什么**：

1. **你一行校验代码都没写**（`Field(...)` 就是规则），FastAPI 全干了
2. `field` 是 `body.message`，精确到字段，**前端可以直接拿去表单回填**
3. 格式是统一的 `{code, msg, data, detail}`，**不是 FastAPI 默认的 `{"detail":[...]}`**

**第 3 点是怎么做到的？** 就是那个 `RequestValidationError` 处理器。
**没有它，这里会返回 `{"detail":[{"loc":["body","message"],...}]}`——前端要写两套解析。**

> 这是新手最容易漏的一步，因为它不影响功能。但不做，前端就会来找你三次。

---

## 场景 6 · `GET /api/kb/list?page=abc` —— 类型校验

```bash
curl.exe "http://127.0.0.1:8010/api/kb/list?page=abc"
```

**真实返回**（HTTP 400）：

```json
{"code":40001,"msg":"参数校验失败","data":null,
 "detail":[{"field":"query.page",
            "msg":"Input should be a valid integer, unable to parse string as an integer"}]}
```

**对应代码**（`backend/app/main.py`）：

```python
@app.get("/api/kb/list", tags=["kb"], summary="知识库文档列表（分页 + 搜索）")
async def kb_list(page: int = 1, size: int = 10, q: str = "") -> dict:
    status, body = await run_in_threadpool(api.handle_kb_list, {"page": page, "size": size, "q": q})
    return JSONResponse(status_code=status, content=body)
```

**这一步验证了什么**：
`page: int = 1` 里的那个 `int` **不是装饰**。
传 `abc` 时，**`kb_list` 函数根本不会被调用**——请求在校验层就被挡回去了。

对比：正常请求 `?page=1&size=2` 返回：

```json
{"code":0,"msg":"ok","data":{"items":[
  {"source":"尺码推荐.txt","chunks":1,"created_at":"2026-09-16 09:19:52"},
  {"source":"洗涤养护.txt","chunks":1,"created_at":"2026-09-16 09:19:52"}],
  "total":3,"page":1,"size":2,"pages":2}}
```

---

## 场景 7 · `DELETE /api/kb/不存在的来源` —— 业务错误码

```bash
curl.exe -X DELETE "http://127.0.0.1:8010/api/kb/不存在的来源"
```

**真实返回**（HTTP 404）：

```json
{"code":40400,"msg":"知识库中没有来源：不存在的来源","data":null}
```

**对应代码**（`backend/app/api.py`）：

```python
def handle_kb_delete(source: str) -> tuple[int, dict]:
    if not source:
        raise AppError(ErrorCode.VALIDATION_ERROR, "source 不能为空")
    result = services().kb_delete(source)
    if result["deleted_chunks"] == 0 and result["deleted_rows"] == 0:
        raise AppError(ErrorCode.NOT_FOUND, f"知识库中没有来源：{source}")
    return 200, ok(result)
```

**对应代码**（`backend/app/main.py`）：

```python
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.http_status, content=fail(exc.code, exc.msg, exc.detail))
```

**这一步验证了什么**：
业务代码只负责 `raise AppError(ErrorCode.NOT_FOUND, "...")`，
**HTTP 状态码 404 是自动映射出来的**（映射表在 `errors.py` 的 `_HTTP_STATUS`）。

**这就是"业务和框架解耦"**：`api.py` 完全不知道 HTTP 是什么。

---

## 场景 8 · `POST /api/chat/stream` —— SSE 流式

```bash
curl.exe -N -X POST http://127.0.0.1:8010/api/chat/stream \
  -H "Content-Type: application/json" \
  --data-binary '{"message":"身高170体重120斤穿什么码","session_id":"demo2"}'
```

**真实返回**（逐条事件，节选；`-N` 关掉 curl 自己的缓冲）：

```
data: {"type": "agent", "data": {"node": "router", ... "summary": "路由判定", "detail": {"plan": ["retrieve"], ...}}}

data: {"type": "agent", "data": {"node": "retrieve", "summary": "检索到 3 条知识", ...}}

data: {"type": "retrieved", "data": [{"text": "尺码推荐：身高170厘米，体重90–115斤建议M码...", "score": 5.7095, "source": "尺码推荐.txt"}, ...]}

data: {"type": "token", "data": "【离线演示】"}
data: {"type": "token", "data": "根据检索到的"}
data: {"type": "token", "data": "资料：[尺码"}
data: {"type": "token", "data": "推荐.txt"}
data: {"type": "token", "data": "] 尺码推荐"}
...（共 20 个 token 事件）
data: {"type": "done", "data": {"answer": "【离线演示】...", "context": {...}, "trace": [...], "used_tools": [], "backend": "fake"}}
```

**对应代码**（`backend/app/main.py`）：

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

**这一步验证了什么**：

**四种事件的职责分工**——这就是前后端契约：

| 事件 | 干什么 | 前端拿来渲染什么 |
|---|---|---|
| `agent` | 每完成一个 Agent 步骤就发 | "Agent 协作链"面板 |
| `retrieved` | 检索完成 | 命中的知识卡片（带 score） |
| `token` | 每生成一小段就发 | **打字机效果** |
| `done` | 全部结束 | 上下文面板 + trace + 收尾 |

**注意**：`token` 事件有 20 条，每条几个字——这就是"一个字一个字蹦出来"的实现。

---

# 第四部分 · 日志里的铁证：request_id 贯穿

这是最容易忽略、但工作里最有用的东西。看服务端日志的真实输出：

```
2026-09-18 16:03:31 INFO  app.http               rid=9805a54e53ff http method=POST path=/api/chat status=200 ms=4.7
2026-09-18 16:03:31 INFO  app.http               rid=906c96838f4a http method=POST path=/api/chat status=400 ms=0.7
2026-09-18 16:03:31 INFO  app.http               rid=7b3d216cd5ce http method=GET  path=/api/kb/list status=200 ms=0.6
2026-09-18 16:03:31 INFO  app.http               rid=48836e552027 http method=GET  path=/api/kb/list status=400 ms=0.4
2026-09-18 16:03:31 INFO  app.retrieval.knowledge rid=f1808910cd81 kb.deleted source=不存在的来源 rows=0 chunks=0
2026-09-18 16:03:31 INFO  app.http               rid=f1808910cd81 http method=DELETE path=/api/kb/不存在的来源 status=404 ms=1.3
```

**看最后两行**——**同一个 `rid=f1808910cd81`**：

- 一行来自 `app.http`（HTTP 层）
- 一行来自 `app.retrieval.knowledge`（检索层的 `KnowledgeBase`）

**两层、两个模块，共享同一个 request_id。** 这就是排查的线索。

而且响应头也带回来了：

```
HTTP/1.1 200 OK
x-request-id: 9805a54e53ff
```

**完整排查链路**：用户截图报错 → 看响应头 `x-request-id` → 日志里搜这个 id
→ 那次请求经过的**所有层**全出来了。

**对应代码**（`backend/app/main.py`）：

```python
@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = set_request_id(request.headers.get("X-Request-ID"))
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        status, body = error_from_exception(exc)
        log(logger, 40, "http.unhandled", path=request.url.path, error=exc.__class__.__name__)
        response = JSONResponse(status_code=status, content=body)
    response.headers["X-Request-ID"] = rid
    log(logger, 20, "http", method=request.method, path=request.url.path,
        status=response.status_code, ms=round((time.perf_counter() - started) * 1000, 1))
    return response
```

**对应代码**（`backend/app/logging_config.py`）：

```python
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

def set_request_id(rid: Optional[str] = None) -> str:
    rid = rid or new_request_id()
    request_id_var.set(rid)
    return rid
```

**为什么用 `contextvars` 而不是全局变量？**
因为 `run_in_threadpool` 会把活丢到别的线程。
全局变量在并发时会串号，`contextvars` 不会——**这是它存在的唯一理由**。

---

# 第五部分 · 从这次运行里能看到的三件事（含真实的坑）

跑通不等于没问题。真实运行能暴露出静态看代码看不出的东西：

## ① 状态码透传的问题（真实存在）

看代码：

```python
# 这两条 —— status 被丢了
async def health() -> dict:
    status, body = api.handle_health()
    return body

async def chat(payload: ChatRequest) -> dict:
    status, body = await run_in_threadpool(api.handle_chat, payload.model_dump())
    return body

# 这几条 —— 规规矩矩传了
async def kb_list(page: int = 1, size: int = 10, q: str = "") -> dict:
    status, body = await run_in_threadpool(api.handle_kb_list, {...})
    return JSONResponse(status_code=status, content=body)
```

**为什么这次没暴露？** 因为 `handle_health` / `handle_chat` 目前恒返回 200。
**但只要以后某个分支返回非 200，状态码就会被吞掉**，而中间件日志里打印的
`status=200` 也会是错的——**排查时会被误导。**

**修法**：统一成 `return JSONResponse(status_code=status, content=body)`。

## ② 参数校验跑了两遍（真实存在）

```python
# main.py —— 第一遍
async def chat(payload: ChatRequest) -> dict:
    ... payload.model_dump() ...

# api.py —— 第二遍
def handle_chat(payload: dict) -> tuple[int, dict]:
    req = ChatRequest(**payload)      # ← 又校验一次
```

**这是"防腐层"的代价**：`api.py` 要保持框架无关，不能假设调用方校验过。
当前取舍是"忍受一次重复校验，换业务层零框架依赖"。
要优化，得给 `api.py` 加一组"信任 typed 对象"的变体。

## ③ SSE 的线程池没生效（真实存在，最坑）

```python
status, events = await run_in_threadpool(api.handle_chat_stream, payload.model_dump())
```

`handle_chat_stream` 是**生成器**。这行只是**拿到生成器就返回了**，
函数体一行都没执行。真正的模型调用发生在 `for evt in events` 迭代时，
**那时已经在事件循环线程里了。**

**根源**：Python 生成器函数被调用时不执行函数体，只返回一个生成器对象。

**为什么这次看不出来？** 因为 `fake` 模型是瞬时的。
**换成 `qwen_api`（真实网络调用）并发一上来，就会堵住事件循环。**

**修法**：
```python
from starlette.concurrency import iterate_in_threadpool

async def gen():
    async for evt in iterate_in_threadpool(events):
        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
```

> **这三个坑的价值**：它们说明"接口能通"≠"没问题"。
> 而它们**只有真跑一遍、并且看懂日志，才会被发现**。
> 工作里的技术债就是这么攒下来的——**关键是认领并登记，而不是假装没有。**

---

# 第六部分 · 新手复现命令（照抄）

```bash
# 1) 起服务
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload

# 2) 浏览器打开交互文档
#    http://127.0.0.1:8010/docs
#    找到 POST /api/chat → Try it out → 填 message → Execute

# 3) 命令行跑一遍
curl.exe http://127.0.0.1:8010/health
curl.exe http://127.0.0.1:8010/openapi.json

curl.exe -X POST http://127.0.0.1:8010/api/chat/plan ^
  -H "Content-Type: application/json" ^
  --data-binary "{\"message\":\"加绒牛仔怎么洗\",\"session_id\":\"demo1\"}"

curl.exe -X POST http://127.0.0.1:8010/api/chat ^
  -H "Content-Type: application/json" ^
  --data-binary "{\"message\":\"加绒牛仔怎么洗\",\"session_id\":\"demo1\"}"

# 4) 故意传错，看校验
curl.exe -X POST http://127.0.0.1:8010/api/chat ^
  -H "Content-Type: application/json" ^
  --data-binary "{\"session_id\":\"demo1\"}"

curl.exe "http://127.0.0.1:8010/api/kb/list?page=abc"

# 5) 看 SSE 流式（-N 关掉 curl 缓冲，不然看不到逐条效果）
curl.exe -N -X POST http://127.0.0.1:8010/api/chat/stream ^
  -H "Content-Type: application/json" ^
  --data-binary "{\"message\":\"身高170体重120斤穿什么码\",\"session_id\":\"demo2\"}"

# 6) 看服务端日志（重点看 rid= 那一列）
```

**看日志时重点盯这一列**：`rid=xxxxxxxxxxxx`
同一个请求跨越多层时，`rid` 是同一个值——**这就是排查问题的绳子。**

---

# 最后 · 把整个过程压成三句话

1. **干了什么**：先建能跑的空壳 → 接第一条最傻的 `/health` →
   再一条条接真业务 → 补契约、错误、横切 → 最后接上传和流式。
   **FastAPI 只做"收信、校验、回信"，业务全在 `api.py` 及其下层。**

2. **为什么要这样**：因为一上来接 `/api/chat` 出错你不知道找哪层；
   因为"接口能通"不等于"没问题"；因为每一步都能跑，你才一直有退路。

3. **怎么和其他部分连接**：
   - 路由只认识 `api.handle_*`（**传菜口**）
   - `api.py` 只认识 `services()`（**后厨总管**）
   - 所有机器在 `AppServices.__init__` 里接上电（**设备总开关**）
   - `context/` `agents/` `retrieval/` 里**不许出现 fastapi**（**铁律**）
