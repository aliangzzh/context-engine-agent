---
name: silent-exception-swallow
description: 写异常处理时必须让失败可观测（HTTP 状态码 / 业务错误码 / 日志 / 降级标记），不要用 except Exception: return {} 把错误吞掉，让问题以"结果不对"的形式出现在下游。
tags: [error-handling, observability, api]
trigger: [异常, 错误处理, 静默, 吞掉, 降级, 错误码, except, try]
stack: [python]
status: active
version: 1
updated: 2026-09-30
---

# 不要让异常被静默吞掉

## 规则（检查清单）

1. **坏请求 → 显式 400 + 业务错误码**，不要返回空对象让调用方自己猜（`app/errors.py`）。
2. **降级/超限 → 如实上报**：预算超了报 `over_budget`，向量路降级报 `last_degrade` /
   `retrieval_effective`，依赖缺失报 `missing_deps`。**不静默**。
3. **兜底 `except` 只允许出现在统一入口一处**（`api.safe_call`），并且必须写日志
   （`request_id` + 错误码），否则线上只剩"接口 500"没有线索。
4. **兜底返回值必须是可解释的人话**，不能是空 dict / 空列表；否则下游会拿着空数据继续跑，
   把"失败"变成"结果不对"。
5. **每条修复配一条测试**，尤其是失败路径（回滚、降级、边界）。

## 反例（本仓库真实发生过）

**① `except Exception: return {}` 吞掉坏请求**

- 现象：非法参数请求"成功"返回，前端拿到空数据，用户看到空白页
- 根因：AI 习惯性地写宽泛兜底，把错误路径变成了正常路径
- 修复：显式 `400 + 40001`，错误码分段（`40xxx` 调用方 / `50xxx` 服务端 / `502xx` 上游）
- 验证：`backend/tests/test_api.py`（含"分页 page=0 必须 400"这类边界）

**② 超预算被静默突破**

- 现象：上下文超出 token 预算，但没有任何地方报出来
- 根因：裁剪后只更新了 `total_tokens`，没告知"被裁了多少"
- 修复：`Context.trimmed` + `Context.over_budget`（`app/schemas.py`），由后端算、前端不自己判断
- 验证：`tests/test_core.py` 的预算裁剪用例（含"只剩 system 槽仍超预算"）

**③ 向量依赖缺失时只说 unavailable，查不出原因**

- 现象：`/health` 显示 `unavailable`，但分不清"包没装"还是"包在但深层导入炸了"
- 根因：依赖探测只返回布尔，丢掉异常
- 修复：`_DEPS_ERROR` + `missing_deps` / `deps_error` 进 `describe()`
- 验证：`tests/test_core.py` 的降级用例

## 怎么自查你正在犯这个错

- 全局搜 `except Exception`，看后面是不是 `return {}` / `return None` / `pass`
- 问一句：**这条失败路径，线上出问题时我能从日志或 /health 看出来吗？**
- 失败路径有没有测试？（没有测试的失败路径 = 没实现的失败路径）
