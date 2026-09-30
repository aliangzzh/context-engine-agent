# 技能库（skills/）规范

> 这里放**开发经验技能**：一个文件夹 = 一个技能 = 一个具体的坑（或一套具体做法）。
> 目标不是"写文档"，而是**让 Agent 在动手前能把这条经验调出来用**。

## 一、目录结构

```
skills/
├── README.md                       # 本文件：格式规范
└── <skill-name>/                   # 目录名 = front-matter 里的 name，kebab-case
    ├── SKILL.md                    # 必填：规则 + 检查清单 + 反例索引（要短）
    └── references/                 # 选填：详细案例、日志片段、代码对比
        └── case-*.md
```

## 二、SKILL.md 的 front-matter

```markdown
---
name: tool-arg-extraction
description: 一句话说清"什么时候该用它"——这是触发匹配的主要依据，必须写场景，不要写口号。
tags: [tool-calling, agent]
trigger: [工具调用, 参数, 抽参, function calling]
stack: [python]
status: active
version: 1
updated: 2026-09-30
---
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | ✅ | 唯一标识，kebab-case，**必须与目录名一致** |
| `description` | ✅ | 一句话说清适用场景；**匹配主要看它**，写"工具调用必须先抽参数"比写"工具调用规范"有用 |
| `tags` | | 分类标签，便于筛选 |
| `trigger` | | 触发词（能出现在用户问题里的短词），给关键词匹配用 |
| `stack` | | 技术栈，如 `python` / `vue` |
| `status` | | `active`（参与匹配）/ `deprecated`（保留但不再匹配） |
| `version` | | 整数，改内容时 +1 |
| `updated` | | 日期，改内容时同步 |

> front-matter 解析是**容错**的：缺字段不会让服务崩，只会跳过该技能并记录原因
> （技能是人手写的，写错是常态）。

## 三、正文怎么写（比格式更重要）

正文只放三块，**控制在 40~80 行**（它会被塞进模型的上下文预算里）：

1. **规则 / 检查清单**——可执行的判断句，不要写背景介绍。
2. **反例（真实发生过的）**——每条按四段式写：`现象 / 根因 / 修复 / 验证`。
3. **怎么自查**——"如果你看到 X，说明你正在犯这个错"。

### 三条质量红线

| 红线 | 为什么 | 怎么做 |
|---|---|---|
| **一条技能 = 一个具体的坑** | 太宽（"Python 最佳实践"）会**永远命中**、等于噪音；太窄会永远不命中 | 起步 4~8 条，每条一个坑 |
| **必须真踩过** | 编的技能在"当时怎么发现的"这一问上会崩 | 每条都指向**真实存在的文件或测试** |
| **验证可复现** | 不能复现的经验等于传闻 | `验证：` 后面写清跑哪条命令 / 看哪个测试 |

## 四、新增一条技能（三步）

```bash
# 1) 复制模板
mkdir -p skills/<skill-name>/references
# 2) 写 SKILL.md（至少要有 name / description）
# 3) 跑校验（阶段 2 提供；现在可以先跑单测）
cd backend && ..\.venv\Scripts\python.exe -m unittest tests.test_skills -v
```

## 五、改完技能之后

- 技能正文是**索引的真源**：改了文件要重新入库（阶段 2 的归档脚本会按 md5 检测变化），
  否则会出现"我明明改了它还是老行为"。
- 删除技能时同步删索引，否则会**幽灵命中**（和向量索引那类一致性问题同源）。
- 重要改动把 `version` +1、`updated` 改成当天。

## 六、怎么跑通 / 怎么确认技能真的生效

### 6.1 三条命令（不装任何依赖，先确认"库是好的"）

```bash
cd backend
..\.venv\Scripts\python.exe -m scripts.collect_experience check    # 技能格式校验，不合规 exit 1
..\.venv\Scripts\python.exe -m scripts.collect_experience sync     # 同步进检索语料（md5 幂等）
..\.venv\Scripts\python.exe -m unittest tests.test_skills -v       # 加载/匹配/语料/槽位/节点
```

### 6.2 起服务看真实效果（推荐）

```bash
# 终端 1
cd backend && ..\.venv\Scripts\python.exe run.py      # http://localhost:8000
# 终端 2
cd frontend && npm run dev                            # http://localhost:5173
```

打开对话页，问一句**带触发词**的开发经验问题。触发词：`经验` / `坑` / `技能库` / `教训` / `skill`。

| 问法 | 期望看到 |
|---|---|
| 「查一下工具调用参数抽取的踩坑经验」 | Agent 面板出现 📘 **skill** 节点；上下文面板出现「**技能（开发经验）**」槽（优先高于检索槽）；回答里就是那条技能的规则与反例 |
| 「加绒牛仔怎么洗」 | **没有** skill 槽（技能库不截胡业务问答，这是精准门在起作用） |

### 6.3 只看接口（不开前端）

```powershell
$body = '{"message":"接口字段前后端对不上有经验吗","stream":false}'
Invoke-RestMethod http://127.0.0.1:8000/api/chat -Method Post -ContentType 'application/json' -Body $body
# 看 data.skills / data.context.slots（kind=skill）/ data.agent_trace
```

### 6.4 量化证据（A/B：带技能 vs 不带技能）

```bash
python -m eval.run --dataset dataset_skill.json --skills both
```

### 6.5 给外部编码 Agent 用（MCP）

`search_skill` 已经在 MCP 工具清单里（`mcp_server.py` 直接复用 `TOOLS` 注册表）：

```bash
cd backend && python mcp_server.py     # JSON-RPC 2.0 over stdio
# 配进 Cursor / Claude Code / DSH 的 MCP 配置，外部 Agent 就能直接查这个经验库
```

### 6.6 自己产一条技能（归档链路）

两条入口：**从文档起草**、**从对话历史起草**。

```bash
# A) 从 docs/ 抽「N. **标题**：解释」形式的条目
python -m scripts.collect_experience draft     # docs/ → skills/_inbox/*.md 草稿（半成品，需人工补全）

# B) 从对话历史抽"值得沉淀的事件片段"（默认只列候选、不写文件）
python -m scripts.collect_experience from-chat --top 6 --verbose   # 只看
python -m scripts.collect_experience from-chat --write             # 确认后落进 _inbox/

# 人工过三问、补全四段式后，移到 skills/<kebab-case>/SKILL.md
python -m scripts.collect_experience check
python -m scripts.collect_experience sync
```

> `skills/_inbox/` 是**草稿区**：loader 只认 `*/SKILL.md`，所以草稿再乱也**不会进检索语料**；
> 它同时已加进 `.gitignore`（草稿属于本地素材，不进版本库）。

**`from-chat` 是怎么挑候选的**（三层信号，宁可漏、不要错）：

| 规则 | 说明 |
|---|---|
| 切片段 | 遇到含**现象词**的用户轮就开一段（一次排查通常跨好几轮），片段最多 8 轮 |
| 打分 | **现象**（只在用户提问里找）× **动作** × **验证** 三类信号各 2 分，首问 +1，有长回答 +1 |
| 门槛 | 必须有现象词、至少两类信号；**命中业务/闲聊词就整段丢弃**（业务问答不是开发经验） |
| 去重 | 用**内容词覆盖率**（不是 Jaccard，会被长度差稀释）：与已有技能/草稿、以及**本批候选之间**比，≥0.7 就算重复 |
| 落盘 | 草稿头部标 **AI 抽取 · 未验证**；头部写清来源会话、起始轮次、命中的信号词、打分 |

> **把一段对话变成技能**的正确姿势（两段式 + 一个闸门）：
> ① `from-chat` 自动起草（素材，可以有错、可以有中间态判断）；
> ② 人工过三问 —— **真踩过吗 / 验证指向哪个文件或测试 / 和已有技能重复吗**；
> ③ 补全后移到 `skills/<name>/SKILL.md` → `check` → `sync` → 立刻可被 Agent 命中。
> 关键是第 ② 步不要跳过：会话里的中间判断经常是错的，而技能会被当**硬约束**注入模型
> （一条技能约 846~1345 token，写成垃圾还会挤掉上下文预算）。

### 6.7 看不到效果时的三个排查点

1. **问句里没有触发词** → 路由不会走技能节点（刻意的精准门：宁可漏、不要错）。补一句"有经验吗 / 踩过坑吗"。
2. **`/health` 里 `model` 是 `fake`** → 离线回放模式，回答带 `【离线演示】` 前缀，只能证明"技能进了上下文"；接了真模型才看得到"按经验作答"。
3. **改了技能文件没生效** → 跑一次 `sync`（索引不会自己发现文件变了）。日志里的
   `retrieval.degraded reason=stale` 是**业务知识库**的向量索引过期后的正常降级，与技能库无关。

### 6.8 完整流程（照着做一遍：从对话到技能）

下面这 7 步就是全部流程，**只有第 2、3 步需要人做判断**，其余都是命令。

```powershell
# 0) 起服务（可选，第 5 步验证时要用）
双击 F:\shujuf\code\context-engine-agent\start_all.bat

cd F:\shujuf\code\context-engine-agent\backend

# 1) 起草：先看，再写
..\.venv\Scripts\python.exe -m scripts.collect_experience from-chat --top 6 --verbose  # 只看候选
..\.venv\Scripts\python.exe -m scripts.collect_experience from-chat --write            # 落进 _inbox/
#    （另一条入口：从文档抽  ->  ... collect_experience draft）
#    看什么：分数 / 类别命中 N/3 / 轮数 / 是否标了 ⚠ 重复。标 ⚠ 的先别管。
```

```powershell
# 2) ★闸门（人工）：打开草稿，回答三个问题
notepad F:\shujuf\code\context-engine-agent\skills\_inbox\<那份草稿>.md
#    ① 真踩过吗（能指出当时的报错/现象）？
#    ② 验证指向哪个文件 / 哪条测试？
#    ③ 和已有技能重复吗（重复就合并，不要新增）？
#    过不了就删掉它 —— 这一步是整套流程里唯一的质量关。
```

```powershell
# 3) ★提升：建目录 + 写 SKILL.md（目录名 = front-matter 的 name，kebab-case）
mkdir F:\shujuf\code\context-engine-agent\skills\env-key-placeholder
notepad F:\shujuf\code\context-engine-agent\skills\env-key-placeholder\SKILL.md
#    正文按四段式写：规则 / 反例（现象·根因·修复·验证）/ 自查；控制在 40~80 行
#    「验证」必须指向真实存在的文件或测试，否则这条技能迟早会被发现是编的
```

```powershell
# 4) 校验 + 入库
..\.venv\Scripts\python.exe -m scripts.collect_experience check   # 期望：[OK] env-key-placeholder
..\.venv\Scripts\python.exe -m scripts.collect_experience sync     # 期望：变化 ['env-key-placeholder']
```

```powershell
# 5) 验证命中（页面上问一句，必须带触发词：经验/坑/技能库/教训/skill）
#    问「我把 .env 里的 key 写成占位符，请求全失败，有经验吗」→ 看三处证据：
#      ① Agent 链：skill 技能命中 1 条，注入上下文 1 条 | injected skill:env-key-placeholder
#      ② 上下文面板：技能（开发经验） prio 115
#      ③ 回答：按这条技能的规则作答
#    不想开界面也可以：GET /api/skills 看列表；POST /api/chat 看 data.skills
```

```powershell
# 6) 维护
#    改内容 → 把 front-matter 的 version +1、updated 改当天 → check → sync
#    想立刻生效：页面「技能」页点「重新同步语料」（刷新进程内缓存，不用重启服务）
#    废弃：status 改 deprecated（保留在库里，但不再参与匹配）
```

**每一步的卡点**：第 1 步没候选 → 那段对话里没有"现象词"（换个说法再问一次）；第 4 步 `check` 报跳过 → 看它给的原因（缺字段 / name 与目录名不一致）；第 5 步没命中 → 问句缺触发词，或忘了 `sync`，或服务还是旧进程。
