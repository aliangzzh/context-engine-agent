# FastAPI 入门 —— 只看这一份

> 给"有一点基础、第一次在真实项目里用 FastAPI"的人。
> **看完这份就够开始了。** 其余文档全部挪到了 `docs/fastapi-详解/`，遇到具体问题再去翻。
>
> 项目里的真实实现：`backend/app/main.py`（197 行）。

---

## 0. 一句话

**FastAPI 是"收 HTTP 请求 → 调你的函数 → 把返回值变成响应"的框架。**

在这个项目里，它只是**最外面薄薄一层**：

```
① FastAPI 外壳    main.py（197 行）        ← 只负责收信、校验、回信
② 防腐层          api.py                   ← 框架无关的业务函数
③ 服务组装        services/chat_service.py ← 所有东西在这 10 行里接上
④ 真正干活        agents/ context/ retrieval/ models/ storage/
```

**记住这张图，后面全是它的展开。**

---

## 1. 先跑起来（3 条命令）

```powershell
cd F:\shujuf\code\context-engine-agent\backend

# ① 起接口服务
uvicorn app.main:app --host 127.0.0.1 --port 8090

# ② 验证（另开一个窗口）
#    ✅ 最简单：浏览器地址栏直接打开（GET 接口都行，不用装任何东西）
#       http://127.0.0.1:8090/health
#    ⏭️ 命令行版（可选，等你要发 POST 请求时再学）
curl.exe http://127.0.0.1:8090/health

# ③ 想看界面的话，停掉再用零依赖入口
python run.py        # 然后打开 http://localhost:8000/
```

> **验证接口有 4 种方式，随便挑一种就行：**
>
> | 方式 | 适合 | 说明 |
> |---|---|---|
> | **浏览器地址栏** | GET 接口 | **最简单，推荐新手先用这个** |
> | `curl.exe` | POST / 脚本 | 命令行，方便复制粘贴 |
> | Postman / Apifox | 日常开发 | 工作中最常用，图形界面，要装 |
> | 写测试 | 真实工程 | 最正经，见 `backend/tests/` |
>
> **`curl` 不是必须的。** 它只是"方便"，不是"必需"——用浏览器一样能验证。

**应该看到**：
```json
{"code":0,"msg":"ok","data":{"status":"ok","chat_backend":"fake",
 "retrieval_backend":"bm25","model":"fake","db_backend":"sqlite","cache_backend":"lru"}}
```

> ⚠️ **两个小坑，知道就行，别深究：**
> - **不要用 `/docs`**：这台机器没有外网，那个页面的界面代码要从 CDN 下载，打开是**白页**。测试用 `curl.exe`，或者用 `python run.py` 自带的界面。
> - **PowerShell 里给 curl 传 JSON**：双引号必须写成 `\"`，外层用单引号。
>   `--data-binary '{\"message\":\"你好\"}'`

---

## 2. 你现在只需要懂的 5 件事

### ① 怎么加一条接口 —— 两行

```python
@app.get("/api/ping", tags=["ops"], summary="测试接口")
async def ping() -> dict:
    return {"code": 0, "msg": "ok", "data": {"pong": True}}
```

`@app.get("/地址")` + 一个函数 = 一条接口。**不用再写 `if path == "/api/ping"`。**

### ② 参数写在函数签名里，不写在函数体里

```python
class ChatRequest(BaseModel):                      # 契约
    message: str = Field(..., description="用户的问题")   # 三个点 = 必填
    session_id: str = Field(default="default")            # 有默认值 = 可省

@app.post("/api/chat")
async def chat(payload: ChatRequest) -> dict:      # ← 括号里声明，FastAPI 自动校验
    ...
```

前端传错，FastAPI 自动返回 400，**你的函数根本不会被调用**。

### ③ 路由里不写业务 —— 这是项目最重要的规矩

```python
@app.post("/api/chat")
async def chat(payload: ChatRequest) -> dict:
    status, body = await run_in_threadpool(api.handle_chat, payload.model_dump())
    return JSONResponse(status_code=status, content=body)
```

**路由只干三件事**：收参数 → 转给 `api.handle_chat` → 塞进 HTTP 响应。
**一行业务逻辑都没有。**

为什么要这样？因为业务逻辑要能被别的地方复用（这个项目里 stdlib 入口 `server.py` 也在用同一份 `api.py`）。

### ④ "接线" = 找到已经组装好的入口

这是新手最容易卡住的地方。看 `api.py`：

```python
def handle_health() -> tuple[int, dict]:
    return 200, ok(services().health().model_dump())

def services() -> AppServices:
    global _services
    if _services is None:
        _services = AppServices(seed_kb=True)     # ← 第一次调用时才创建
    return _services
```

**`services()` 是后厨总开关。** 它内部（`chat_service.py` 的 `AppServices.__init__`）把检索器、模型、数据库、上下文引擎全接好了。

> **所以你写路由时不需要 `new` 任何东西——调 `api.handle_xxx` 就行。**

### ⑤ 慢操作要丢进线程池

```python
from starlette.concurrency import run_in_threadpool

status, body = await run_in_threadpool(api.handle_chat, payload.model_dump())
```

**判断标准一句话**：函数里有没有读文件 / 读数据库 / 发网络请求？**有 → 就包 `run_in_threadpool`。**

不包的后果：不是变慢，是**其他请求全部排队**（事件循环被堵住）。

---

## 3. 第一个练习：加一条自己的接口

**别新建文件**，直接在 `main.py` 里照抄 `/health` 的样子加一条：

```python
@app.get("/api/ping", tags=["ops"], summary="测试接口")
async def ping() -> dict:
    return {"code": 0, "msg": "ok", "data": {"pong": True}}
```

然后：
```powershell
# 重启服务，然后
curl.exe http://127.0.0.1:8090/api/ping
```

**看到 `{"code":0,"msg":"ok","data":{"pong":true}}` 就成了。**

记得删掉——练习完别留在项目里。

---

## 4. 谁连谁（四个连接点）

```
浏览器 ──► main.py 路由
              │ ① 只调 api.handle_*
              ▼
          api.py ──► services()          ← ② 唯一入口
                        │
                        ▼
                   AppServices.__init__  ← ③ 所有东西在这 10 行里接上
                        │
        ┌───────────────┼───────────────┬──────────────┐
        ▼               ▼               ▼              ▼
   retrieval/       models/        storage/       context/
   （检索）          （模型）        （存储）        （上下文引擎）
                        │
                        ▼
              AgentOrchestrator（多 Agent 编排）
```

**一条铁律**：`context/` `agents/` `retrieval/` 里**不许出现 `from fastapi import`**。
违反了，业务就被框架绑架，换框架和写单测都动不了。

---

## 5. 报错速查（先看这里，别去搜）

| 报错 / 现象 | 真正的原因 | 怎么改 |
|---|---|---|
| `No module named 'app'` | 不在 `backend/` 目录下 | `cd backend` 再启动 |
| `No module named 'api'` | 写成了 `import api` | 改成 `from . import api`（**那个点不能少**） |
| `... must be in format "<module>:<attribute>"` | 少写了 `:app` | `uvicorn app.main:app` |
| `Address already in use` | 端口被占用 | 换端口，如 `--port 8091` |
| 改了代码没生效 | 没重启 | `Ctrl+C` 再启动 |
| `{"code":40001,...,"msg":"JSON decode error"}` | PowerShell 吃掉了双引号 | 双引号写成 `\"`，外层用单引号 |
| 前端一个请求都发不出，后端日志干净 | CORS（跨域） | 去**浏览器控制台**看，不是后端问题 |
| `/docs` 打开是白页 | 这台机器没外网，界面要从 CDN 下载 | 用 `curl.exe` 或 `python run.py` 的界面 |

---

## 6. 想深入的时候，再去看这些

**都在 `docs/fastapi-详解/` 里，按需查，不用通读。**

| 你想搞清楚 | 看这份 |
|---|---|
| 这些代码是怎么一步步写出来的（带真实运行输出） | `真实代码从0到1带练.md` |
| 一个请求进来，经过哪些层、去哪个文件找问题 | `新手接线指南.md` |
| 为什么要接 FastAPI、跟项目其他部分什么关系 | `为什么和怎么接-人话版.md` |
| 真实工作里这个过程长什么样（工单、评审、提交） | `工作场景开发实录.md` |
| 项目现在跑通了吗、有哪些已知问题 | `真实代码跑通检测.md` |
| 想自己动手敲一遍（8 个 Lab） | `跟练手册.md` |
| 以后带人做项目时（任务卡、评审、验收标准） | `接入工作流程.md` |
| 其余（12 步重放、8 步实跑、真实运行记录） | 同目录，按名字挑 |

---

## 最后一句话

> **你只需要记住三件事：**
> 1. 加接口 = `@app.get(...)` + 函数
> 2. 参数写在签名里，业务调 `api.handle_*`
> 3. 慢操作包 `run_in_threadpool`
>
> **其余的都是遇到问题了再学。**
