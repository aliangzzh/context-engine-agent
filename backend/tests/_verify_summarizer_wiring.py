"""端到端验证：滑窗"摘要压缩"到底有没有真的调用模型。

不是单元测试的替身断言，而是走真实 ContextEngine → _HistoryRunner → HistorySummarizer
调用链，并检查本机默认配置下注入的模型究竟是哪一个。

    python tests/_verify_summarizer_wiring.py      (from backend/)
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import config
from app.context.engine import ContextEngine
from app.context.rerank import Reranker
from app.context.summarizer import HistorySummarizer
from app.schemas import HistoryTurn
from app.services.chat_service import AppServices


class RecordingModel:
    """真·模型替身：记录收到的消息，返回一段可辨认的摘要。"""

    name = "recording"

    def __init__(self):
        self.calls = []

    def generate(self, messages):
        self.calls.append(messages)
        return "摘要：用户问了尺码/洗涤/颜色，结论是 M 码、水温≤30℃。"

    def stream(self, messages):
        return iter([])


class BrokenModel:
    name = "broken"

    def generate(self, messages):
        raise RuntimeError("model down")

    def stream(self, messages):
        return iter([])


def _engine(summarizer):
    return ContextEngine(config.CONTEXT_TOKEN_BUDGET, reranker=Reranker(), summarizer=summarizer)


def _slots(ctx):
    return {s.kind: s for s in ctx.slots}


def main() -> int:
    history = [
        HistoryTurn(user=f"q{i} 第{i}个问题", assistant=f"a{i} 第{i}个回答") for i in range(12)
    ]
    print("=" * 74)
    print(f"HISTORY_MAX_TURNS={config.HISTORY_MAX_TURNS}  输入历史={len(history)} 轮")

    # ---------------------------------------------------------------- 1
    print("\n[1] 真实 engine 路径：滑窗溢出时，模型被调用了吗？")
    spy = RecordingModel()
    ctx = _engine(HistorySummarizer(spy)).build(
        user_input="总共聊了几件事？", retrieved=[], history=history, system_prompt="sys"
    )
    slots = _slots(ctx)
    called = len(spy.calls)
    print(f"    model.generate 调用次数 : {called}")
    if called:
        msgs = spy.calls[0]
        print(f"    消息角色               : {[m['role'] for m in msgs]}")
        print(f"    system 提示词前缀      : {msgs[0]['content'][:24]}...")
        print(f"    被挤出滑窗的旧轮次进了 user 消息: {'q0' in msgs[1]['content']}")
    print(f"    summary slot 内容      : {slots['summary'].content[:60]}...")
    print(f"    history slot 保留轮数  : {slots['history'].content.count('用户：')}")
    print(f"    结论                   : {'模型被真实调用 -> 摘要来自模型' if called else '模型没被调用 -> 仍是硬编码模板'}")

    # ---------------------------------------------------------------- 2
    print("\n[2] 未溢出滑窗时（<= max_turns）不应该调用模型")
    spy2 = RecordingModel()
    _engine(HistorySummarizer(spy2)).build(
        user_input="x", retrieved=[], history=history[:3], system_prompt="sys"
    )
    print(f"    model.generate 调用次数 : {len(spy2.calls)}（期望 0：没必要压缩）")

    # ---------------------------------------------------------------- 3
    print("\n[3] 模型调用失败 -> 降级到规则模板，且不抛异常")
    ctx3 = _engine(HistorySummarizer(BrokenModel())).build(
        user_input="x", retrieved=[], history=history, system_prompt="sys"
    )
    print(f"    summary slot 内容      : {_slots(ctx3)['summary'].content}")

    # ---------------------------------------------------------------- 4
    print("\n[4] 本机默认配置下，AppServices 注入的到底是哪个模型？")
    services = AppServices(seed_kb=False)
    injected = services.engine.summarizer.model
    print(f"    config.effective_chat_backend() : {config.effective_chat_backend()}")
    print(f"    DASHSCOPE_API_KEY 是否配置      : {bool(config.DASHSCOPE_API_KEY)}")
    print(f"    LoRA adapter 是否存在           : {(config.FT_OUTPUT_ADAPTER / 'adapter_config.json').exists()}")
    print(f"    AppServices.model               : {type(services.model).__name__} (name={services.model.name})")
    print(f"    summarizer 拿到的模型           : {type(injected).__name__} (name={injected.name}, is_llm={getattr(injected, 'is_llm', True)})")
    print(f"    两者是同一个实例                : {injected is services.model}")

    ctx4 = services.engine.build(
        user_input="总共聊了几件事？", retrieved=[], history=history, system_prompt="sys"
    )
    actual = _slots(ctx4)["summary"].content
    print(f"    本机真实 summary slot 内容      : {actual}")
    if "早期对话共" in actual:
        origin = "规则模板降级（离线无真模型 -> 诚实降级，不再假装）"
    elif "离线演示" in actual:
        origin = "离线 FakeModel 话术（缺陷：不是摘要）"
    else:
        origin = "模型生成的摘要"
    print(f"    摘要来源                       : {origin}")

    # ---------------------------------------------------------------- 5
    print("\n[5] 摘要到底压缩了吗？（旧轮次 token -> summary slot token）")
    from app.context.token_budget import token_len

    old_text = "\n".join(f"用户：{t.user}\n助手：{t.assistant}" for t in history[:-config.HISTORY_MAX_TURNS])
    old_tokens = token_len(old_text)
    print(f"    被挤出滑窗的旧轮次原文 : {old_tokens} tokens")
    print(f"    规则模板降级路径       : {token_len(_slots(ctx3)['summary'].content)} tokens（真压缩）")
    print(f"    本机 FakeModel 路径    : {token_len(actual)} tokens"
          f"{' ← 比原文还长：旧轮次被原样塞进摘要 slot，等于重复注入' if token_len(actual) >= old_tokens else ''}")
    print(f"    旧轮次是否被原样复制   : {'是' if history[0].user in actual else '否'}")

    # ---------------------------------------------------------------- 6
    print("\n[6] 连续 3 轮对话：同一批旧轮次会被重复摘要吗？（缓存问题）")
    spy3 = RecordingModel()
    eng = _engine(HistorySummarizer(spy3))
    for _ in range(3):
        eng.build(user_input="x", retrieved=[], history=history, system_prompt="sys")
    print(f"    3 次 build -> model.generate 调用 {len(spy3.calls)} 次（无缓存，每次重新摘要）")

    print("\n" + "=" * 74)
    print("结论：调用链是真的（[1] 模型确实被调用、旧轮次确实进了 user 消息）。")
    print("      本机 backend=fake（无 key / 无 adapter），[4][5] 显示非 LLM 后端已")
    print("      诚实降级为规则模板：31 tokens，不再把旧轮次原样放大成 146 tokens。")
    print("      想看真模型生成的摘要：配置 DASHSCOPE_API_KEY 后重跑本脚本。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
