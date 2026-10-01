---
name: context-engine-agent
description: 在本仓库（Context Engine + Multi-Agent QA）里改代码、加功能、排查问题时使用。它说明怎么零依赖跑起来、哪些东西绝对不能动（BM25 结果顺序 / kb.json 写入路径 / 现有评测题期望值 / 双 HTTP 入口）、改完必须跑哪两条命令，以及这个仓库真实踩过的几个坑。
---

# Context Engine + Multi-Agent QA（本仓库开发规范）

## 1. 先跑起来（离线、零依赖）

```bash
cd backend
python run.py                    # stdlib HTTP 服务器 → http://localhost:8000
# 或（需 pip install fastapi uvicorn，逻辑完全相同，都调 app/api.py）
uvicorn app.main:app             # /docs 有 Swagger
```

```bash
cd frontend
npm install && npm run dev       # http://localhost:5173
# 页面：#/ 对话 · #/kb 知识库 · #/dashboard 看板
```

不配任何 key 也能跑全链路（离线 `fake` 模型 + BM25）。想接通义千问：
`pip install -r requirements-llm.txt`（只用 `.env` 填 key 不装依赖会**静默退回离线模型**）。

## 2. 改完必须跑这两条（缺一条都算没做完）

```bash
cd backend
..\.venv\Scripts\python.exe -m unittest discover -s tests -q   # 全绿（当前 116 个）
..\.venv\Scripts\python.exe -m eval.run --check                # 回归门，回退则 exit 1
```

> 本地若报 `PermissionError` / `unable to open database file`：删掉
> `backend/tests/_scratch/` 与 `backend/eval/_run/` 重跑即可（都是 `.gitignore` 里的派生数据）。

## 3. 🔴 绝对不能动

| 约束 | 原因 |
|---|---|
| **BM25 的结果顺序** | CI 回归门跑的是 `bm25 + fake`（`eval/run.py` 里锁定 bm25），排序一变门就红 |
| **`kb.json` / `kb_chunks` 的写入路径** | 保持零数据迁移；改动必须同步向量索引与 md5 指纹，否则出现"新文档搜不到 / 删了还命中" |
| **现有 5 类评测题的期望值** | 只能**加题、加类别**，不能改旧题；加完必须 `--save-baseline` 重冻，否则旧基线立刻判回退 |
| **双 HTTP 入口一致性** | 新接口要同时改 `app/api.py`（handler + `__all__`）、`server.py`（import + if 链）、`app/main.py`（路由）三处 |
| **`rerank` 写进 `RetrievedChunk` 的 `priority`** | 它是 `model_copy(update=...)` 造的野字段，`model_dump()` 会丢（SSE 那条路已经丢过一次） |

## 4. 这个仓库真实踩过的坑（改代码前先扫一眼）

1. **沉默的错误**：`except Exception: return {}` 会把坏请求吞掉 → 改显式 `400 + 错误码`；超预算用 `over_budget` 如实上报。
2. **跨线程假设**：SQLite 连接默认不能跨线程，而 HTTP 服务器是多线程的 → `check_same_thread=False` + 锁，并补并发回归测试。
3. **假参数**：工具调用把整句用户输入当参数，"跑通了"但结果全错（`未找到城市「北京今天天气怎么样」`）→ `extract_args` 抽参数，抽不到就追问。
4. **前后端字段漂移**：SSE 发 `used_tools`、前端读 `usedTools` → 页面永远不显示工具调用。这类问题只有"跑起来看"或类型检查才发现。

细节与更多例子见 `docs/ai-assisted.md`；经验被沉淀成可检索技能后放在根目录 `skills/`（见 `skills/README.md`）。

## 5. 约定

- **零依赖优先**：能 stdlib 就不引包；可选依赖（faiss / redis / pymysql / fastapi）必须**优雅降级**而不是崩。
- **中文注释解释"为什么"**，不是"做了什么"；踩过的坑要写进注释或文档。
- **每个修复配一条测试**，评测相关改动要有定点单测（`tests/test_eval.py` 就是这么用的）。
- **改动分阶段提交**，每阶段跑一次上面两条命令，全绿再合。
