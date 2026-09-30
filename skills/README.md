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

```bash
python -m scripts.collect_experience draft     # docs/ → skills/_inbox/*.md 草稿（半成品，需人工补全）
# 补全 TODO、删掉草稿注释后，移到 skills/<kebab-case>/SKILL.md
python -m scripts.collect_experience check
python -m scripts.collect_experience sync
```

> `skills/_inbox/` 是**草稿区**：loader 只认 `*/SKILL.md`，所以草稿再乱也**不会进检索语料**；
> 它同时已加进 `.gitignore`（草稿属于本地素材，不进版本库）。
>
> **把一段对话变成技能**（目前是手工闭环，`draft --from-chat` 还没做）：
> ① 把「来源会话 + 问题 + 回答要点 + 证据」记成一份草稿（原始素材，什么都有）；
> ② 压成四段式（现象 / 根因 / 修复 / 验证），仍放 `_inbox/`，**标清 TODO**；
> ③ 补全后移到 `skills/<name>/SKILL.md` → `check` → `sync` → 立刻可被 Agent 命中。
> 关键是第 ② 步不要跳过：原始问答直接当技能会变成垃圾堆，还会挤掉上下文预算（一条技能约 846 token）。

### 6.7 看不到效果时的三个排查点

1. **问句里没有触发词** → 路由不会走技能节点（刻意的精准门：宁可漏、不要错）。补一句"有经验吗 / 踩过坑吗"。
2. **`/health` 里 `model` 是 `fake`** → 离线回放模式，回答带 `【离线演示】` 前缀，只能证明"技能进了上下文"；接了真模型才看得到"按经验作答"。
3. **改了技能文件没生效** → 跑一次 `sync`（索引不会自己发现文件变了）。日志里的
   `retrieval.degraded reason=stale` 是**业务知识库**的向量索引过期后的正常降级，与技能库无关。
