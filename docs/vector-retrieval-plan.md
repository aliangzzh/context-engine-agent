# 向量检索接入方案（决策稿）

> 目标：把副项目 `P4_RAG项目案例` 里验证过的 FAISS 向量索引，接入本项目作为**可选的检索后端**；
> 向量不可用时**自动降级 BM25**，服务永不中断。
>
> 基线：`main` @ `58517ef`，tag `baseline-before-vector`，103 测试全绿，eval 回归门 100%。

---

## 一、先回答："只接向量索引就够了吗？"

**不够。** 分三件事看：

| 事项 | 现状 | 只接索引够不够 |
|---|---|---|
| 让向量检索**跑起来** | 缺"建索引"代码（只有 `load_local`，无 `from_texts`/`save_local`） | ✅ 补上就够了 |
| 让它**不出错** | 索引是静态快照，上传/删除不同步 → 新文档搜不到、删掉的成幽灵结果 | ❌ **必须另做一致性处理** |
| 让它**有效** | `_embed_search` 的 `score` 写死 `1.0`，`rerank` 会按词项重叠把语义排序**抹平** | ❌ **必须同时修 score** |

**结论**：接索引是 1/3 的工作量；**另外 2/3 是"一致性"和"score 语义"**。

---

## 二、影响面：哪些文件会动、哪些绝对不能动

### ✅ 会新增/修改

| 文件 | 动作 | 说明 |
|---|---|---|
| `backend/app/retrieval/vector_index.py` | **新增** | 建索引 / 增量追加 / 落盘 / 指纹校验（从 P4 搬 + 加固） |
| `backend/app/retrieval/knowledge.py` | 改 1 处 | `ingest_text` 成功后调用 `vector_add`；`delete_source` 后触发重建或标记失效 |
| `backend/app/retrieval/retriever.py` | 改 2 处 | `_embed_search` 返回**真实相似度分**；用 `self._emb_store` 缓存 store |
| `backend/app/config.py` | 加配置 | `VECTOR_*` 系列开关 |
| `backend/app/services/chat_service.py` | 改 `health()` | 暴露**实际生效**的检索后端 + 索引状态 |
| `backend/requirements-llm.txt` | 取消注释 | `faiss-cpu>=1.8` |
| `backend/tests/test_core.py` | 加 5 条 | 见 §5 |
| `docs/evaluation.md` | 加一节 | BM25 / 向量 / hybrid 的对比数据 |
| 前端徽章文案 | 改 1 处 | `dashscope` → `bm25 + dashscope`（口径准确） |

### 🔴 绝对不能动

| 约束 | 原因 |
|---|---|
| **BM25 路径的输出顺序** | CI 的 eval 回归门跑的是 **BM25 + 离线 fake 模型**（CI 只装 `requirements.txt`，无 faiss、无 key）。改了 BM25 结果 → **回归门变红** |
| **`kb.json` / SQL 的写入路径** | 不改写入路径 → 零数据迁移 → 不需要数据回滚 |
| **`rerank.py` 的默认行为** | 它是 BM25 和向量共用的；任何改动必须**配置化**或只在向量路径生效 |

---

## 三、三个可选方案（你来选做到哪一层）

### 方案 A：最小可用（约 1 小时）

**做什么**
1. 新增 `vector_index.py`（建索引 + 增量追加 + 落盘）
2. `knowledge.py` 入库后调用一次
3. `pip install faiss-cpu`，手动建一次索引

**产出**：能演示"向量检索真的在工作"——`/health` 名义上是 `dashscope`，实际也真的是向量召回。

**遗留风险（要如实知道）**
- ⚠️ 上传新文件后**搜不到它**（索引没同步）
- ⚠️ 删除文档后**还能搜到**（幽灵结果）
- ⚠️ rerank 把语义排序**抹平**，效果可能还不如 BM25

> **适合**：只想先"有这个东西"。但风险是"看起来做了，实际更差"。

---

### 方案 B：可用 + 可讲（约 3~4 小时）★ 推荐

**A 的全部，加上 4 件必须做的事：**

| # | 做什么 | 解决什么 |
|---|---|---|
| 1 | `_embed_search` 改用 `similarity_search_with_score()` 返回**真实相似度** | 修 rerank 抹平语义 |
| 2 | **索引指纹**（`index_meta.json` 记 `corpus_md5` + `embedding_model` + `chunk_count`）；检索前校验，不一致 → **标记 STALE 并降级 BM25** | 修"新文档搜不到 / 幽灵结果"——不靠"记得重建"，靠机器检测 |
| 3 | `self._emb_store` 缓存 FAISS store（每次检索不再读盘） | 修性能 |
| 4 | `health()` 暴露 `retrieval_effective` + 索引状态（status / chunk_count / last_degrade） | 修"徽章说 dashscope 实际 BM25"的误导 |

**产出**：向量检索**真的能用**，且三态降级（READY / STALE / UNAVAILABLE）都能观测、能解释。

**验收**：见 §5。

---

### 方案 C：完整（约 1 天）—— 直接命中 JD 加分项

**B 的全部，加上 2 件事：**

| # | 做什么 | 命中 JD |
|---|---|---|
| 5 | **`hybrid` 混合检索**：BM25 + 向量两路召回 → **RRF 融合**（只看名次，规避两路分数量纲不可比） | 加分项 5「RAG 效果优化」 |
| 6 | **用现有 eval 框架做消融对比**：BM25 vs 向量 vs hybrid，把三个数字记进 `docs/evaluation.md` | 加分项 4「向量库/Embedding 选型」+ 加分项 5「对比 Embedding 模型」 |

**为什么第 6 条价值最高**：你已经有零依赖跑分器 + 30 题题库 + 冻结基线。
**"我对比过三种检索方案，通过率分别是 X / Y / Z"** —— 这是加分项 4 明确要求的
「能讲清楚：为什么选这个方案、效果好在哪里」。

**额外好处**：hybrid 天然缓解一致性问题——向量索引看不到新文档，但 **BM25 兜得住**。

---

## 四、方案对比

| | A 最小 | **B 推荐** | C 完整 |
|---|---|---|---|
| 耗时 | ~1h | **~3-4h** | ~1 天 |
| 新增文件 | 1 | 1 | 1 |
| 改动点 | 2 处 | 6 处 | 7 处 |
| 向量真能用 | ⚠️ 勉强 | ✅ | ✅ |
| 一致性有保障 | ❌ | ✅ 指纹检测 | ✅ + hybrid 兜底 |
| 效果不倒退 | ❌ rerank 抹平 | ✅ | ✅ 且更好 |
| 面试可讲 | 少 | **够** | **命中 JD 加分项 4+5** |
| 回归门风险 | 低 | 低 | 低（配置化） |

**建议**：**做 B**；如果时间允许，把 C 的第 6 条（评测对比）单独拿出来做——
**它成本最低（几小时）、加分最高**，因为评测框架你已经有了。

---

## 五、验收标准（每阶段跑同样的命令）

```powershell
cd backend
..\.venv\Scripts\python.exe -m unittest discover -s tests        # 期望 103 → 108 全绿
..\.venv\Scripts\python.exe -m eval.run --check                   # 期望回归门全 1.0000、零错误
```

**新增 5 条测试：**

| # | 测试 | 断言 |
|---|---|---|
| 1 | 依赖缺失降级 | 无 faiss → 返回 BM25 结果，不抛异常 |
| 2 | 索引不存在降级 | 无 `index_meta.json` → `status=UNAVAILABLE` → 降级 |
| 3 | **指纹不匹配降级** | 语料变了但索引没重建 → `status=STALE`，**且不返回过期结果** |
| 4 | 增量追加 | 上传后 `chunk_count` 与语料一致，新文档**能被向量检索到** |
| 5 | 写入失败不影响入库 | mock `save_local` 抛异常 → 上传仍成功、索引标记为 stale |

**手动验收（每次改完都做一遍）：**
1. 上传一个新文件 → 提问相关问题 → **确认答案引用了它**
2. 删除该文件 → 再问 → **确认不再引用它**（没有幽灵结果）
3. `/health` → `retrieval_effective` 与实际一致

---

## 六、回滚方案（四层，前两层不用碰代码）

| 层 | 手段 | 耗时 |
|---|---|---|
| **1. 配置回滚** | `.env` 改 `RETRIEVAL_BACKEND=bm25` → 重启 | 秒级 |
| **2. 索引回滚** | 删掉 `index_meta.json` → 自动判定不可用 → 降级 | 秒级 |
| **3. 代码回滚** | `git checkout main`（分支隔离） | 1 分钟 |
| **4. 数据回滚** | **不需要** —— 因为不改写入路径，零数据迁移 | — |

**工作流**：`main` 保持可用 → 开 `feat/vector-retrieval` 分支 → 分阶段提交（每阶段一个 commit）→ 全绿再合。

---

## 七、执行顺序（无论选哪个方案）

```
0. git push origin main --tags          ← 先把基线推到远端（含 tag）
1. git checkout -b feat/vector-retrieval
2. 阶段一：新增 vector_index.py + 改 knowledge.py → 跑测试 + 手动验证
3. 阶段二：修 score / 指纹 / store 缓存 / health → 跑测试 + eval 回归门
4. 阶段三（可选）：hybrid + 评测对比 → 跑测试 + 记录数据
5. 每阶段一个 commit；全绿后 git checkout main && git merge feat/vector-retrieval
```

**已知代价（提前接受）**
- 之后**每次上传文件会调一次 embedding**（按 token 计费，很便宜但不再是 0）
- **每次检索多一次 embedding 调用**（只 embed 问题，不 embed 文档）
- 索引目录必须是**纯 ASCII 路径**（P4 踩过：FAISS 底层 C++ 读不了中文路径）

---

## 八、决策点（请你选）

- [ ] **方案 A**：最小可用，1 小时，但效果可能不如 BM25
- [ ] **方案 B**：可用 + 可讲，3-4 小时 ← **建议**
- [ ] **方案 C**：完整，1 天，直接命中 JD 加分项 4+5
- [ ] **方案 B + C 的第 6 条**：性价比最高 ← **如果只能做一次，选这个**
- [ ] **暂不做**：先专心截图 / 面试准备，向量检索留到面试后
