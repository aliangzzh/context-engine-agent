"""Prepare a small instruction dataset for the LoRA demo.

We synthesize a compact domain QA set (clothing care / sizing / color matching)
with an instruction format compatible with Qwen2.5-Instruct. Each record is a
list of ``messages`` so TRL's ``SFTTrainer`` can apply the chat template.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

OUT = Path(__file__).parent / "data" / "domain_qa.jsonl"

# Base seed facts (mirrors the demo knowledge base)
FACTS = [
    "加绒牛仔：水温≤30℃，中性洗涤剂，翻面清洗，机洗选轻柔模式，避免长时间浸泡。",
    "收纳加绒牛仔时折叠平放，避免重压破坏绒层。",
    "纯棉保暖内衣可机洗或手洗，水温≤30℃，禁止使用漂白剂。",
    "德绒保暖内衣避免高温熨烫，防止破坏保暖纤维。",
    "尺码推荐：身高170厘米，体重90–115斤建议M码，体重115–135斤建议L码。",
    "牛仔裤尺码按腰围选择，宽松款可比平时大一号。",
    "春季适合清新柔和的颜色：樱花粉、薄荷绿、浅蓝色。",
    "服装搭配遵循三色原则，全身颜色不超过三种，同色系更显高级。",
]

TEMPLATES = [
    ("如何{goal}？", "根据资料，{fact}"),
    ("{question}，应该注意什么？", "需要注意：{fact}"),
    ("帮我看看{question}怎么处理", "好的，{fact}"),
    ("{question}的要点是什么？", "要点是：{fact}"),
    ("我想了解{question}", "可以这样理解：{fact}"),
]

GOALS = ["洗涤加绒牛仔", "收纳加绒牛仔", "清洗纯棉保暖内衣", "熨烫德绒内衣", "挑选牛仔裤尺码"]
QUESTIONS = ["加绒牛仔怎么洗", "纯棉内衣保养", "德绒如何养护", "牛仔裤选码", "春季搭配颜色"]


def build_records(n: int, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    records = []
    for i in range(n):
        fact = rng.choice(FACTS)
        tpl = rng.choice(TEMPLATES)
        goal = rng.choice(GOALS)
        q = rng.choice(QUESTIONS)
        prompt = tpl[0].format(goal=goal, question=q).replace("{goal}", goal).replace("{question}", q)
        answer = tpl[1].format(fact=fact)
        records.append(
            {
                "id": i,
                "messages": [
                    {"role": "system", "content": "你是一名专业的企业知识问答助手。"},
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": answer},
                ],
            }
        )
    return records


def main():
    records = build_records(200)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} records -> {OUT}")


if __name__ == "__main__":
    main()
