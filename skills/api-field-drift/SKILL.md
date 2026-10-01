---
name: api-field-drift
description: 改接口返回字段（含 SSE 事件 payload）时必须同步前端类型定义与页面读取，否则页面会静默不显示数据——这类问题类型检查和"真跑一遍"才能发现，读代码看不出来。
tags: [api, frontend, sse, contract]
trigger: [字段, 接口, 前后端, sse, 类型, 字段名, 契约, 前端]
stack: [python, vue, typescript]
status: active
version: 1
updated: 2026-09-30
---

# 接口字段名漂移（前后端契约）

## 规则（检查清单）

1. 后端返回的键名就是**契约**：本项目统一 `snake_case`（`used_tools` / `agent_trace` /
   `kb_chunks`），前端类型与页面读取必须跟着它，不要在前端"顺手改成驼峰"。
2. 改字段要**同时**改四处：后端 handler / 前端类型定义 / 页面读取 / mock 数据。
3. **SSE 事件是接口的一部分**：`agent` / `retrieved` / `token` / `done` / `error` 的
   `data` 结构变了，前端 `streamChat` 的解析必须同步。
4. **别用 `?? []` / `|| []` 掩盖字段名错误**——那会把"字段名写错"变成"就是没数据"，
   把显式 bug 变成静默 bug。
5. 用两道网兜住：`vue-tsc` 类型检查（构建必跑）+ 真起服务的接口测试（`tests/test_api.py`）。

## 反例（本仓库真实发生过）

**SSE 发 `used_tools`，前端读 `usedTools`**

- 现象：对话页的"工具调用"面板永远空的，但后端 trace 里明明有工具
- 根因：前端自己发明了驼峰键名，类型是 `string[]` 所以类型检查也不报错
  （`usedTools` 是合法标识符，只是取不到值）
- 修复：`frontend/src/api/index.ts` 的类型与 `ChatView.vue` 的读取都改成后端原键 `used_tools`
- 验证：`npm run typecheck`（vue-tsc）+ `backend/tests/test_api.py` 对 SSE / JSON 结构的断言

## 怎么自查你正在犯这个错

- 页面上某块数据"永远不显示"，但接口返回值里有 → 先对键名，别先怀疑逻辑
- 前端类型定义里的键名和后端 `model_dump()` 出来的键名，**肉眼比一遍**
- 前端有没有 `?? []` / `|| {}` 这种"防御性默认值"？它们最容易藏字段名错误
