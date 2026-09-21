# FastAPI：为什么接、怎么接（新手人话版）

> 写给**第一次接触真实项目开发**的人。
>
> 前面两份文档（`fastapi-接入工作流程.md`、`fastapi-新手接线指南.md`）讲的是
> "怎么做"，假设你已经知道"为什么要做"。这一份专门补上那个前提。
>
> 全文用一个类比贯穿：**把后端项目当成一家餐厅**。

---

## 0. 先记住这个类比

| 餐厅里的角色 | 项目里的对应物 | 一句话职责 |
|---|---|---|
| 顾客 | 浏览器 / 前端页面 | 提要求、等结果 |
| **点单员 / 前台** | **FastAPI** | 接单、核对订单、把结果端出去 |
| 菜单 | `/docs` | 告诉顾客"我们这有什么、怎么点" |
| 传菜口 | `app/api.py` | 前台和后厨之间唯一的通道 |
| 后厨总管 | `api.services()` | 后厨的唯一入口 |
| 设备总开关 | `AppServices` | 把所有机器接上电、连上水 |
| 配菜员 / 采购 / 炒锅 | `agents/` `retrieval/` `models/` | 真正干活的人 |
| 出餐标准（几克盐、摆盘） | `context/`（上下文引擎） | 控制"这道菜用多少料" |

**这家餐厅的特点是：点单员不认识任何一个厨师。** 他只跟传菜口打交道。
这就是整个项目的设计核心，后面会反复用到。

---

## 1. 先搞懂：没有 Web 框架时，后端在干什么

后端这件事，本质上就四个动作：

```
① 收信   浏览器发来一个请求（一封"信"）
② 看懂   这封信要干什么？要哪些参数？
③ 干活   查数据库、算数、调大模型……
④ 回信   把结果打包成约定格式，发回去
```

**Web 框架负责 ① ② ④，你负责 ③。**

你项目里的 `backend/server.py` 就是"不用框架、全部自己写"的版本。
看它怎么接一个 `POST /api/chat`：

```python
def do_POST(self):
    path = urlparse(self.path).path              # ① 自己拆信，看地址
    if path == "/api/chat":                      # ② 自己判断"这封信要干嘛"
        payload = self._read_json()              #    自己读信纸、自己解析 JSON
        status, body = safe_call(handle_chat, payload)   # ③ 自己调业务 + 自己兜异常
        return self._send_json(status, body)     # ④ 自己写信封、写状态码、序列化
    if path == "/api/chat/plan":                 #    再来一封信，再加一个 if
        ...
    return self._send_json(404, ...)             #    不认识的地址，自己写 404
```

**新手最容易觉得"这不挺好懂的吗，为什么要框架"？** 那是因为你只看到 5 个接口。
真实的痛点是这四条：

| 痛点 | 具体长什么样 |
|---|---|
| **越写越长** | 每加一个接口，就要在一个 `do_POST` 里再加一个 `if`。50 个接口 = 200 行 if/elif |
| **没有说明书** | 前端想知道 `/api/chat` 要传什么，只能**翻你的 Python 代码猜** |
| **参数错了才发现** | 前端少传字段，代码跑到很深处才报错，报错信息还是 Python 异常，前端看不懂 |
| **重复劳动** | 每个接口都要手写"读 body → 解析 JSON → 兜异常 → 写状态码"这四步 |

**这四条，就是 FastAPI 存在的理由。** 不是 FastAPI 高级，而是这些活太烦。

---

## 2. FastAPI 到底是个什么东西

它是**点单员 + 菜单印刷机 + 门卫**，三个身份合一：

### 身份一：点单员（路由）

你告诉它"什么地址 → 调哪个函数"，它负责接单分发。

```python
@app.post("/api/chat")              # ← 就这一行，等于 server.py 里的 if 判断
async def chat(payload: ChatRequest) -> dict:
    ...
```

不再有 if/elif。**一个接口 = 一个函数 + 一行装饰器。**

### 身份二：门卫（参数校验）

你在函数括号里写清楚"我要什么"，它自动检查、自动转换、自动拒绝。

```python
@app.get("/api/kb/list")
async def kb_list(page: int = 1, size: int = 10, q: str = ""): ...
```

前端传 `?page=abc`，FastAPI 直接返回 400 并说明"page 应该是整数"，
**你的业务代码根本不会被调用**。手写版本里你得自己写这段检查。

### 身份三：菜单印刷机（自动文档）

这是对新手最震撼的一点：**你什么都不用额外做，它就自动生成了一份可交互的接口说明书。**

- `http://localhost:8000/docs` — 能直接点按钮发请求的文档
- `http://localhost:8000/redoc` — 阅读版文档
- `http://localhost:8000/openapi.json` — 机器可读的接口规范

前端不用再来问你"这个接口传什么"，**打开 `/docs` 自己看**。
你项目 `main.py` 里那些 `tags=["chat"]`、`summary="一次性返回完整回答"`，
就是写进这份说明书的。

> 一句话记住：**FastAPI 是业务的"皮"，业务是皮下面的"肉"。**
> 皮负责跟外界打交道，肉负责真干活。**皮换了，肉不用动。**

---

## 3. 为什么"这个项目"要接 FastAPI（诚实版）

这里必须说句实话，新手最容易被绕晕：

> **你这个项目不接 FastAPI，只靠 `server.py` 也能完整跑起来。**

README 里写着 `python run.py` 就能跑，一行依赖都不用装。那为什么还要接 FastAPI？四个理由，按重要性排：

### 理由一：前端联调需要"契约"（最真实的工程理由）

前端要和后端并行开发。没有 `/docs`，前端只能：
"哥，`/api/chat` 要传啥？" → "你等下我看代码" → "session_id 是必填吗？" → ……

有 `/docs` 之后，前端自己看字段名、类型、示例、错误码。
**这是新手第一次能真切感受到"工程"和"写作业"的区别。**

### 理由二：参数校验和错误处理要统一

你项目有 12 个接口。如果每个都手写校验，会出现"这个接口返回 `{"error": "..."}`，
那个接口返回 `{"msg": "..."}`"这种烂摊子。
FastAPI 让校验和异常处理**集中在一处**（`main.py` 里三个 `exception_handler`），
所有接口的出错格式长得一样。前端只需要写一套错误处理。

### 理由三：流式输出（SSE）的落地需要它

聊天要"一个字一个字往外蹦"（打字机效果），这需要 SSE。
手写 `server.py` 里得自己 `_send_sse()` 拼 socket；
FastAPI 里有现成的 `StreamingResponse`。**这是这个项目的刚需。**

### 理由四：生态与事实标准

**FastAPI 是当前 Python 后端 + 大模型应用的事实标准**：`/docs` 自动生成、
pydantic 校验、`StreamingResponse`、异步路由，这一整套在别的框架里得自己拼。

所以这个项目接 FastAPI 是**两个目的叠加**：
1. 真实工程上确实需要（理由一~三）
2. 它是当前生态里的主流选择，值得完整走一遍

**理解这一点很重要**：不要以为"所有项目都必须用 FastAPI"。
框架是工具，需求决定工具。这个项目选 FastAPI，是因为它同时满足了上面的需要。
在真实公司里，如果项目已经用 Flask 且跑得很好，你不会为了"新"而换掉它。

---

## 4. 工作流程模拟：接 FastAPI 的这一周

现在进入你问的"模拟工作流程"。我把"给项目接 FastAPI"这件事，
拆成**一个真实的人一周里会经历的事**。注意每天都有产出，不留"写了三天还没跑"的情况。

### 星期一上午：别人来找你（需求从哪来）

工作里的活**从来不是凭空来的**，一定是有人被某件事烦到了：

- 前端："接口没文档，我联调全靠猜"
- 测试："同一个错误，有的接口返回 `{error}` 有的返回 `{msg}`，我的断言没法写"
- 你自己："加一个接口要改 3 个地方，改错一次就 500"

**你要做的第一件事：把抱怨翻译成一句话需求。**
> "后端引入 FastAPI，提供可交互接口文档 + 统一参数校验 + 统一错误格式。"

**新手最容易犯的错**：接到"接个 FastAPI"就埋头写代码。
结果做完发现前端要的是文档、测试要的是错误码——**返工**。

### 星期一下午：把现有接口抄一遍（摸底）

打开 `server.py`，把 `do_GET` / `do_POST` / `do_DELETE` 里所有 `if` 抄成一张表：
**方法 + 路径 + 要什么参数 + 返回什么**。

为什么必须先干这个？因为**接新框架时，最怕的是漏接口**——
老接口还有人用，你换的时候漏了一个，上线才发现。

**产出**：一张 12 行的接口清单（你项目的清单我已经整理在
`fastapi-接入工作流程.md` 的"阶段 6"里，可以直接看）。

### 星期二上午：想清楚"怎么接不破坏现有的"

这是**新手和老手的最大区别**。老手会先问：现有代码里，哪些是资产，哪些是要换的？

翻一下会发现关键事实：你项目的业务逻辑**不在 `server.py` 里**，而在 `app/api.py` 里，
而且写成了框架无关的纯函数（返回 `(状态码, 内容)` 两个值）。

所以方案就变得很清楚了：

```
server.py（手写外壳）      ┐
                           ├──► 都调用 app/api.py（业务，一个字不改）
app/main.py（FastAPI外壳） ┘
```

**你只换壳，不换肉。** 这就是那天上午最重要的决定。
（这个技巧叫"防腐层"，但你现在不用记这个词，记住"只换壳不换肉"就够了。）

### 星期二下午：先接一个最傻的接口（骨架）

不要一上来接 `/api/chat`（它要串 5 个模块，出错你根本不知道哪错了）。
**先接 `/health`**——它什么都不依赖。

```python
@app.get("/health")
async def health() -> dict:
    return {"code": 0, "msg": "ok", "data": {"status": "ok"}}
```

跑：`cd backend && uvicorn app.main:app --reload`
看：打开 `http://localhost:8000/docs`，能点按钮发请求。

**这一天结束时的产出：一个能跑的空壳。** 半小时的事，但意义重大——
你有了一个"确定能工作"的地基，后面每一步都是在这个地基上加东西。

### 星期三：把 `/health` 真的连上业务

把上面那个假的 `/health` 换成真的：

```python
from . import api
from starlette.concurrency import run_in_threadpool

@app.get("/health")
async def health() -> dict:
    status, body = await run_in_threadpool(api.handle_health)
    return body
```

**这是你第一次"接线"。** 你会在这里冒出一堆问题：
`api` 是什么？`handle_health` 内部怎么就有数据了？`run_in_threadpool` 为什么要加？

**这些问题就是"连接"的核心，第 5 节专门讲。**

### 星期四~五：一个接口一个接口地搬

- 一次只搬一个，搬完立刻自己点一下 `/docs` 试试
- 按分组搬：`ops`（健康检查）→ `chat` → `kb` → `feedback`
- **搬的过程中，旧的 `server.py` 必须还能跑**（不然出了问题你没法对比）

**产出**：一张"旧地址 ↔ 新路由"的对照表。

### 下周一：交付给前端，并保证不出错

- 告诉前端："文档在 `/docs`，字段和错误码都在里面"
- 补测试：`python -m unittest discover -s tests -q`
- 检查一个细节：**状态码有没有被丢掉**（你项目就有这个问题，见第 7 节）

### 整个流程记住一句话

> **每一步都留下一个能跑的东西。**
> 不是"写三天然后一起跑"，而是"半小时后就能跑，然后一直保持能跑"。

---

## 5. FastAPI 怎么和项目其他部分连接（核心问题）

这一节是你问题的正题。我用餐厅类比 + 真实代码一起讲。

### 连接一：FastAPI ↔ 业务（只通过 `api.py` 这一个口）

```python
# main.py（点单员）
@app.post("/api/chat")
async def chat(payload: ChatRequest) -> dict:
    status, body = await run_in_threadpool(api.handle_chat, payload.model_dump())
    return JSONResponse(status_code=status, content=body)

# api.py（传菜口）
def handle_chat(payload: dict) -> tuple[int, dict]:
    req = ChatRequest(**payload)
    return 200, ok(services().chat(req).model_dump())
```

**看明白这两段的关系**：路由函数里**没有一行业务逻辑**，
它只干三件事——收参数、转给 `api.handle_chat`、把结果塞进 HTTP 响应。

> **点单员不炒菜。** 这就是为什么要分层：
> 以后想换掉 FastAPI（比如换成 Flask），只需要重写"点单员"，
> `api.py` 和后面所有代码一个字都不用改。

### 连接二：业务 ↔ 所有组件（只通过 `services()` 这一个入口）

```python
# api.py
_services = None

def services() -> AppServices:
    global _services
    if _services is None:          # ← 第一次调用时才创建
        _services = AppServices(seed_kb=True)
    return _services
```

`services()` 就是"**后厨总管**"。所有 handler 需要干活时，都喊他一声。
注意它是**懒加载**的：不是启动时就创建，而是**第一次有人用的时候才创建**。

为什么要这样？因为创建它很重（要加载检索索引、开数据库连接），
而且有些场景（比如跑单元测试）根本不需要真的启动服务。

### 连接三：组件之间（在 `AppServices.__init__` 里插线）

**这是整个项目最关键的 10 行代码。** 想知道"谁连谁"，看这里就够了：

```python
# services/chat_service.py
class AppServices:
    def __init__(self, seed_kb: bool = True):
        self.retriever = get_retriever()          # 采购员：负责找资料
        self.model = get_model_backend()          # 炒锅：负责生成回答
        self.store = ChatStore(...)               # 仓库：负责存对话
        self.kb_repo = KbRepository()
        self.feedback_repo = FeedbackRepository()
        self.metrics = get_metrics()              # 记账：负责统计
        self.engine = ContextEngine(              # 摆盘标准：控制用多少料
            config.CONTEXT_TOKEN_BUDGET,
            reranker=Reranker(),
            summarizer=HistorySummarizer(self.model),   # ← 注意这行！
        )
```

**`HistorySummarizer(self.model)` 这一行值得单独说**：
它表示"上下文引擎需要用到模型"（把旧对话压成摘要要靠模型）。
**这条依赖关系，就是在这行代码里被"插上"的。**

新手常问："我怎么知道 A 要依赖 B？" 答案：**在你 new A 的时候，需要传 B 进去，
那 A 就依赖 B。** 所有的连接关系，都会在"new 的那一行"暴露出来。

### 连接四：和前端（靠"契约"，不靠代码）

后端和前端之间**没有代码连接**，只有约定：

| 约定 | 内容 |
|---|---|
| 正常响应 | `{"code": 0, "msg": "ok", "data": {...}}` 永远长这样 |
| 出错响应 | `{"code": 40001, "msg": "参数校验失败", ...}` 永远长这样 |
| 成功判定 | 看 `code == 0`，不是看 HTTP 状态码 |
| 流式事件 | SSE 里的事件名固定是 `agent` / `retrieved` / `token` / `done` |

**为什么要有契约？** 因为前端和后端是两个人在写两份代码。
没有契约，两边就永远在互相猜。有了契约，两边可以同时开工。

> **改事件名或删字段 = 撕毁契约 = 前端静默崩溃。** 加字段是安全的。
> 这是新手最容易踩的坑，记住这条能省你很多加班。

### 一条铁律（防身用）

```
HTTP 层   →   服务层   →   领域层   →   基础设施层
main.py       services     agents       storage
                           context      models
                           retrieval
```

**箭头只能往右。** 具体说：`context/`、`agents/`、`retrieval/` 这些文件里，
**绝对不允许出现 `from fastapi import ...`**。

一旦出现，你的业务就被框架绑架了：
想换框架要动全部代码，想跑单元测试还得先起一个 HTTP 服务器。

**怎么检查？** 一行命令：
```bash
# 在 backend/app/ 里搜，如果 agents/ context/ retrieval/ 里搜出来东西，就是违规
```

你项目守住了这条铁律——这也是为什么同一份 `api.py` 能被 FastAPI 和 stdlib 两个服务器同时用。

---

## 6. 一个请求的完整旅程（点外卖版）

点外卖的流程和这个项目**一模一样**，对照着看：

| 点外卖 | 这个项目 | 具体在哪 |
|---|---|---|
| ① 你在 App 上点单 | 前端发 `POST /api/chat` | `frontend/src/api/index.ts` |
| ② 商家前台接单 | FastAPI 路由匹配到 `chat` 函数 | `main.py::chat` |
| ③ 核对订单格式（几份、辣度） | pydantic 校验 `ChatRequest` 字段 | `ChatRequest`（`schemas.py`） |
| ④ 订单转到后厨传菜口 | 调 `api.handle_chat` | `api.py::handle_chat` |
| ⑤ 后厨总管接单分派 | `services()` 拿到总服务 | `api.py::services()` |
| ⑥ 看今天有没有这类菜的备料 | 先检索知识库看有没有相关内容 | `retriever.search()` |
| ⑦ 决定要不要额外采购 | Router 判断要不要检索/调工具 | `agents/router.py` |
| ⑧ 采购员去拿菜 | 检索出相关资料 | `retrieval/` |
| ⑨ 摆盘定量（这道菜放多少克） | **上下文引擎按 token 预算裁剪** | `context/engine.py` |
| ⑩ 炒锅开火 | 调大模型生成回答 | `models/*.generate()` |
| ⑪ 出餐、打包 | 包成 `{code, msg, data}` | `errors.py::ok()` |
| ⑫ 前台端给你 | 转成 HTTP 响应发回 | `main.py` 返回 |

**为什么要知道这个旅程？** 因为**出问题时你就知道去哪找**：

- 前端说"点了没反应" → 看 ②（路由有没有匹配上）
- 前端说"参数错了" → 看 ③（校验规则）
- 回答里没有知识库的内容 → 看 ⑥⑧（检索）
- 回答被截断/不完整 → 看 ⑨（token 预算裁太狠了）
- 回答特别慢 → 看 ⑩（模型调用）

**新手最大的痛苦就是"不知道该去哪找"。有了这张旅程图，就不慌了。**

---

## 7. 新手最容易懵的 5 件事

### ① 为什么函数要写 `async def`？

因为要**同时服务很多人**。FastAPI 只有一个"主线程"在处理请求，
如果里面有一段慢操作（比如调大模型要 3 秒），
**整个服务这 3 秒都不理别人了**——这叫"阻塞事件循环"。

`async def` 的意思是"我可以在这里让出位置给别人"。

**但有个坑**：`async def` 里如果写的是**普通的阻塞代码**（查数据库、调模型都是），
照样会卡住。所以你的项目用 `run_in_threadpool` 把这些活丢到别的线程去做。

> 记住结论：**`async def` 里不能直接写慢操作，要丢进 `run_in_threadpool`。**

### ② 为什么 handler 要返回两个值 `(status, body)`？

因为要**把"网络层"和"业务层"分开**：

- `status`（200/400/404）= 网络层的事，给网关、监控看
- `code`（0/40001）= 业务层的事，给前端做判断

`api.py` 只关心业务，它不知道上面盖的是 FastAPI 还是别的什么，
所以它把状态码当**普通数据**返回，让外壳去决定怎么用。
好处：同一份业务代码，两个服务器都能用。

### ③ 为什么有个全局变量 `services()`？

见第 5 节"连接二"。一句话：**避免重复创建重东西**。
检索索引加载一次就够，数据库连接不用每个请求都开。

### ④ 什么是"中间件"？

就是"每个请求都会经过的一道关卡"。你项目用它做了三件事：

```python
@app.middleware("http")
async def request_context(request, call_next):
    rid = set_request_id(...)          # 给这次请求发一个编号
    started = time.perf_counter()      # 开始计时
    response = await call_next(request)  # 放行，让它继续走
    response.headers["X-Request-ID"] = rid   # 把编号写回响应头
    log(...)                           # 记一笔日志
    return response
```

**好处**：出问题时，用户把响应头里的编号给你，你直接搜日志就能定位。
不用写 12 遍。

### ⑤ `uvicorn app.main:app` 这行命令什么意思？

拆开看：

| 部分 | 含义 |
|---|---|
| `uvicorn` | 真正的"服务器程序"，负责监听端口、收发网络数据 |
| `app.main` | 一个模块路径 = `app/main.py` 文件 |
| `:app` | 这个文件里的那个叫 `app` 的变量 |

**新手常见误解**：以为 FastAPI 就是服务器。
不是——**FastAPI 是"应用"（负责业务逻辑），uvicorn 是"服务器"（负责网络）**。
两者配合工作，就像"餐厅"和"店铺门面"。

还有一个坑：**必须在 `backend/` 目录下运行**，
因为 `app.main` 这个写法要求"当前目录能看见 `app` 这个文件夹"。

---

## 8. 你现在该做什么（第一步只有一件事）

别看太多，先动手。顺序是：

**第一步（今天）**：什么都不改，只把项目跑起来，看一眼 `/docs`

```bash
cd backend
uvicorn app.main:app --reload
# 浏览器打开 http://localhost:8000/docs
```

在 `/docs` 里点开 `POST /api/chat`，点 "Try it out"，填个 `message`，点 Execute。
**看一眼返回的 JSON**——特别是 `data.context`（上下文用了多少 token）
和 `data.agent_trace`（后端走了哪几步）。

**这一步的目的**：让你亲眼看到"我发一个请求，后端串起了 5 个模块"。
有了这个具体印象，再去读代码就不抽象了。

**第二步**：找到 `main.py` 里的 `chat` 函数，对照第 6 节的旅程表，一个一个文件点进去看。
看不懂的先跳过，**至少把路线记住**。

**第三步**：在 `backend/app/` 下新建一个 `main_min.py`，只写 20 行，
接一个 `/ask` 接口，调 `api.handle_chat`。跑通它。
（练手代码在 `fastapi-新手接线指南.md` 第 6 节，可以直接抄。）

---

## 最后：把所有事压成三句话

1. **为什么接 FastAPI**：因为手写路由会越写越长、没文档、校验乱、错误格式不统一。
   FastAPI 把"收信、校验、回信"这三件烦事包了，你只管写业务。

2. **怎么接**：先接一个最傻的接口跑通 → 一个接口一个接口搬 →
   全程旧的还能用 → 最后交给前端。

3. **怎么和项目其他部分连接**：
   - FastAPI 只认识 `api.py`（**传菜口**）
   - `api.py` 只认识 `services()`（**后厨总管**）
   - 所有机器在 `AppServices.__init__` 里接上电（**设备总开关**）
   - `context/` `agents/` `retrieval/` 里**不许出现 fastapi**（**铁律**）

**记住这四条连线，整个项目就通了。**
