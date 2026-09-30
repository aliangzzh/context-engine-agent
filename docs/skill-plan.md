# Skill / 经验复用接入方案（决策稿）

> 目标：给本项目加一套「**把开发经验沉淀成 Skill，Agent 干活时自动调用**」的能力：
> **归档 → 结构化 → 检索 → 注入上下文 → 可度量**（闭环）。
>
> 定位：这不是另起一个项目，而是**本项目自己的第 8 个模块**——用你已经跑通的
> 「入库 → 检索 → 增强 → 生成」链路，去管你自己的开发经验（自举）。
>
> 现状：本仓库**没有任何 Skill 相关代码**（净新增），但**零件已经齐了 80%**：
> Agent 编排、上下文槽与预算裁剪、BM25 + 向量双检索、SQL 仓储、零依赖评测框架全都在。

---

## 一、先回答："加 Skill 到底加的是什么？"

三层，别混在一起谈：

| 层 | 是什么 | 本项目现状 | 工作量 |
|---|---|---|---|
| ① 项目**本身**成为一个 Skill | 仓库里放 `.agents/skills/context-engine-agent/SKILL.md`，让 Cursor / Claude Code / DSH 这类编码 Agent 一进仓库就懂规矩（怎么跑、别动什么、有哪些坑） | ❌ 没有 | **~1 小时**，零代码风险 |
| ② 项目**内部**有技能库 | `skills/` 目录 + SKILL.md 规范 + 归档脚本 + 独立检索语料 | ❌ 没有（业务知识库有，经验库没有） | 半天 ~ 1 天 |
| ③ Agent **真的会用**技能 | 触发匹配 → 注入上下文 → trace 可解释 → 评测能量化 | ⚠️ 零件齐，缺"技能"这一路 | 1 ~ 1.5 天 |

**最重要的一个结论（先说风险）**：

> 本项目的评测跑的是**离线 `fake` 模型**（`models/fake.py`，只回放检索到的片段，不生成真答案）。
> 所以「带了技能，模型变聪明了」这种结论**离线测不出来**。离线能测的只有三件事：
> **① 该技能有没有被检索到 ② 有没有进上下文 ③ 答案里有没有出现它的约束原文**。
> 真实增益必须接真模型（`DASHSCOPE_API_KEY`）跑同题两遍对比 —— 口径写进 `docs/evaluation.md`，别含糊。

---

## 二、影响面：哪些文件会动、哪些绝对不能动

### ✅ 会新增 / 修改

| 文件 | 动作 | 说明 |
|---|---|---|
| `backend/app/skills/` | **新增目录** | `loader.py`（解析 SKILL.md）+ `matcher.py`（触发匹配）+ `store.py`（技能语料检索） |
| `skills/`（仓库根） | **新增目录** | 技能正文（人可读、可 Git review）：`<name>/SKILL.md` + `references/*.md` |
| `backend/scripts/collect_experience.py` | **新增** | 归档脚本：把踩坑记录抽成四段式（与 `scripts/upload_corpus.py` 同风格） |
| `backend/app/schemas.py:41` | 改 1 处 | `ContextSlot.kind` 的 `Literal` 加 `"skill"`——**不加就 `ValidationError`** |
| `backend/app/context/engine.py:47-56` | 改签名 | `build()` 增 `skills` 入参 |
| `backend/app/context/engine.py:64-84` | 加一段 | 生成 `kind="skill"` 的槽，priority 建议 **70**（高于 tool=60，仅次于 system=100） |
| `backend/app/context/engine.py:112-127` | 改 1 处 | `render_messages` 的 `elif` 链**没有 `else`**：新 kind 不加分支会被**静默丢弃**（只在上下文面板出现，不进 prompt） |
| `backend/app/agents/router.py:34-58` | 加关键词 | 技能触发词 → `step = "skill"` |
| `backend/app/agents/orchestrator.py:132-171` | 加分支 | `skill` 节点：调 matcher → 取技能正文 → 写 trace（命中理由 + 来源文件） |
| `backend/app/agents/orchestrator.py:176-182` | 改 1 处 | 把技能内容传进 `engine.build()` |
| `backend/app/agents/tools.py:222-232` | 加 1 条 | 注册 `search_skill` 工具（让 Agent 也能主动查经验） |
| `backend/app/retrieval/retriever.py:193` | **必改** | 缓存 key `retrieve:{backend}:{k}:{query}` 无「语料」维度 → 技能库与业务库**必然串味**，要加 namespace |
| `backend/app/config.py:78` | 加配置 | `SKILL_DIR` / `SKILL_KB_PATH` / `SKILL_INDEX_NAME` / `SKILL_ENABLED` |
| `backend/app/services/chat_service.py:32-45` | 加装配 | 第二套 `Retriever(kb_path=SKILL_KB_PATH)` + 独立 `VectorIndex(index_name=SKILL_INDEX_NAME)` |
| `backend/app/storage/repo.py` | 加 1 个类 | `SkillRepository`（技能元数据 + 命中统计），仿 `KbRepository`（repo.py:72） |
| `backend/app/storage/db.py:24-54` + `:123-152` | 加建表 | **SQLite 与 MySQL 两份都要写**；没有迁移机制，`IF NOT EXISTS` 不会补列 |
| `backend/tests/test_skills.py` | **新增** | 6 条测试，见 §5 |
| `backend/eval/` | 加一类 | 新类别 + 重冻 baseline，见 §5 |
| `docs/evaluation.md` / `docs/architecture.md` | 各加一节 | 口径与模块图 |

### 🔴 绝对不能动

| 约束 | 原因 |
|---|---|
| **BM25 的结果顺序** | CI 回归门跑的是 `bm25 + fake`（`eval/run.py:110-111` 强制锁 bm25），动了排序 → 门变红 |
| **`kb.json` / `kb_chunks` 的写入路径** | 保持零数据迁移；技能库用**新的独立文件 + 新表**，不碰老的 |
| **现有 5 类题的期望值** | 只能**新增类别**，不能改旧题；新增题会改 `overall_pass_rate` 分母 → 旧 baseline 立刻判回退 |
| `RetrievedChunk.priority` | 它是 `rerank.py:123` 用 `model_copy(update=...)` 写进 `__dict__` 的**野字段**，`model_dump()` 会丢（SSE 那条路已经丢过一次）——别把关键数据挂在它上面 |

**三个必须知道的坑（都是这次调研挖出来的）**：

1. **缓存串味**：`retriever.py:193` 的 key 没有语料维度，而 `cache.py` 是**进程级全局单例**（`clear()` 在 Redis 下就是 `flushdb()`）。技能库若共用 key，`bm25 + k=3 + 同一个问题` 会跨库命中。
2. **BM25 是全局扁平语料**：一个 `Retriever` 实例只有一份 `docs` 列表，两库塞一起会互相挤掉 top-k → 必须**物理隔离**（独立 `kb.json` + 独立向量索引目录/名字）。
3. **向量索引指纹**：`vector_index.py:63` 对**全部** text 排序哈希，技能库若共用 `index_name`，两边 `corpus_md5` 互踩 → **恒 STALE、永远降级 BM25**。

---

## 三、三个可选方案（你来选做到哪一层）

### 方案 A：最小可用（约 1~2 小时）

**做什么**
1. 加 `.agents/skills/context-engine-agent/SKILL.md`（项目自身的说明书：怎么跑、约定、四个已知坑）
2. 加 `skills/` 目录规范 + 1 个示例技能（就写 `tool-arg-extraction`）
3. `loader.py` + 注册 `search_skill` 工具（直接读文件，**不入库、不检索**）
4. 3 条单测 + `docs/skill-plan.md` 定稿

**产出**：能演示"Agent 会调一个技能工具，并把技能正文拿到"；面试可讲"Skill 是什么格式、怎么被加载"。

**遗留风险**：技能一多就靠关键词硬匹配；没有语料检索、没有评测数字 → **只能讲机制，不能讲效果**。

---

### 方案 B：可用 + 可讲（1~2 天）★ 推荐

**A 的全部，加上 5 件必须做的事：**

| # | 做什么 | 解决什么 |
|---|---|---|
| 1 | **独立技能语料**：`skills/` 为 source of truth，切分后进 `data/skills/kb.json` + 独立向量索引（`SKILL_INDEX_NAME=skills`）；缓存 key 加 namespace | 修坑 ①②③（串味 / 挤 top-k / 恒 STALE） |
| 2 | **归档脚本** `scripts/collect_experience.py`：从 `docs/ai-assisted.md` §3 的**四类真实问题** + `docs/code-review.md` + `git log` 抽成「现象 / 根因 / 修复 / 验证」四段式，MD5 幂等 | "自动归档"落地，且**第一批数据是真的、不是编的** |
| 3 | **Context Engine 的 skill 槽**：`kind="skill"`、priority=70、`render_messages` 加分支 | 技能真正进 prompt（不踩"静默丢弃"那个坑） |
| 4 | **matcher + trace**：关键词/tag 命中 + 复用 `context/rerank.is_relevant` 做覆盖率门控（防乱触发）；trace 写"为什么加载这个技能" | 触发可解释、可调试；面经里最值钱的一段 |
| 5 | **评测新类别**：`dataset_skill.json` 8~12 题，量**技能命中率**与**约束进上下文比例**，并做 `--skills on/off` 对照 | 有数字可讲，且口径诚实（离线只测"进没进上下文"） |

**产出**：`/health` 能看到技能库规模；一条踩坑题能被检索到、进上下文、出现在 trace 里；评测有前后对比。

**验收**：见 §5。

---

### 方案 C：完整（约 3 天）—— 直接命中 JD 加分项

**B 的全部，加上 3 件事：**

| # | 做什么 | 命中什么 |
|---|---|---|
| 6 | **MCP 暴露**：`search_skill` 注册进 `TOOLS` 后，只要在 `mcp_server.py:28-42` 补一份 JSON Schema，**外部编码 Agent 就能通过 MCP 调你的经验库** | JD「MCP / Tool Calling」+ "能力可被外部 Agent 复用" |
| 7 | **前端技能页** `#/skills`：`api/index.ts` 加接口 → `mock/index.ts` 加假数据 → 新建 `views/SkillsView.vue` → `router/index.ts:18-22` 加一行（导航自动出现） | 全栈交付完整度 |
| 8 | **自举**：把本项目**自己的**踩坑（四个坑 + 这次的环境问题）写进技能库，下一轮开发真的用它 | 面试最强叙事："我做的经验库，第一个用户是我自己" |

---

## 四、方案对比

| | A 最小 | **B 推荐** | C 完整 |
|---|---|---|---|
| 耗时 | 1~2h | **1~2 天** | ~3 天 |
| 新增文件 | 3 | 6~8 | 12+ |
| 技能进 prompt | ❌ 只有工具返回 | ✅ 独立槽位 | ✅ |
| 语料隔离 / 不串味 | — | ✅ | ✅ |
| 有评测数字 | ❌ | ✅（离线口径） | ✅ + 真模型口径 |
| 外部 Agent 可调（MCP） | ❌ | ❌ | ✅ |
| 回归门风险 | 极低 | 低（新增类别，需重冻 baseline） | 低 |

**建议**：**做 B**。C 的第 6 条（MCP）成本只有 10 分钟，顺手做掉 —— 它是"能力可被复用"这句话的**唯一硬证据**。

---

## 五、验收标准（每阶段跑同样的命令）

```powershell
cd F:\shujuf\code\context-engine-agent\backend
..\.venv\Scripts\python.exe -m unittest discover -s tests -q     # 基线实测 116 全绿；加 6 条后期望 122
..\.venv\Scripts\python.exe -m eval.run --check                  # 新增类别后需先重冻 baseline
..\.venv\Scripts\python.exe -m eval.run --save-baseline          # 只在确认改动正确后执行
```

**新增 6 条测试**（`backend/tests/test_skills.py`）：

| # | 测试 | 断言 |
|---|---|---|
| 1 | SKILL.md 解析 | front-matter 缺失/字段不全时**不崩**，给出明确跳过原因 |
| 2 | matcher 正反例 | "工具参数怎么抽" → 命中 `tool-arg-extraction`；"今天天气" → **不命中**（门控生效） |
| 3 | **缓存不串味** | 同一 query 分别查业务库/技能库，结果**互不污染**（回归 §2 的坑 1） |
| 4 | 技能槽受预算约束 | 技能正文超长 → 按 priority 被裁，且 `over_budget` 如实上报 |
| 5 | **skill 槽不被静默丢弃** | `render_messages` 后 system 内容里**含**技能正文（回归 §2 表里 `engine.py:112-127` 那条） |
| 6 | 技能库不污染业务库 | 入库/删除技能后，业务 `kb_chunks` 与 BM25 结果**零变化** |

**评测口径（写进 `docs/evaluation.md`，别含糊）**：

| 指标 | 离线（fake 模型）能测什么 | 需要真模型 |
|---|---|---|
| `skill_hit_rate` 技能命中率 | ✅ 该技能是否进 top-k | — |
| `skill_injected` 约束进上下文 | ✅ 技能正文是否出现在模型输入里 | — |
| `grounding_gain` 真实增益 | ❌ **测不出来**（fake 只回放） | ✅ 同题 `--skills on/off` 两遍对比 |

**手动验收（3 步）**：
1. 问一句带坑的编码问题 → 看 trace 里有没有 `skill` 节点、命中哪个文件
2. 打开上下文面板 → 确认 `kind=skill` 的槽在里面，且 token 计入预算
3. 临时删掉 `skills/` 里那个技能 → 再问 → **确认不再命中**（证明是真检索，不是硬编码）

---

## 六、回滚方案（四层，前两层不用碰代码）

| 层 | 手段 | 耗时 |
|---|---|---|
| **1. 配置回滚** | `.env` 加 `SKILL_ENABLED=0` → 重启，全部新路径短路 | 秒级 |
| **2. 数据回滚** | 删 `skills/` 与 `data/skills/` → 技能库为空，主链路不受影响 | 秒级 |
| **3. 代码回滚** | 分支隔离，`git checkout main` | 1 分钟 |
| **4. 数据迁移** | **不需要** —— 技能库是新增独立文件 + 新表，`turns` / `kb_chunks` / `feedback` 一行不动 | — |

---

## 七、执行顺序（阶段划分）

```
阶段 0 环境与分支
  ✅ 已完成：本地 backend/tests/_scratch 与 backend/eval/_run 里残留了旧沙箱会话创建的目录，
     当前进程写不进去 → 87 个测试报 35 个 PermissionError、eval 报 "unable to open database file"。
     两者都在 .gitignore（第 8 / 27 行），是纯派生数据，删除后重建即可。
     删完复测：116 个测试全绿、eval 回归门九项全 1.0000（这就是本方案的真实基线）。
     → 以后本地再出现同类报错，直接删这两个目录重跑，不要怀疑代码。
  ⏳ 待做：feat/vector-retrieval 上还有 3 个未提交文件 + 2 个未跟踪目录（backend/scripts/、docs/images/）：
     先提交或 stash，再从可用基线开 feat/skills，别和向量检索那条线缠在一起。

阶段 1（1h）方案 A：项目自身 SKILL.md + skills/ 规范 + search_skill 工具 + 3 条单测
阶段 2（半天）技能库：collect_experience.py 归档脚本 + 四类真实踩坑入库 + 独立语料与索引 + 缓存 namespace
阶段 3（半天）Agent 接入：skill 槽 + matcher + trace + 冒烟验证（手动验收 3 步）
阶段 4（半天）评测：dataset_skill.json + score_case 新分支 + METRIC_KEYS + test_eval 类别集合 + 重冻 baseline + docs
阶段 5（可选，1h）MCP 暴露 + 前端技能页 + 自举（把自己这次的坑写进技能库）

每阶段一个 commit，每阶段跑一次 §5 的两条命令；全绿再合。
```

---

## 八、决策点（请你选）

- [ ] **方案 A**：1~2 小时，能讲机制、没有数字
- [ ] **方案 B**：1~2 天，技能真进 prompt + 有评测口径 ← **建议**
- [ ] **方案 B + C 第 6 条（MCP）**：性价比最高（+10 分钟，多一条"可被外部 Agent 调用"的硬证据）← **如果只做一次，选这个**
- [ ] **方案 C**：完整（含前端页 + 自举），约 3 天
- [ ] **暂不做**：先专心收尾 `feat/vector-retrieval`（向量检索那条线已经在半空中）

---

## 九、方案 B 的注意事项（开工前先看这一页）

> 一句话：B 的坑**不在"能不能写出来"，而在两类假象**——
> **①「看着生效了，其实没生效」 ②「有个数字，但数字站不住」**。

### 9.1 速查表（按"你会怎么发现它"排）

| # | 症状（你怎么发现） | 根因 | 对策 |
|---|---|---|---|
| 1 | 上下文面板里**有** `skill` 槽，但回答完全不受影响 | `engine.py:112-127` 的 `render_messages` 是 `elif` 链、**没有 `else`**：新 kind 不进 prompt | 加 `skill` 分支 + 写死一条测试断言（§5 第 5 条） |
| 2 | 问"工具参数怎么抽"，检索回来的却是"尺码推荐" | `retriever.py:193` 缓存 key 没有语料维度 + 缓存是进程级单例（`cache.py:92-99`，Redis 下 `clear()` 直接 `flushdb()` `cache.py:87`） | 缓存 key 加 namespace（如 `retrieve:skills:...`） |
| 3 | `/health` 里 `retrieval_effective` **永远是 bm25**，配了 hybrid 也没用 | `vector_index.py:63` 的指纹对**全部**文本算；两库共用 `VECTOR_INDEX_NAME`（`config.py:78`）→ 指纹互踩，**恒 STALE** | 技能库用独立 `index_name` / `index_dir`（`vector_index.py:122-134`） |
| 4 | 技能库一入库，**业务问答的召回变差**（或反过来） | BM25 是"一坨扁平语料"（`retriever.py:63/97`），一个实例只有一份 docs，两库一起塞会互相挤掉 top-k | 物理隔离：独立 `kb.json` + 独立 `Retriever` 实例 |
| 5 | 本地全绿，**CI 红**；或 `--check` 直接判回退 | 新增题目会改 `overall_pass_rate` 的分母（`run.py:295-296`），旧 baseline 立刻算回退 | 确认改动正确后 `--save-baseline` **重冻**，并让 `test_eval.py:74-77` 用新基线 |
| 6 | `unittest` 红在评测那条：类别集合不相等 | `test_eval.py:47-49` 是**集合相等**断言，`KNOWN_CATEGORIES`（`:25`）必须同步 | 加类别名，和 `dataset.json` 一起改 |
| 7 | 新指标在报告里**根本不出现** | `METRIC_KEYS`（`run.py:260-270`）没登记 → 不打印、`--check` 也不校验 | 加指标名；`CATEGORY_TITLE`（`:382-388`）也要加，否则不打这一类 |
| 8 | A/B 跑了，但只看到一次观测 | 现有 Harness 是"**一题一次观测**"模型，表达不了两遍 | 按「附 2」改 8 处；每个 case 跑两遍 → **耗时翻倍**，分母语义要写清 |
| 9 | 你写出"带技能准确率提升 X%"，被追问细节答不上 | 离线 `fake` 模型（`models/fake.py`）**只回放检索片段，不生成** | 离线只讲「命中率 / 是否进上下文」；真实增益必须接真模型跑同题两遍 |
| 10 | stdlib 服务器上没有新接口，FastAPI 有 | 本项目**双 HTTP 入口**：`api.py` handler + `__all__`（`:151-157`）、`server.py` 的 import（`:24-29`）与 if 链（`:171-253`）、`main.py` 路由 | 四处一起改，别只改一处 |
| 11 | 我明明改了 SKILL.md，Agent 行为还是老的 | `skills/` 是 source of truth，**文件改了要重新入库**（否则索引还是旧内容） | 入库前比对 md5/清单，启动或 reload 时做一致性校验 |
| 12 | 技能从目录里删了，检索**还能命中**（幽灵结果） | 索引没跟着删 —— 和你在向量检索里踩过的是同一类一致性坑 | 复用你在 `vector_index.py` 里的**指纹检测**思路，别靠"记得重建" |
| 13 | 外部 Agent 调 `search_skill` 时参数是空的 | `mcp_server.py:28-42` 的 `_TOOL_SCHEMAS` 没补，回退成空 object | 补一份 JSON Schema（10 分钟，顺手完成方案 C 第 6 条） |
| 14 | 本地又报权限错 / `unable to open database file` | `backend/tests/_scratch`、`backend/eval/_run` 残留旧沙箱目录 | 删这两个目录重跑（都在 `.gitignore` 第 8/27 行），**不要怀疑代码** |
| 15 | 每问一句都变慢 | `get_retriever()` 每次 new 实例（`retriever.py:299-300`），技能库若每请求新建会重复读盘/建索引；配了向量则**每个问题多一次 embedding 调用（收费）** | 技能检索实例挂在 `AppServices` 上做单例（`chat_service.py:32-45`） |

### 9.2 最容易翻车的 5 个（按优先级）

1. **槽位静默丢弃（#1）**——最阴的一个：面板上看得见，prompt 里没有。**先写测试再写功能**。
2. **缓存串味（#2）**——技能库和业务库"串味"以后，你会以为是匹配算法写错了，实际是缓存层。
3. **向量恒 STALE（#3）**——不隔离索引名，向量这条线等于白配，还查不出原因。
4. **评测数字站不住（#5/#9）**——回归门变红会挡住 CI；离线口径说错会在面试被问穿。
5. **双入口漏改（#10）**——这个项目特有的结构，改接口时最容易"一半有、一半没有"。

### 9.3 技能内容本身的质量红线（比代码更容易出问题）

| 注意 | 为什么 | 怎么做 |
|---|---|---|
| **粒度：一条技能 = 一个具体的坑** | 太宽（"Python 最佳实践"）会**永远命中**、等于噪音；太窄会**永远不命中** | 起步 4~8 条，就用 `docs/ai-assisted.md` §3 那四类真实问题 |
| **必须是真踩过的** | 编出来的技能会在追问"这个坑当时怎么发现的"时崩 | 每条都带「现象 / 根因 / 修复 / 验证」，验证指向**真实存在的测试或文件** |
| **front-matter 要容错** | 技能是人手写的，总会写错字段 | 缺字段**不崩**，给明确跳过原因（§5 第 1 条测试） |
| **触发要能"不命中"** | 关键词匹配最容易乱触发（问天气也命中技能） | 复用 `context/rerank.is_relevant` 做覆盖率门控，并写**正反例**测试（§5 第 2 条） |
| **别把技能塞进 PROTECTED_KINDS** | 技能正文长了会挤掉参考资料 | 默认按 priority=70 参与裁剪；要"永不裁"必须显式配置并知道代价 |

### 9.4 流程与范围

- **先把 `feat/vector-retrieval` 收尾**（3 个未提交文件 + 2 个未跟踪目录），再开 `feat/skills`：两条线缠在一起，出问题分不清是谁的。
- **别一次做成方案 C**：前端页、自举都可以后置。范围一涨，"每阶段验收全绿"就守不住了。
- **每阶段一个 commit + 跑 §5 两条命令**；`--save-baseline` 只在**确认改动正确**之后执行，别拿它去"让 CI 变绿"。
- **技能库的检索结果同样要过相关性门控**：技能命中率低不要紧（可以调），**误命中**才是灾难（Agent 会拿着不相干的经验去改代码）。

### 9.5 开工前自检（勾完再动手）

- [ ] `SKILL_ENABLED` 开关写好了（回滚第一条靠它）
- [ ] 缓存 key 带上了语料 namespace（#2）
- [ ] 向量索引名 / 目录与业务库不同（#3）
- [ ] `ContextSlot.kind` 加了 `"skill"`，且 `render_messages` 有对应分支（#1）
- [ ] 技能库是独立 `kb.json` + 独立 `Retriever` 实例（#4）
- [ ] 双入口四处（`api.py` / `__all__` / `server.py` / `main.py`）都改了（#10）
- [ ] `test_eval.py` 的 `KNOWN_CATEGORIES` 已同步（#6）
- [ ] 新指标进了 `METRIC_KEYS` 与 `CATEGORY_TITLE`（#7）
- [ ] `docs/evaluation.md` 写清了"离线测什么、真模型才能测什么"（#9）
- [ ] baseline 重冻过，且 CI 五道门本地都过了一遍

---

## 附：方案 B 的文件级改动清单（照着做即可）

| 顺序 | 文件 | 动作 | 参考位置 |
|---|---|---|---|
| 1 | `skills/tool-arg-extraction/SKILL.md` | 新增（front-matter：`name` / `description` / `tags` / `trigger` / `status` / `version`） | 仿 `.venv/.../fastapi/.agents/skills/fastapi/SKILL.md` 的格式 |
| 2 | `backend/app/skills/loader.py` | 新增：扫 `skills/` → 解析 front-matter → `Skill` 对象（**手写解析，零依赖**） | — |
| 3 | `backend/app/skills/matcher.py` | 新增：关键词/tag + `is_relevant` 门控 | `context/rerank.py:is_relevant` |
| 4 | `backend/app/skills/store.py` | 新增：技能语料入库 + 检索（独立 `Retriever`） | `retrieval/knowledge.py:88-125` |
| 5 | `backend/app/config.py` | 加 `SKILL_ENABLED` / `SKILL_DIR` / `SKILL_KB_PATH` / `SKILL_INDEX_NAME` / `SKILL_TOP_K` | 第 78 行附近 |
| 6 | `backend/app/retrieval/retriever.py:193` | 缓存 key 加语料 namespace | 必改，否则串味 |
| 7 | `backend/app/schemas.py:41` | `Literal` 加 `"skill"`；可另加 `SkillHit` schema | — |
| 8 | `backend/app/context/engine.py:47-84`、`:112-127` | `build()` 收 `skills` → 建槽；`render_messages` 加 `skill` 分支 | priority=70 |
| 9 | `backend/app/agents/router.py:34-58`、`orchestrator.py:132-171`、`:176-182` | `skill` 节点 + trace + 传参 | 仿 `retrieve` 分支 |
| 10 | `backend/app/agents/tools.py:222-232`、`mcp_server.py:28-42` | `search_skill` 工具 + MCP schema（顺手完成方案 C 第 6 条） | — |
| 11 | `backend/app/storage/db.py:24-54`、`:123-152`、`repo.py` | 新表 `skill_meta`（技能元数据 + 命中次数）+ `SkillRepository` | 仿 `KbRepository` |
| 12 | `backend/app/services/chat_service.py:32-45`、`:168-190` | 装配技能检索；`stats()` / `health` 暴露技能库规模 | — |
| 13 | `backend/scripts/collect_experience.py` | 归档脚本（`docs/ai-assisted.md` §3 四类 + `code-review.md` + `git log` → 四段式 md，MD5 幂等） | 仿 `scripts/upload_corpus.py` |
| 14 | `backend/eval/` | `dataset_skill.json` + `run.py` 的 `score_case` / `METRIC_KEYS` / `CATEGORY_TITLE` + `test_eval.py` 类别集合 + 重冻 `baseline.json` | run.py:190-256 / 260-270 / 382-388 |
| 15 | `docs/evaluation.md`、`docs/architecture.md`、`README.md` | 各加一节（口径、模块、特性） | — |

---

## 附 2：评测做 A/B 对照要动的函数（照行号改，别漏）

现有的评测是「**一题一次观测**」模型，表达不了「带技能 / 不带技能」两遍对比，所以要动 8 处：

| # | 位置 | 怎么改 |
|---|---|---|
| 1 | `eval/run.py:94-129` `Harness.__init__` | 加 `skills: bool` 开关（开/关技能库路径与索引） |
| 2 | `eval/run.py:140-176` `Harness.ask` | 加 `variant` 参数，或新增 `ask_pair()` 跑两遍 |
| 3 | `eval/run.py:190-256` `score_case` | 加分派（建议在 `:355` 处按类别转到新函数），`obs` 带两路信号 |
| 4 | `eval/run.py:339-374` `_run_cases` | `record/signals` 容纳两次观测（`:361-363` 的 rank 只服务 retrieval，短路安全） |
| 5 | `eval/run.py:273-297` `compute_metrics` | 加 `skill_hit_rate` 与「技能增益」口径 |
| 6 | `eval/run.py:260-270` `METRIC_KEYS` | 加指标名——**不加就不打印、`--check` 也不校验** |
| 7 | `eval/run.py:382-388` `CATEGORY_TITLE` | 加类别标题，否则 `print_report`（`:401`）不显示这一类 |
| 8 | `eval/run.py:451` + `tests/test_eval.py:25` | `--category` 帮助文案；`KNOWN_CATEGORIES` 加类别名（`:47-49` 是**集合相等**断言，两边必须同步） |

**两个必须记住的评测约束**：
- `compare()` 对 baseline 里**缺失的 key 直接跳过**（`run.py:433-434`），所以新增指标本身不会让旧 baseline 报错；
  但**新增题目会改变 `overall_pass_rate` 的分母**（`:295-296`）→ 旧基线立刻判回退 → **必须先 `--save-baseline` 重冻**，并让 `test_eval.py:74-77` 跟着用新基线，否则 CI 门变红（`ci.yml:40-46`）。
- 每个 case 跑两遍会让 30 题级评测**耗时翻倍**；`env.cases` 与 `overall_pass_rate` 的分母语义要在报告里写清楚，别让人误读。

