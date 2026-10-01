"""Model backend factory (requirement #3 inference wiring).

除了"选后端"，这里还承担一件事：**降级必须能自证原因**。

只填了 ``.env`` 的 key、却没装 ``requirements-llm.txt`` 时，项目会**静默退回**离线
fake 模型：界面徽章照样写着 ``qwen_api``，回答却全是【离线演示】。这个坑踩过一次，
所以：

* ``LAST_DEGRADE`` 记下"想用哪个后端、为什么没起来"；
* ``probe_degrade()`` 启动时探一次（只做**导入**检查，不构造实例 —— 真模型加载很贵）；
* ``degrade_notice()`` 给启动横幅与 ``/health`` 用。

（与向量索引的 ``_DEPS_ERROR`` 是同一套做法：失败原因留下来，而不是只给一个 unavailable。）
"""
from __future__ import annotations

from .. import config
from .base import ModelBackend

#: 最近一次降级原因（空串 = 没降级）
LAST_DEGRADE = ""

#: 后端名 -> 模块名 / 类名
_MODULE = {
    "qwen_api": "app.models.qwen_api",
    "deepseek_api": "app.models.deepseek_api",
    "local_ft": "app.models.local_ft",
}
_CLASS = {
    "app.models.qwen_api": "QwenApiModel",
    "app.models.deepseek_api": "DeepSeekApiModel",
    "app.models.local_ft": "LocalFTModel",
}


def get_model_backend(backend: str | None = None) -> ModelBackend:
    wanted = backend or config.effective_chat_backend()
    module = _MODULE.get(wanted)
    if module is None:          # 配置就是 fake（离线演示）
        _clear()
        from .fake import FakeModel
        return FakeModel()
    return _safe(module, wanted)


def _safe(module: str, wanted: str) -> ModelBackend:
    """真后端构造失败（缺 key / 缺依赖）就退回 FakeModel，并**记下**原因。"""
    global LAST_DEGRADE
    try:
        model = __import__(module, fromlist=[_CLASS[module]]).__dict__[_CLASS[module]]()
        _clear()
        return model
    except Exception as exc:
        LAST_DEGRADE = (
            f"{wanted} 起不来（{exc.__class__.__name__}: {exc}），实际用的是离线 fake 模型"
        )
        from .fake import FakeModel
        return FakeModel()


def _clear() -> None:
    global LAST_DEGRADE
    LAST_DEGRADE = ""


def probe_degrade() -> str:
    """启动时探一次：配置的对话后端能不能导入。返回一行原因（空串 = 没问题）。

    只做导入检查、**不构造实例**：``local_ft`` 真的加载模型要几十秒，
    启动横幅不能把服务卡住。
    """
    global LAST_DEGRADE
    wanted = config.effective_chat_backend()
    module = _MODULE.get(wanted)
    if module is None:
        _clear()
        return ""
    try:
        __import__(module)
        _clear()
    except Exception as exc:
        LAST_DEGRADE = (
            f"{wanted} 起不来（{exc.__class__.__name__}: {exc}），实际用的是离线 fake 模型"
        )
    return LAST_DEGRADE


def degrade_reason() -> str:
    """一行原因（``/health`` 的 ``chat_degraded_reason`` 用）。"""
    return LAST_DEGRADE


def degrade_notice() -> str:
    """给人看的排查提示（启动横幅用）；没降级返回空串。"""
    if not LAST_DEGRADE:
        return ""
    # 修复建议要跟着后端走：DeepSeek 用 requests 直连，**不需要装依赖**，
    # 让用户去 pip install 只会白折腾一轮。
    wanted = config.effective_chat_backend()
    fix = (
        "在 backend/.env 里填 DEEPSEEK_API_KEY（这个后端不需要额外依赖）"
        if wanted == "deepseek_api"
        else "pip install -r requirements-llm.txt（只填 .env 里的 key 不够）"
    )
    return (
        "[警告] 配置的对话后端没有生效，回答会是【离线演示】（只回放上下文，不生成真实答案）。\n"
        f"       原因：{LAST_DEGRADE}\n"
        "       排查：① 用哪个解释器启动的？应该用项目自己的 .venv\\Scripts\\python.exe\n"
        f"             ② {fix}\n"
        "             ③ 确认：看 /health 的 model 字段，而不是 chat_backend"
    )
