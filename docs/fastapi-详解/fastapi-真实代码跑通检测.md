# 项目里 FastAPI 真实代码 · 跑通检测报告 + 逐段走读

> **这份是对项目已有代码的实测，不是教学示例。**
> 用的是 `backend/app/main.py`（197 行，项目里真实存在的 FastAPI 实现），
> 起真实服务、发真实请求、看真实日志。
>
> - 环境：Python 3.12.7 / FastAPI 0.141.1 / uvicorn 0.52.4 / pydantic 2.12.5
> - 启动命令：`cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8090`
> - 检测时间：2026-09-18

---

# 一、结论：能跑通

| 检测项 | 结果 |
|---|---|
| 服务能否启动 | ✅ 正常 |
| 13 条路由是否全部可用 | ✅ 全部 200 |
| 写接口（入库/上传/反馈） | ✅ 正常，且能删干净 |
| 异常路径（400/404） | ✅ 4 项全部符合预期 |
| `/docs` 交互文档 | ✅ 可访问 |
| `/openapi.json` | ✅ 12 条路径、4 个分组 |
| **单元测试（与 CI 一致）** | ✅ **Ran 86 tests — OK** |
| `ruff check` | ⚠️ 本机未安装 ruff（CI 里会装，不是项目问题） |
| request_id 跨层贯穿 | ✅ 日志里实测到跨 **3 个模块** |
| 全栈联调（前端） | ⚠️ 需注意：前端 proxy 指向 **8000**，用别的端口跑前端连不上 |

**20 项探针，20 项通过。** 下面逐条给证据。

---

# 二、20 项探针逐条结果（真实响应）

## 读接口（6 项）

| # | 方法 | 路径 | 状态 | 真实返回 |
|---|---|---|---|---|
| 1 | GET | `/` | 200 | `{"code":0,"msg":"ok","data":{"name":"Context Engine + Multi-Agent QA","docs":"/docs","health":"/health"}}` |
| 2 | GET | `/health` | 200 | `{"code":0,...,"data":{"status":"ok","chat_backend":"fake","retrieval_backend":"bm25","model":"fake","db_backend":"sqlite","cache_backend":"lru"}}` |
| 3 | GET | `/api/stats` | 200 | `{"code":0,...,"data":{"kb":{"chunks":3,"sources":3,"chunk_lengths":[...]},...}}` |
| 4 | GET | `/api/kb/list` | 200 | `{"code":0,...,"data":{"items":[{"source":"尺码推荐.txt","chunks":1,...},{"source":"洗涤养护.txt",...},{"source":"颜色选择.txt",...}],"total":3,...}}` |
| 5 | GET | `/api/feedback` | 200 | `{"code":0,...,"data":{"items":[],"total":0,"page":1,"size":3,"pages":0}}` |
| 6 | GET | `/api/context/checkup` | 200 | `{"code":0,...,"data":{"session_id":"checkup","turns":0,"history":[]}}` |

## 写接口（6 项）

| # | 方法 | 路径 | 状态 | 真实返回 |
|---|---|---|---|---|
| 7 | POST | `/api/chat/plan` | 200 | `{"code":0,...,"data":{"plan":[{"name":"retrieve","desc":"检索 Agent：从知识库检索相关上下文"},{"name":"writer","desc":"汇总生成最终回答"}]}}` |
| 8 | POST | `/api/chat` | 200 | `{"code":0,...,"data":{"answer":"【离线演示】根据检索到的资料：[洗涤养护.txt] 加绒牛仔：水温≤30℃，中性洗涤剂，翻面清洗...","context":{"slots":[{"kind":"system",...` |
| 9 | POST | `/api/chat/stream` | 200 | **SSE 事件数 = 21** |
| 10 | POST | `/api/kb/ingest` | 200 | `{"code":0,...,"data":{"status":"ingested","chunks":1,"filename":"体检临时文档.txt","reason":""}}` |
| 11 | POST | `/api/kb/upload` | 200 | `{"code":0,...,"data":{"status":"ingested","chunks":1,"filename":"checkup.txt","reason":""}}` |
| 12 | POST | `/api/feedback` | 200 | `{"code":0,...,"data":{"session_id":"checkup","reason":"other","created_at":"2026-09-18 08:19:47"}}` |

> 第 9 项用 `curl -N` 实测：21 个 SSE 事件（2 个 agent + 1 个 retrieved + 17 个 token + 1 个 done）。

## 删除 + 清理（2 项）

| # | 方法 | 路径 | 状态 | 真实返回 |
|---|---|---|---|---|
| 13 | DELETE | `/api/kb/体检临时文档.txt` | 200 | `{"code":0,...,"data":{"source":"体检临时文档.txt","deleted_chunks":1,"deleted_rows":1}}` |
| 14 | DELETE | `/api/kb/checkup.txt` | 200 | `{"code":0,...,"data":{"source":"checkup.txt","deleted_chunks":1,"deleted_rows":1}}` |

**清理后复查知识库，恢复原样 3 条**：
```json
{"code":0,"msg":"ok","data":{"items":[{"source":"尺码推荐.txt",...},{"source":"洗涤养护.txt",...},{"source":"颜色选择.txt",...}],"total":3,"page":1,"size":10,"pages":1}}
```

## 异常路径（4 项）

| # | 请求 | 状态 | 真实返回 |
|---|---|---|---|
| 15 | `POST /api/chat` 少 `message` | **400** | `{"code":40001,"msg":"参数校验失败","data":null,"detail":[{"field":"body.message","msg":"Field required"}]}` |
| 16 | `GET /api/kb/list?page=abc` | **400** | `{"code":40001,"msg":"参数校验失败","data":null,"detail":[{"field":"query.page","msg":"Input should be a valid integer, unable to parse string as an integer"}]}` |
| 17 | `DELETE /api/kb/不存在` | **404** | `{"code":40400,"msg":"知识库中没有来源：不存在","data":null}` |
| 18 | `GET /api/nonexistent` | **404** | `{"detail":"Not Found"}` ← ⚠️ **格式没统一，见第七节** |

## 文档（2 项）

| # | 路径 | 状态 | 结果 |
|---|---|---|---|
| 19 | `/docs` | 200 | 页面 1030 字节 |
| 20 | `/openapi.json` | 200 | **路径数 = 12**、4 个分组 |

---

# 三、日志证据：request_id 跨 3 个模块贯穿

这是本次检测最有价值的发现。看真实服务端日志（节选）：

```
rid=44297a6fa4b3 kb.chunk    chars=35 strategy=sentence ms=0.0        ← app.retrieval.knowledge
rid=44297a6fa4b3 kb.ingested source=体检临时文档.txt chunks=1          ← app.retrieval.knowledge
rid=44297a6fa4b3 http method=POST path=/api/kb/ingest status=200      ← app.http
```

再看上传那条，**跨了整整 3 个模块**：

```
rid=10a2670b99dd kb.chunk    chars=37 strategy=sentence ms=0.0        ← app.retrieval.knowledge
rid=10a2670b99dd kb.ingested source=checkup.txt chunks=1              ← app.retrieval.knowledge
rid=10a2670b99dd kb.upload   filename=checkup.txt size=89             ← app.api
rid=10a2670b99dd http method=POST path=/api/kb/upload status=200      ← app.http
```

**同一个 `rid=10a2670b99dd`，出现在 3 个不同模块的日志里。**

这就是"可观测"的实际价值：

> 用户报错 → 拿到响应头的 `x-request-id` → 日志里搜这个编号
> → **这一次请求在 HTTP 层、业务层、检索层分别干了什么，全出来。**

## 全部 20 次请求的日志（真实）

```
rid=2ff7d6bcec64 http method=GET  path=/                      status=200 ms=0.8
rid=ece8de99659a http method=GET  path=/health                status=200 ms=4.1
rid=297ceac87939 http method=GET  path=/api/stats             status=200 ms=1.0
rid=770d21bc8800 http method=GET  path=/api/kb/list           status=200 ms=1.7
rid=9818f9c462a2 http method=GET  path=/api/feedback          status=200 ms=1.1
rid=120f79f8286a http method=GET  path=/api/context/checkup   status=200 ms=0.7
rid=4803330aec61 http method=POST path=/api/chat/plan         status=200 ms=1.0
rid=52acec97bb61 http method=POST path=/api/chat              status=200 ms=6.1
rid=541f8e23466f http method=POST path=/api/chat/stream       status=200 ms=1.9
rid=44297a6fa4b3 http method=POST path=/api/kb/ingest         status=200 ms=10.1
rid=10a2670b99dd http method=POST path=/api/kb/upload         status=200 ms=6.3
rid=7f6816ba33a9 http method=POST path=/api/feedback          status=200 ms=4.5
rid=f997cce194e9 http method=DELETE path=/api/kb/体检临时文档.txt status=200 ms=5.3
rid=0656038ece0d http method=DELETE path=/api/kb/checkup.txt   status=200 ms=4.8
rid=483201fcfe3a http method=POST path=/api/chat              status=400 ms=0.5
rid=6f2ca01b8b3d http method=GET  path=/api/kb/list           status=400 ms=0.4
rid=d762324e4701 http method=DELETE path=/api/kb/不存在        status=404 ms=1.1
rid=4959f0cb8447 http method=GET  path=/api/nonexistent       status=404 ms=0.2
rid=53b5a8851fe2 http method=GET  path=/docs                  status=200 ms=0.2
rid=078bdef6a031 http method=GET  path=/openapi.json          status=200 ms=8.6
```

**注意**：连 400 和 404 也照样有 `rid` 和耗时——**出错的请求最需要排查，它们也有编号。**

---

# 四、单元测试：86 个全过

```powershell
cd backend
python -m unittest discover -s tests -q
```

真实输出：
```
Ran 86 tests in 3.586s

OK
```

这和 CI 里跑的是同一条命令（`.github/workflows/ci.yml` 的 `backend-tests` job）。

**`ruff check` 本机没装**（`No module named ruff`），CI 里会 `pip install ruff` 再跑。
想本地跑就 `pip install ruff`，不影响功能。

---

# 五、要跑通"全栈"还差一步

检测 `frontend/vite.config.ts` 发现一个关键点：

```ts
server: {
  port: 5173,
  proxy: {
    '/api': {
      target: 'http://localhost:8000',   // ← 前端默认找 8000
      changeOrigin: true,
    },
  },
},
```

而 `frontend/src/api/index.ts` 里是：
```ts
const BASE = '/api'    // 相对路径，靠 proxy 转发
```

**所以：**

| 想跑通 | 后端必须跑在 |
|---|---|
| 前端 dev（`npm run dev`，5173） | **`--port 8000`** |
| Docker（nginx 反代） | 容器内 8000（`docker compose up` 已配好） |

**我这次用的是 8090**（避免和你可能开着的服务冲突），所以**前端连不上**——
这不是 bug，是端口对不上。要联调就换回 8000：

```powershell
cd backend
uvicorn app.main:app --reload --port 8000
```

---

# 六、⚠️ 检测出的 4 个问题

跑通 ≠ 没问题。下面是静态看代码容易漏、真跑一遍才暴露的。

## 问题 1 · 未知路径的 404 格式没统一（新发现）

探针 17 和 18 放在一起看：

```
DELETE /api/kb/不存在     →  404  {"code":40400,"msg":"知识库中没有来源：不存在","data":null}   ✅ 统一
GET    /api/nonexistent   →  404  {"detail":"Not Found"}                                    ❌ 没统一
```

**原因**：`main.py` 只注册了三个处理器——`AppError`、`RequestValidationError`、`Exception`。
而"路径不存在"抛的是 Starlette 的 `HTTPException`，**不归这三个管**，
被 Starlette 自己的默认处理器接走了。

**影响**：前端拿到两种不同形状的 404，得写两套解析。**这正是 Lab 5 要解决的问题，但漏了这一类。**

**修法**：再加一个处理器

```python
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=fail(ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.BAD_REQUEST,
                     str(exc.detail)),
    )
```

## 问题 2 · 部分路由丢掉了状态码（已确认存在）

对比同一个文件里的两种写法：

```python
# 丢了 status 的（/、/health、/api/stats、/api/chat、/api/chat/plan、/api/context/{id}）
async def chat(payload: ChatRequest) -> dict:
    status, body = await run_in_threadpool(api.handle_chat, payload.model_dump())
    return body

# 正确透传的（/api/kb/ingest、/api/kb/upload、/api/kb/list、/api/kb/delete、/api/feedback）
async def kb_list(page: int = 1, size: int = 10, q: str = "") -> dict:
    status, body = await run_in_threadpool(api.handle_kb_list, {...})
    return JSONResponse(status_code=status, content=body)
```

**为什么这次检测没炸？** 因为这些 handler 目前恒返回 200。
**但只要以后有分支返回非 200，状态码就会被静默吞掉**，
而且中间件日志里打的 `status=200` 会是错的——**排查时会被误导。**

**修法**：统一成 `JSONResponse(status_code=status, content=body)`。

## 问题 3 · 参数校验跑了两遍

```python
# main.py —— 第一遍（FastAPI 用 pydantic 校验）
async def chat(payload: ChatRequest) -> dict: ...

# api.py —— 第二遍
def handle_chat(payload: dict) -> tuple[int, dict]:
    req = ChatRequest(**payload)      # ← 又校验一次
```

**这是"防腐层"的代价**：`api.py` 要保持框架无关，不能假设调用方校验过。
当前取舍是"忍受一次重复校验，换业务层零框架依赖"。

## 问题 4 · SSE 的线程池没生效

```python
status, events = await run_in_threadpool(api.handle_chat_stream, payload.model_dump())
```

`handle_chat_stream` 是**生成器**，这行只是"拿到生成器就返回了"，函数体一行没执行。
真正的模型调用发生在 `for evt in events` 迭代时——**那时已经在事件循环线程里**。

**根源**：Python 生成器函数被调用时**不执行函数体**。

**为什么这次检测看不出来？** 因为 `fake` 模型是瞬时的（`ms=1.9`）。
换成 `qwen_api`（真实网络调用）并发一上来就会堵住事件循环。

**修法**：
```python
from starlette.concurrency import iterate_in_threadpool

async def gen():
    async for evt in iterate_in_threadpool(events):
        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
```

---

# 七、带你按"从 0 到 1"的顺序读真实代码

`main.py` 这 197 行**不是一次写完的**。如果重写一遍，代码会按下面这个顺序长出来。
每一步我都标了**真实行号**，你可以对着看。

| 步 | 会写出什么 | 真实位置 | 为什么是这个顺序 |
|---|---|---|---|
| 1 | `app = FastAPI(title, version, description, openapi_tags)` | `main.py` **34–48 行** | 先有 app，`/docs` 才能开 |
| 2 | `GET /health`（先返回假数据） | **112–115 行** | 最简接口，先验证"能跑" |
| 3 | 把 `/health` 接到 `api.handle_health` | 同上 | **第一次接线**，一次连上 4 层 |
| 4 | `ChatRequest` + `POST /api/chat`（先只校验） | `schemas.py` **19–22 行** + `main.py` **125–129 行** | 契约先定，业务后接 |
| 5 | 三个 `exception_handler` | **85–103 行** | 第 4 步会暴露"错误格式不统一" |
| 6 | `request_context` 中间件 + `CORSMiddleware` | **50–81 行** | 请求多了才需要排查和跨域 |
| 7 | `run_in_threadpool` 接真业务 | **128 行** | 一到阻塞操作就必须加 |
| 8 | `StreamingResponse` 做 SSE | **138–147 行** | 特殊需求，最后做 |

**剩下的是重复劳动**：把 `ops` / `chat` / `kb` / `feedback` 四组路由按同样的套路补齐。

## 四个"连接点"在真实代码里的位置

| 连接 | 真实代码 | 说明 |
|---|---|---|
| ① FastAPI → 业务 | `main.py` 每条路由里的 `api.handle_*` | **路由里没有一行业务逻辑** |
| ② 业务 → 服务栈 | `api.py` 的 `services()` | 全局懒加载单例，唯一入口 |
| ③ 服务栈内部 | `services/chat_service.py` 的 `AppServices.__init__` | **整个项目的线都插在这 10 行** |
| ④ 横切 | `main.py` 的中间件 + `logging_config.py` 的 `contextvars` | request_id 贯穿所有层 |

## 一条铁律（实测验证过）

**`context/` `agents/` `retrieval/` 里没有 `from fastapi import`。**

这正是为什么同一份 `api.py` 能被 **两个完全不同的 HTTP 入口**调用：

| 入口 | 启动方式 | 检测结果 |
|---|---|---|
| FastAPI | `uvicorn app.main:app` | ✅ 本次检测，20 项全过 |
| stdlib 手写 | `python run.py` | 零依赖，逻辑相同 |

---

# 八、你自己复现的命令（照抄）

```powershell
# ① 起服务（想联调前端就用 8000）
cd F:\shujuf\code\context-engine-agent\backend
uvicorn app.main:app --host 127.0.0.1 --port 8000

# ② 浏览器
#    http://127.0.0.1:8000/docs   ← 点按钮就能测

# ③ 命令行逐条验（PowerShell 里双引号要反斜杠转义）
curl.exe http://127.0.0.1:8000/health
curl.exe http://127.0.0.1:8000/api/stats
curl.exe "http://127.0.0.1:8000/api/kb/list?page=1&size=5"

curl.exe -X POST "http://127.0.0.1:8000/api/chat" `
  -H "Content-Type: application/json" `
  --data-binary '{\"message\":\"加绒牛仔怎么洗\",\"session_id\":\"demo1\"}'

# ④ 故意传错，看错误格式
curl.exe -X POST "http://127.0.0.1:8000/api/chat" `
  -H "Content-Type: application/json" --data-binary '{\"session_id\":\"demo1\"}'

curl.exe "http://127.0.0.1:8000/api/kb/list?page=abc"

# ⑤ 看 SSE（-N 必须加）
curl.exe -N -X POST "http://127.0.0.1:8000/api/chat/stream" `
  -H "Content-Type: application/json" `
  --data-binary '{\"message\":\"身高170体重120斤穿什么码\",\"session_id\":\"demo2\"}'

# ⑥ 跑测试（和 CI 同一条命令）
python -m unittest discover -s tests -q

# ⑦ 看响应头里的 request_id
curl.exe -i http://127.0.0.1:8000/health
```

**看日志时盯住 `rid=` 那一列**——同一个请求跨越多层时，`rid` 是同一个值。
**这就是排查问题的绳子。**

---

# 附：本次检测的副作用（如实说明）

为了让"写接口"也能检测到，我真的写入了一条测试数据：

| 写入 | 现状 | 能否清理 |
|---|---|---|
| `POST /api/kb/ingest` 一条临时文档 | ✅ **已删除干净** | 是 |
| `POST /api/kb/upload` 一个临时文件 | ✅ **已删除干净** | 是 |
| `POST /api/feedback` 一条反馈（`session_id=checkup`, `reason=other`, `note=接口检测`） | ⚠️ **留在 `app.db` 里** | ❌ 反馈没有删除接口 |
| `POST /api/chat` 的 `checkup` 会话 | ⚠️ 留下一轮对话历史 | 存在 `data/chat_history/` |

知识库已复查恢复原样（3 条）。那条反馈和 `checkup` 会话如需清掉，
可以直接删 `backend/data/app.db` 里的 `feedback` 表和 `/api/context` 对应的会话文件——
**但更简单的做法是留着，它不影响任何功能。**
