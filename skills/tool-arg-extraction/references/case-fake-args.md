# 案例：假参数（整句用户输入当参数）

> 来源：本仓库真实修复记录（见 `docs/ai-assisted.md` §3 第 3 条）。
> 这条案例对应技能 `tool-arg-extraction` 的反例 ①。

## 现象

工具调用"成功"了，但答案是错的：

```
调用工具 get_weather
args: {"city": "北京今天天气怎么样"}
result: 未找到城市「北京今天天气怎么样」的坐标
```

当时的判断是"网络问题"，实际是**参数抽取这一步从来没做**。

## 根因

`function calling` 有三步：**决定调哪个工具 → 产出 arguments → 执行**。
旧实现只做了第 1 步和第 3 步，把用户原话直接塞进第 1 个参数位置——
参数类型没错（都是 string），所以**调用不报错**，错误被推迟到工具内部，
表现成"查询失败"而不是"参数错误"。

## 修复

```python
# backend/app/agents/tools.py
def extract_args(name: str, user_input: str) -> dict:
    if name == "get_weather":
        city = _extract_city(user_input)
        return {"city": city} if city else {}
    if name == "calculator":
        expr = _extract_expression(user_input)
        return {"expression": expr} if expr else {}
    return {}
```

抽不到参数时由编排层追问：

```python
# backend/app/agents/orchestrator.py
if tool.params and not args:
    result = self._missing_args_hint(name)   # "没能从提问里识别出城市名，请补充城市"
```

## 验证

- `backend/tests/test_core.py`：城市抽取（含「深圳明天会下雨吗」这类没写"天气"的问法）、
  算式抽取（全角括号、中文运算符、"加绒"误判）。
- `backend/eval/dataset.json` 的 `tool_args` 类（7 题）：比对**计算结果**而不是写法，
  因为 `(18+6)*3` 与 `18+6*3` 是两回事。

## 教训（可迁移）

> **"跑通了"不等于"跑对了"**——参数类型合法、调用不报错，错误会以"结果不对"的形式
> 出现在下游。凡是从自然语言到结构化参数的这一步，都要有**反例测试**。
