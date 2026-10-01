"""对话后端降级：必须能自证原因。

背景（本仓库真实踩过）：只填了 ``.env`` 的 ``DASHSCOPE_API_KEY``、却没装
``requirements-llm.txt`` 时，项目会**静默退回离线 fake 模型** —— 界面徽章写着
``qwen_api``，回答却全是【离线演示】，只能靠猜。所以这里锁住三件事：

* ``probe_degrade()`` 能探出"配了但起不来"并给出原因；
* ``degrade_notice()`` 的提示里带**修复步骤**（解释器 + 装依赖 + 看哪个字段）；
* ``/health`` 有一个字段能把原因说出去（``chat_degraded_reason``）。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

os.environ.setdefault("LOG_LEVEL", "CRITICAL")

from app import config
from app import models as models_mod
from app.schemas import Health

_MISSING = "app.models.__not_installed__"


class ChatBackendDegradeTest(unittest.TestCase):
    def setUp(self):
        self._eff = config.effective_chat_backend
        self._module = models_mod._MODULE["qwen_api"]
        models_mod._clear()

    def tearDown(self):
        config.effective_chat_backend = self._eff
        models_mod._MODULE["qwen_api"] = self._module
        models_mod._clear()

    def _pretend_key_without_deps(self):
        """模拟"配了 key 但依赖没装"：配置层说 qwen_api，模块却导不进来。"""
        config.effective_chat_backend = lambda: "qwen_api"
        models_mod._MODULE["qwen_api"] = _MISSING

    def test_health_exposes_degrade_reason_field(self):
        self.assertIn("chat_degraded_reason", Health.model_fields)

    def test_probe_reports_import_failure(self):
        self._pretend_key_without_deps()
        reason = models_mod.probe_degrade()
        self.assertIn("qwen_api", reason)
        self.assertIn("__not_installed__", reason)

    def test_notice_carries_the_fix_steps(self):
        self._pretend_key_without_deps()
        models_mod.probe_degrade()
        notice = models_mod.degrade_notice()
        self.assertIn("requirements-llm.txt", notice)
        self.assertIn(".venv", notice)
        self.assertIn("model", notice)      # 明确告诉人去看 /health 的 model 字段

    def test_fallback_model_is_fake_and_reason_recorded(self):
        self._pretend_key_without_deps()
        model = models_mod.get_model_backend()
        self.assertEqual(model.name, "fake")
        self.assertTrue(models_mod.degrade_reason())

    def test_no_notice_when_config_is_fake(self):
        config.effective_chat_backend = lambda: "fake"
        self.assertEqual(models_mod.probe_degrade(), "")
        self.assertEqual(models_mod.degrade_notice(), "")
        self.assertEqual(models_mod.get_model_backend().name, "fake")


if __name__ == "__main__":
    unittest.main()
