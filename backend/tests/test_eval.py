"""评测集完整性 + 回归门 + 优化点锁定。

把「评测集 → 策略优化 → 复测」变成 CI 的一部分：
* 题集本身要合法（用例 id 唯一、期望来源真实存在于语料里）；
* 开发集跑分不得低于 ``eval/baseline.json`` 冻结的指标（回归门）；
* 每个优化点都有一条**直接单测**兜底，避免只靠评测集间接覆盖。

跑法（backend/ 下）：``python -m unittest tests.test_eval -v``
故意不联网：天气工具在评测台里被替换为确定性桩。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.agents.router import route
from app.agents.tools import calculator, extract_args
from app.context.rerank import content_terms, coverage, is_relevant
from eval.run import BASELINE_PATH, CORPUS_DIR, DATASET_PATH, EVAL_DIR, compare, run_eval

KNOWN_CATEGORIES = {"routing", "tool_args", "retrieval", "answer_grounding", "guard"}


def load_dataset(name: str) -> dict:
    return json.loads((EVAL_DIR / name).read_text(encoding="utf-8"))


class TestDatasetIntegrity(unittest.TestCase):
    """题集本身的结构检查：改语料/改题时先在这里炸，而不是分数悄悄变。"""

    def test_dev_set_shape(self):
        dataset = load_dataset("dataset.json")
        cases = dataset["cases"]
        self.assertGreaterEqual(len(cases), 30)
        ids = [c["id"] for c in cases]
        self.assertEqual(len(ids), len(set(ids)), "用例 id 不能重复")
        for case in cases:
            self.assertIn(case["category"], KNOWN_CATEGORIES, case["id"])
            self.assertTrue(case["question"].strip(), case["id"])
            self.assertTrue(case["expect"], case["id"])
            self.assertTrue(case.get("note"), f"{case['id']} 缺 note（说明这条在考什么）")

    def test_every_category_is_covered(self):
        cases = load_dataset("dataset.json")["cases"]
        self.assertEqual({c["category"] for c in cases}, KNOWN_CATEGORIES)

    def test_holdout_sets_exist(self):
        self.assertGreaterEqual(len(load_dataset("dataset_holdout.json")["cases"]), 14)
        self.assertGreaterEqual(len(load_dataset("dataset_holdout2.json")["cases"]), 10)

    def test_corpus_is_big_enough_to_make_topk_meaningful(self):
        docs = list(CORPUS_DIR.glob("*.txt"))
        self.assertGreaterEqual(len(docs), 10, "语料太少的话 hit@3 没有意义")

    def test_retrieval_expectations_point_to_real_docs(self):
        names = {p.name for p in CORPUS_DIR.glob("*.txt")}
        for name in ("dataset.json", "dataset_holdout.json", "dataset_holdout2.json"):
            for case in load_dataset(name)["cases"]:
                if case["category"] == "retrieval":
                    self.assertIn(case["expect"]["source"], names, case["id"])


class TestRegressionGate(unittest.TestCase):
    """开发集跑分不得低于冻结基线（CI 的回归门）。"""

    def test_dev_set_meets_baseline(self):
        if not BASELINE_PATH.exists():
            self.skipTest("还没有 baseline.json，先跑 python -m eval.run --save-baseline")
        baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        report = run_eval(dataset_path=DATASET_PATH)
        ok, problems = compare(baseline, report, tolerance=0.0)
        self.assertTrue(ok, f"评测指标回退：{problems}")
        self.assertEqual(report["metrics"]["errors"], 0, "评测过程中出现异常")


class TestFixesLocked(unittest.TestCase):
    """每个优化点一条直接单测：评测集管整体，这里管"这一处别再退化"。"""

    # -- 优化一：参数抽取 / 算式意图 ------------------------------------------------
    def test_fullwidth_parentheses_are_normalized(self):
        args = extract_args("calculator", "（18+6）乘以3 等于几")
        self.assertEqual(calculator(args["expression"]), "72")

    def test_chinese_operator_counts_as_calc_intent(self):
        self.assertIn("tool:calculator", route("12乘34加5等于多少？"))

    def test_jia_in_a_word_is_not_a_calc_intent(self):
        # 「加绒牛仔」里的「加」不能把洗护问题变成算数问题
        self.assertNotIn("tool:calculator", route("加绒牛仔怎么洗？"))

    def test_weather_city_survives_cold_phrasing(self):
        self.assertEqual(extract_args("get_weather", "成都今天冷吗？"), {"city": "成都"})

    def test_weather_city_survives_rain_phrasing(self):
        self.assertEqual(extract_args("get_weather", "深圳明天会下雨吗？"), {"city": "深圳"})

    def test_missing_city_yields_no_args(self):
        # 「查一下」不是地名：宁可空参数走追问，也不要瞎查
        self.assertEqual(extract_args("get_weather", "帮我查一下温度"), {})

    # -- 优化二：多意图路由 ---------------------------------------------------------
    def test_multi_intent_keeps_both_tools(self):
        plan = set(route("上海天气怎么样？另外帮我算一下 8*7"))
        self.assertTrue({"tool:get_weather", "tool:calculator"} <= plan, plan)

    # -- 优化三/四：相关性门控 ------------------------------------------------------
    def test_relevance_gate_rejects_chitchat(self):
        chunk = (CORPUS_DIR / "会员积分.txt").read_text(encoding="utf-8")
        self.assertFalse(is_relevant("你好，请介绍一下你能做什么", chunk))

    def test_relevance_gate_accepts_real_question(self):
        chunk = (CORPUS_DIR / "售后政策.txt").read_text(encoding="utf-8")
        self.assertTrue(is_relevant("买回来不合适能退吗？", chunk))

    def test_stopwords_are_not_content_terms(self):
        self.assertNotIn("的", content_terms("这个的怎么"))
        self.assertIn("退", content_terms("能退吗"))

    def test_coverage_prefers_the_right_document(self):
        right = (CORPUS_DIR / "库存库位.txt").read_text(encoding="utf-8")
        wrong = (CORPUS_DIR / "材质说明.txt").read_text(encoding="utf-8")
        question = "餐桌放在仓库哪个位置？"
        self.assertGreater(coverage(question, right), coverage(question, wrong))


if __name__ == "__main__":
    unittest.main()
