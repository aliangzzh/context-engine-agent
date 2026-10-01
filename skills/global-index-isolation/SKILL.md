---
name: global-index-isolation
description: 测试、评测或脚本"拿临时语料跑个流程"时，必须隔离全局资源（向量索引目录、缓存、数据库文件）；否则会用临时语料把线上索引覆盖掉，而且不报错、CI 也测不出来。
tags: [testing, retrieval, faiss, isolation]
trigger: [向量索引, 索引, 隔离, stale, 降级, 全局目录, 覆盖]
stack: [python]
status: active
version: 1
updated: 2026-09-30
---

# 全局索引/缓存目录被临时语料覆盖

## 规则（检查清单）

1. **列一遍全局资源**：索引目录、缓存单例、数据库文件、日志文件。任何"进程级共享路径"
   在测试 / 评测 / 脚本里都必须显式隔离（重定向到临时目录）。
2. **隔离要跟着数据走**：语料在哪，索引就该在哪 —— 默认值应该由**参数推导**
   （拿自定义语料路径时，索引默认放它旁边），而不是硬编码一个全局路径。
   只改测试不改实现，等于把坑留给下一个脚本。
3. **降级必须可观测**：状态要能自证（`status` / `chunk_count` / 原因字段）。
   这次能发现，靠的就是 `/health` 里"语料 488 块、索引 1 块"这个刺眼的对比。
4. **复现即测试**：把"跑完整个测试套件后，业务索引仍与语料一致"变成一条断言 ——
   否则修完还会复发。
5. **CI 绿不等于安全**：CI 没装可选依赖（faiss）时，这条代码路径根本不会执行。
   涉及可选依赖的坑要在**本机**验一遍。

## 反例（本仓库真实发生过）

**跑一次 `test_api.py`，业务向量索引被写成 1 块**

- 现象：`/health` 里 `retrieval_effective` 恒为 `bm25`、`vector_index.status=stale`、
  `chunk_count=1`（实际语料 488 块）。配置写着 hybrid，却永远走 BM25，**且不报错**。
- 根因：`tests/test_api.py` 的隔离 setUp 重定向了 `DATA_DIR / KB_DIR / DB_PATH`，
  **漏了 `FAISS_PERSIST_DIR`**（索引目录是全局的）。它用临时目录里 1 块的语料触发了一次
  rebuild，把业务索引的 `index_meta.json` + `index.faiss` 覆盖了。
  `VectorIndex.meta_path` 是 `<目录>/index_meta.json` —— **指纹按目录存放，不按索引名**，
  所以"换个索引名"并不能隔离。
- 修复：① `Retriever` 在调用方给了自定义 `kb_path` 且未显式指定 `index_dir` 时，
  默认把索引放到**那份语料旁边**（`kb_path.parent / "faiss"`）；
  ② `test_api.py` 的隔离集合补齐 `FAISS_PERSIST_DIR` / `SKILL_INDEX_DIR`。
- 验证：`backend/tests/test_core.py::RetrieverIndexIsolationTest`（3 条：
  自定义语料用本地索引目录 / 默认语料仍用全局目录 / 显式 `index_dir` 优先）；
  手工验证：`python -m app.retrieval.vector_index` 重建（488 块）→
  跑完 `python -m unittest discover -s tests`（156 个）→ `chunk_count` 仍是 488。
- 为什么 CI 没拦住：CI 只装 `requirements.txt`，没有 faiss → 索引根本写不出来，
  这条路径在 CI 里是"死代码"。

## 怎么自查你正在犯这个错

- `/health` 里某个 `status` 恒为降级/stale，但日志里没有报错 → 先怀疑"被谁覆盖了"。
- 索引/缓存的规模（`chunk_count`、缓存条数）与语料规模**差得离谱** → 立即对齐两者时间戳。
- 你的隔离 setUp 里只重定向了数据库和语料目录，**没提索引/缓存目录** → 就是它。
- 某个"只在本地复现、CI 永远绿"的问题 → 想想 CI 少了哪个可选依赖。
