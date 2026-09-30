"""DeepSeek 后端：协议解析 + 配置选择（**不联网**，全部打桩）。

为什么值得单独测：这个后端是手写 HTTP + 手解 SSE，最容易错的地方不在"能不能调通"，
而在**边界**——HTTP 非 200、响应结构变了、流里混进半包/心跳行。
这些在真机上一旦出现就是"偶发失败"，用打桩测最省事。
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))

os.environ.setdefault("LOG_LEVEL", "CRITICAL")

from app import config
from app import models as models_mod


class _Resp:
    """够用的假响应：支持 .status_code / .json() / .iter_lines() / with。"""

    def __init__(self, status: int = 200, payload: dict | None = None, lines: list[str] | None = None):
        self.status_code = status
        self._payload = payload or {}
        self._lines = lines or []
        self.text = json.dumps(self._payload, ensure_ascii=False) if payload is not None else "mock body"

    def json(self) -> dict:
        return self._payload

    def iter_lines(self):
        return iter([line.encode("utf-8") for line in self._lines])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class DeepSeekProtocolTest(unittest.TestCase):
    """协议层：请求形状 + 响应解析 + 失败不静默。"""

    def setUp(self):
        self._saved = {
            k: getattr(config, k)
            for k in ("DEEPSEEK_API_KEY", "DEEPSEEK_CHAT_MODEL", "DEEPSEEK_BASE_URL")
        }
        config.DEEPSEEK_API_KEY = "sk-test"
        config.DEEPSEEK_CHAT_MODEL = "deepseek-flash"
        config.DEEPSEEK_BASE_URL = "https://api.deepseek.com"

    def tearDown(self):
        for key, value in self._saved.items():
            setattr(config, key, value)

    def _model(self):
        from app.models.deepseek_api import DeepSeekApiModel

        return DeepSeekApiModel()

    def test_generate_sends_openai_compatible_request(self):
        resp = _Resp(payload={"choices": [{"message": {"content": "这是答案"}}]})
        with patch("requests.post", return_value=resp) as post:
            out = self._model().generate([{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}])

        self.assertEqual(out, "这是答案")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.deepseek.com/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(kwargs["json"]["model"], "deepseek-flash")
        self.assertFalse(kwargs["json"]["stream"])
        self.assertEqual(len(kwargs["json"]["messages"]), 2)

    def test_generate_raises_on_http_error(self):
        with patch("requests.post", return_value=_Resp(status=401, payload={"error": "bad key"})):
            with self.assertRaises(RuntimeError) as ctx:
                self._model().generate([{"role": "user", "content": "hi"}])
        self.assertIn("401", str(ctx.exception))

    def test_generate_raises_on_unexpected_shape(self):
        with patch("requests.post", return_value=_Resp(payload={"unexpected": True})):
            with self.assertRaises(RuntimeError) as ctx:
                self._model().generate([{"role": "user", "content": "hi"}])
        self.assertIn("结构异常", str(ctx.exception))

    def test_stream_parses_sse_and_stops_at_done(self):
        lines = [
            'data: {"choices":[{"delta":{"content":"你"}}]}',
            "",                                              # 空行（心跳）
            "event: ping",                                   # 非 data 行
            'data: {"choices":[{"delta":{"content":"好"}}]}',
            "data: [DONE]",
            'data: {"choices":[{"delta":{"content":"不该出现"}}]}',
        ]
        with patch("requests.post", return_value=_Resp(lines=lines)):
            out = "".join(self._model().stream([{"role": "user", "content": "hi"}]))
        self.assertEqual(out, "你好")

    def test_stream_survives_half_broken_line(self):
        lines = [
            'data: {"choices":[{"delta":{"content":"前"}}]}',
            'data: {"choices":[{"delta":',                    # 半包/截断
            'data: {"choices":[{"delta":{"content":"后"}}]}',
        ]
        with patch("requests.post", return_value=_Resp(lines=lines)):
            out = "".join(self._model().stream([{"role": "user", "content": "hi"}]))
        self.assertEqual(out, "前后")

    def test_missing_key_raises_at_construction(self):
        config.DEEPSEEK_API_KEY = ""
        from app.models.deepseek_api import DeepSeekApiModel

        with self.assertRaises(RuntimeError) as ctx:
            DeepSeekApiModel()
        self.assertIn("DEEPSEEK_API_KEY", str(ctx.exception))

    def test_placeholder_key_is_rejected_with_human_message(self):
        """中文占位符 key（.env 里很容易留下）要给出人话原因。

        真实踩过：`.env` 里写了 `DEEPSEEK_API_KEY=sk-你的key`，而它会被塞进
        Authorization 头 → requests 只接受 latin-1 → 报
        "UnicodeEncodeError: 'latin-1' codec can't encode..."，完全看不懂。
        """
        config.DEEPSEEK_API_KEY = "sk-你的key"
        from app.models.deepseek_api import DeepSeekApiModel

        with self.assertRaises(RuntimeError) as ctx:
            DeepSeekApiModel()
        message = str(ctx.exception)
        self.assertIn("非 ASCII", message)
        self.assertIn("platform.deepseek.com", message)


class ChatBackendSwitchTest(unittest.TestCase):
    """配置层：显式开关 + 隐式优先级 + 降级自证。"""

    def setUp(self):
        self._saved = {
            k: getattr(config, k)
            for k in ("CHAT_BACKEND", "DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY", "FT_OUTPUT_ADAPTER")
        }
        config.CHAT_BACKEND = "auto"
        config.DASHSCOPE_API_KEY = ""
        config.DEEPSEEK_API_KEY = ""
        config.FT_OUTPUT_ADAPTER = Path("F:/__no_such_adapter__")
        models_mod._clear()

    def tearDown(self):
        for key, value in self._saved.items():
            setattr(config, key, value)
        models_mod._clear()

    def test_deepseek_is_selected_when_only_its_key_exists(self):
        config.DEEPSEEK_API_KEY = "sk-test"
        self.assertEqual(config.effective_chat_backend(), "deepseek_api")

    def test_qwen_still_wins_in_auto_when_both_keys_exist(self):
        """保持旧行为：auto 下通义优先（想用 DeepSeek 就显式指定）。"""
        config.DASHSCOPE_API_KEY = "sk-qwen"
        config.DEEPSEEK_API_KEY = "sk-deepseek"
        self.assertEqual(config.effective_chat_backend(), "qwen_api")

    def test_explicit_switch_overrides_keys(self):
        config.DASHSCOPE_API_KEY = "sk-qwen"
        config.DEEPSEEK_API_KEY = "sk-deepseek"
        config.CHAT_BACKEND = "deepseek_api"
        self.assertEqual(config.effective_chat_backend(), "deepseek_api")
        config.CHAT_BACKEND = "fake"
        self.assertEqual(config.effective_chat_backend(), "fake")
        self.assertEqual(models_mod.get_model_backend().name, "fake")
        self.assertEqual(models_mod.degrade_reason(), "", "主动选 fake 不算降级")

    def test_explicit_deepseek_without_key_degrades_honestly(self):
        config.CHAT_BACKEND = "deepseek_api"
        model = models_mod.get_model_backend()
        self.assertEqual(model.name, "fake")
        reason = models_mod.degrade_reason()
        self.assertIn("deepseek_api", reason)
        self.assertIn("DEEPSEEK_API_KEY", models_mod.degrade_notice())


if __name__ == "__main__":
    unittest.main()
