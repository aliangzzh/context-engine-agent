"""Agent 效果评测跑分器（零依赖，stdlib only）。

用法（在 backend/ 下执行）：

    python -m eval.run                    # 跑全部 30 题，打印分类指标 + 失败明细
    python -m eval.run --verbose          # 连通过的用例也打印实际信号
    python -m eval.run --category guard    # 只跑某一类
    python -m eval.run --save-baseline    # 把本次指标冻结为 baseline.json
    python -m eval.run --check            # 与 baseline.json 对比，回退则 exit 1（CI 回归门）
    python -m eval.run --strategy fixed   # 换切分策略跑同一套题（做消融对比）

设计要点
--------
* **隔离**：语料来自 ``eval/corpus/``（10 篇，含 4 篇干扰文档），在 ``eval/_run/`` 下
  重建一套独立的 kb.json + SQLite，绝不碰 ``backend/data/`` 里线上/演示数据。
  所以同一个 commit 在任何机器上跑出的分都一样。
* **确定性**：天气工具替换为本地桩函数（真实 Open-Meteo 会因网络抖动让分数不稳定），
  计算器 / 时间 / 检索 / 上下文装配全部走项目真实实现。
* **可归因**：每条用例记录 expected 与 actual（路由计划、工具参数、检索排序、答案），
  失败原因写成人话，而不是只给一个百分比。
* **可回归**：``--check`` 把指标与 baseline 对比，任何一项掉超过阈值就非零退出，
  可直接挂进 CI，防止"改一处、坏一处"。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 评测输出保持干净：除非外部显式要求，不要打业务日志
os.environ.setdefault("LOG_LEVEL", "CRITICAL")

from app import config  # noqa: E402
from app.agents import tools as tools_mod  # noqa: E402
from app.agents.orchestrator import AgentOrchestrator  # noqa: E402
from app.agents.tools import calculator  # noqa: E402
from app.context.engine import ContextEngine  # noqa: E402
from app.context.history import ChatStore, HistoryManager  # noqa: E402
from app.context.rerank import Reranker  # noqa: E402
from app.context.summarizer import HistorySummarizer  # noqa: E402
from app.models.fake import FakeModel  # noqa: E402
from app.retrieval.knowledge import KnowledgeBase  # noqa: E402
from app.retrieval.retriever import Retriever  # noqa: E402
from app.retrieval.vector_index import VectorIndex  # noqa: E402
from app.storage.cache import get_cache  # noqa: E402
from app.storage.repo import KbRepository  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
CORPUS_DIR = EVAL_DIR / "corpus"
RUN_DIR = EVAL_DIR / "_run"
DATASET_PATH = EVAL_DIR / "dataset.json"
BASELINE_PATH = EVAL_DIR / "baseline.json"
REPORTS_DIR = EVAL_DIR / "reports"

#: 离线（fake 模型）下"知识库不覆盖"时模型的兜底话术；接真实模型后同一口径仍适用
ABSTAIN_WORDS = (
    "没有找到", "未收录", "暂无", "无法回答", "没有相关", "资料不足",
    "没有提供", "空检索",
)
ASK_ARG_WORDS = ("请补充", "补充城市", "请提供城市", "没能从提问里识别")

_SRC_RE = re.compile(r"^\[(.+?)\]")


def install_weather_stub() -> None:
    """把真实天气 API 换成确定性桩，只影响评测进程，不改项目代码。"""

    def _stub(city: str = "") -> str:
        city = (city or "").strip()
        if not city:
            return "请提供城市名"
        return f"{city}：晴，当前温度 20°C（离线评测桩）"

    tools_mod.TOOLS["get_weather"].func = _stub


class Harness:
    """评测台：离线装配与线上一致的链路（检索 → 路由 → 工具 → 上下文 → 生成）。

    作为上下文管理器使用时，退出会还原被替换的天气工具并清空检索缓存，
    避免评测污染同一进程里的其它测试。
    """

    def __init__(self, *, strategy: str | None = None, retrieval: str | None = None,
                 run_dir: Path = RUN_DIR) -> None:
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir = run_dir
        self.strategy = (strategy or config.CHUNK_STRATEGY).lower()

        self._orig_weather = tools_mod.TOOLS["get_weather"].func
        install_weather_stub()
        get_cache().clear()

        # 评测必须**确定性**：默认锁 bm25，不跟随本地 RETRIEVAL_BACKEND。
        # 否则本机装了 faiss + 配了 key 时跑出的是向量结果，与冻结基线不可比，
        # 回归门就变成了"换台机器就红"的随机门。
        # 要做检索方案对比（bm25 / dashscope / hybrid），用 --retrieval 显式指定。
        self.retrieval = (retrieval or "bm25").lower()
        self.retriever = Retriever(kb_path=run_dir / "kb.json", backend=self.retrieval)
        # 评测用**独立**索引目录：FAISS_PERSIST_DIR 是全局的，不隔离的话
        # 跑一次 --retrieval hybrid 就会把线上索引覆盖成评测语料的索引。
        self.retriever.vector = VectorIndex(index_dir=run_dir / "faiss")
        self.repo = KbRepository(db_path=run_dir)
        self.kb = KnowledgeBase(self.retriever, self.repo)
        self.corpus: list[dict] = []
        for path in sorted(CORPUS_DIR.glob("*.txt")):
            res = self.kb.ingest_file(path, source=path.name)
            self.corpus.append({"source": path.name, **res})
        get_cache().clear()

        self.model = FakeModel()
        self.engine = ContextEngine(
            config.CONTEXT_TOKEN_BUDGET,
            reranker=Reranker(),
            summarizer=HistorySummarizer(self.model),
        )
        self.store = ChatStore(run_dir / "chat_history")

    # -- lifecycle -----------------------------------------------------------------
    def __enter__(self) -> "Harness":
        return self

    def __exit__(self, *exc_info) -> None:
        tools_mod.TOOLS["get_weather"].func = self._orig_weather
        get_cache().clear()

    # -- single case ---------------------------------------------------------------
    def ask(self, case: dict) -> dict:
        session_id = f"eval-{case['id']}"
        history = HistoryManager(
            self.store, session_id,
            max_turns=config.HISTORY_MAX_TURNS,
            summary_tokens=config.HISTORY_SUMMARY_TOKENS,
        )
        orch = AgentOrchestrator(self.retriever, self.model, history, self.engine)
        res = orch.generate(case["question"], session_id)

        plan = [p["name"] for p in orch.plan(case["question"]) if p["name"] != "writer"]
        tool_steps = []
        for step in res.trace.to_list():
            if step.get("kind") != "tool":
                continue
            tool_steps.append({
                "name": str(step.get("summary", "")).replace("调用工具 ", "").strip(),
                "args": step.get("detail", {}).get("args", {}),
                "result": str(step.get("detail", {}).get("result", "")),
            })
        context_sources = []
        for slot in res.context.slots:
            if slot.kind != "retrieval":
                continue
            m = _SRC_RE.match(slot.content or "")
            if m:
                context_sources.append(m.group(1))

        return {
            "plan": plan,
            "tool_steps": tool_steps,
            "sources": [c.source for c in res.retrieved],
            "scores": [round(float(c.score or 0.0), 4) for c in res.retrieved],
            "context_sources": context_sources,
            "answer": res.answer,
            "tool_text": " ".join(s["result"] for s in tool_steps),
        }


# --- 打分 ------------------------------------------------------------------------
def strip_question_echo(answer: str, question: str) -> str:
    """去掉答案里对用户原话的回显再判分。

    fake 模型（以及真实模型偶尔）会把用户问题抄进答案，比如
    ``...（问题：你们支持花呗分期付款吗？）``。若直接判 forbid，会把"用户自己
    问的话"算成"模型编造的内容"，那是评分器的错，不是模型的错。
    """
    return (answer or "").replace(question, "")


def score_case(case: dict, obs: dict) -> tuple[bool, str]:
    category = case["category"]
    expect = case.get("expect", {})
    answer = strip_question_echo(obs["answer"], case["question"])

    if category == "routing":
        want, got = set(expect["plan"]), set(obs["plan"])
        return want == got, f"期望 {sorted(want)} / 实际 {sorted(got)}"

    if category == "tool_args":
        name = expect["tool"]
        step = next((s for s in obs["tool_steps"] if s["name"] == name), None)
        if step is None:
            return False, f"没有调用工具 {name}（实际调用 {[s['name'] for s in obs['tool_steps']]}）"
        args = step.get("args") or {}
        if "city" in expect:
            got = args.get("city")
            return got == expect["city"], f"期望 city={expect['city']} / 实际 city={got!r}"
        if "value" in expect:
            expr = args.get("expression") or ""
            if not expr:
                return False, f"没抽出算式（args={args}），结果：{step['result'][:40]}"
            got = calculator(expr)
            return got == str(expect["value"]), f"期望 {expect['value']} / 实际 {got}（算式抽取为 {expr!r}）"
        return False, f"用例缺少期望值：{expect}"

    if category == "retrieval":
        sources = obs["sources"]
        want = expect["source"]
        rank = sources.index(want) + 1 if want in sources else None
        ok = rank is not None and rank <= config.TOP_K
        return ok, f"期望来源 {want} / 排名 {rank}（top{config.TOP_K}={sources}）"

    if category == "answer_grounding":
        missing = [k for k in expect["must_contain"] if k not in answer]
        return not missing, (
            f"缺少事实 {missing} / 答案：{answer[:80]}" if missing
            else f"命中 {expect['must_contain']}"
        )

    if category == "guard":
        problems = []
        hit_forbid = [k for k in expect.get("forbid", []) if k in answer]
        if hit_forbid:
            problems.append(f"答案出现了不该有的内容 {hit_forbid}")
        if expect.get("abstain"):
            # 兜底成立 = 没把低相关片段塞进上下文，或者明确说明知识库没有
            said_no = any(w in answer for w in ABSTAIN_WORDS)
            if obs["context_sources"] and not said_no:
                problems.append(
                    f"知识库不覆盖却把 {obs['context_sources']} 当依据作答（没有明说无法回答）"
                )
        if expect.get("ask_for_args"):
            name = expect.get("tool", "")
            step = next((s for s in obs["tool_steps"] if s["name"] == name), None)
            if step is None:
                problems.append(f"没有走到工具 {name} 的追问")
            else:
                args = step.get("args") or {}
                asked = any(w in (step.get("result", "") + answer) for w in ASK_ARG_WORDS)
                if args:
                    problems.append(f"参数没抽出来却硬调了工具（args={args}）")
                elif not asked:
                    problems.append("参数缺失但没有向用户追问参数")
        return not problems, "；".join(problems) if problems else "兜底行为符合预期"

    return False, f"未知类别 {category}"


# --- 指标 ------------------------------------------------------------------------
METRIC_KEYS = (
    "routing_accuracy",
    "tool_args_accuracy",
    "retrieval_hit@1",
    "retrieval_hit@3",
    "retrieval_mrr",
    "answer_grounding_accuracy",
    "guard_accuracy",
    "overall_pass_rate",
    "errors",
)


def compute_metrics(results: list[dict]) -> dict:
    def rows(cat: str) -> list[dict]:
        return [r for r in results if r["category"] == cat]

    def accuracy(cat: str) -> float:
        group = rows(cat)
        return round(sum(1 for r in group if r["passed"]) / len(group), 4) if group else 0.0

    retrieval = rows("retrieval")
    ranks = [r["signals"].get("rank") for r in retrieval]
    hit1 = round(sum(1 for k in ranks if k == 1) / len(retrieval), 4) if retrieval else 0.0
    hit3 = round(sum(1 for k in ranks if k and k <= config.TOP_K) / len(retrieval), 4) if retrieval else 0.0
    mrr = round(sum(1.0 / k for k in ranks if k) / len(retrieval), 4) if retrieval else 0.0

    return {
        "routing_accuracy": accuracy("routing"),
        "tool_args_accuracy": accuracy("tool_args"),
        "retrieval_hit@1": hit1,
        "retrieval_hit@3": hit3,
        "retrieval_mrr": mrr,
        "answer_grounding_accuracy": accuracy("answer_grounding"),
        "guard_accuracy": accuracy("guard"),
        "overall_pass_rate": round(sum(1 for r in results if r["passed"]) / len(results), 4) if results else 0.0,
        "errors": sum(1 for r in results if r.get("error")),
    }


# --- 运行 ------------------------------------------------------------------------
def load_dataset(path: Path | None = None) -> dict:
    return json.loads((path or DATASET_PATH).read_text(encoding="utf-8"))


def run_eval(*, strategy: str | None = None, category: str | None = None,
             dataset_path: Path | None = None, retrieval: str | None = None) -> dict:
    dataset_path = dataset_path or DATASET_PATH
    dataset = load_dataset(dataset_path)
    cases = dataset["cases"]
    if category:
        cases = [c for c in cases if c["category"] == category]
        if not cases:
            raise SystemExit(f"没有这一类用例：{category}")

    with Harness(strategy=strategy, retrieval=retrieval) as harness:
        results = _run_cases(harness, cases)
        env = {
            "chat_backend": config.effective_chat_backend(),
            "retrieval_backend": self_backend(harness),
            "chunk_strategy": harness.strategy,
            "top_k": config.TOP_K,
            "context_budget": config.CONTEXT_TOKEN_BUDGET,
            "corpus_docs": len(harness.corpus),
            "corpus_chunks": sum(c.get("chunks", 0) for c in harness.corpus),
            "cases": len(results),
        }

    metrics = compute_metrics(results)
    return {
        "version": dataset["version"],
        "dataset": dataset_path.name,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "env": env,
        "metrics": metrics,
        "results": results,
    }


def _run_cases(harness: Harness, cases: list[dict]) -> list[dict]:
    results: list[dict] = []
    for case in cases:
        record = {
            "id": case["id"],
            "category": case["category"],
            "question": case["question"],
            "expect": case.get("expect", {}),
            "note": case.get("note", ""),
            "passed": False,
            "reason": "",
            "signals": {},
            "error": "",
        }
        try:
            obs = harness.ask(case)
            passed, reason = score_case(case, obs)
            record["passed"] = passed
            record["reason"] = reason
            record["signals"] = {
                "plan": obs["plan"],
                "tool_steps": obs["tool_steps"],
                "rank": (obs["sources"].index(case["expect"]["source"]) + 1
                         if case["category"] == "retrieval" and case["expect"]["source"] in obs["sources"]
                         else None),
                "sources": obs["sources"],
                "scores": obs["scores"],
                "context_sources": obs["context_sources"],
                "answer": obs["answer"],
            }
        except Exception as exc:  # 单条用例炸了不能拖垮整轮评测
            record["error"] = f"{exc.__class__.__name__}: {exc}"
            record["reason"] = "用例执行异常"
            record["traceback"] = traceback.format_exc()[-800:]
        results.append(record)
    return results


def self_backend(harness: Harness) -> str:
    return getattr(harness.retriever, "backend", "bm25")


# --- 输出 ------------------------------------------------------------------------
CATEGORY_TITLE = {
    "routing": "意图路由",
    "tool_args": "工具参数抽取",
    "retrieval": "RAG 召回",
    "answer_grounding": "答案事实覆盖",
    "guard": "兜底与拒答",
}


def print_report(report: dict, *, verbose: bool = False) -> None:
    results = report["results"]
    env = report["env"]
    print("=" * 78)
    print(f"Agent 效果评测 · {report['generated_at']} · 题集 {report.get('dataset', 'dataset.json')}")
    print(f"环境：chat={env['chat_backend']} retrieval={env['retrieval_backend']} "
          f"chunk={env['chunk_strategy']} top_k={env['top_k']}")
    print(f"语料：{env['corpus_docs']} 篇 / {env['corpus_chunks']} 块 · 用例 {env['cases']} 条")
    print("=" * 78)

    for cat in CATEGORY_TITLE:
        group = [r for r in results if r["category"] == cat]
        if not group:
            continue
        ok = sum(1 for r in group if r["passed"])
        extra = ""
        if cat == "retrieval":
            extra = (f"  hit@1={report['metrics']['retrieval_hit@1']:.0%}"
                     f"  hit@{env['top_k']}={report['metrics']['retrieval_hit@3']:.0%}"
                     f"  MRR={report['metrics']['retrieval_mrr']:.3f}")
        print(f"\n[{CATEGORY_TITLE[cat]}] {ok}/{len(group)} = {ok / len(group):.0%}{extra}")
        for r in group:
            mark = "PASS" if r["passed"] else "FAIL"
            if r["passed"] and not verbose:
                print(f"  {mark}  {r['id']}  {r['question']}")
                continue
            print(f"  {mark}  {r['id']}  {r['question']}")
            print(f"        → {r['reason']}")

    print("\n" + "-" * 78)
    for key in METRIC_KEYS:
        value = report["metrics"][key]
        shown = f"{value:.4f}" if key != "errors" else str(value)
        print(f"  {key:<26} {shown}")
    print("-" * 78)


def compare(baseline: dict, current: dict, *, tolerance: float) -> tuple[bool, list[str]]:
    problems: list[str] = []
    for key in METRIC_KEYS:
        base = baseline["metrics"].get(key)
        now = current["metrics"].get(key)
        if base is None or now is None:
            continue
        if key == "errors":
            if now > base:
                problems.append(f"{key}: {base} -> {now}（新增异常）")
            continue
        if now < base - tolerance:
            problems.append(f"{key}: {base:.4f} -> {now:.4f}（回退 {base - now:.4f}）")
    return (not problems), problems


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent 效果评测跑分器")
    parser.add_argument("--category", help="只跑某一类：routing/tool_args/retrieval/answer_grounding/guard")
    parser.add_argument("--dataset", default="dataset.json",
                        help="题集文件：dataset.json（开发/回归集）或 dataset_holdout.json（留出集）")
    parser.add_argument("--strategy", help="覆盖切分策略：sentence|fixed（做消融对比）")
    parser.add_argument("--retrieval", default="bm25",
                        help="检索后端：bm25|dashscope|hybrid（默认 bm25，保证与冻结基线可比）")
    parser.add_argument("--verbose", action="store_true", help="连通过的用例也打印实际信号")
    parser.add_argument("--save-baseline", action="store_true", help="把本次指标写进 baseline.json")
    parser.add_argument("--check", action="store_true", help="与 baseline.json 对比，回退则返回非零")
    parser.add_argument("--tolerance", type=float, default=0.0, help="允许的回退阈值（默认 0，不允许回退）")
    parser.add_argument("--json", dest="json_path", help="把本次报告另存到指定路径")
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset)
    if not dataset_path.is_absolute():
        dataset_path = EVAL_DIR / dataset_path
    report = run_eval(strategy=args.strategy, category=args.category,
                      dataset_path=dataset_path, retrieval=args.retrieval)
    print_report(report, verbose=args.verbose)

    save_json(REPORTS_DIR / "latest.json", report)
    if args.json_path:
        save_json(Path(args.json_path), report)
    if args.save_baseline:
        save_json(BASELINE_PATH, report)
        print(f"\n已冻结基线：{BASELINE_PATH}")

    if args.check:
        if not BASELINE_PATH.exists():
            print(f"\n没有基线文件 {BASELINE_PATH}，先跑一次 --save-baseline")
            return 2
        baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        ok, problems = compare(baseline, report, tolerance=args.tolerance)
        if ok:
            print("\n回归检查：通过（没有指标回退）")
            return 0
        print("\n回归检查：失败")
        for p in problems:
            print(f"  - {p}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
