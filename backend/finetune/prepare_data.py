"""Prepare a small, aligned instruction dataset for the LoRA demo.

Each entry is a (question, answer) pair grounded in the demo knowledge base, so
the fine-tuned model learns to answer domain questions correctly. Records use an
instruction format compatible with Qwen2.5-Instruct (``messages``), letting TRL's
``SFTTrainer`` apply the chat template.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

OUT = Path(__file__).parent / "data" / "domain_qa.jsonl"

# Aligned (question, answer) pairs based on the demo knowledge base.
PAIRS = [
    ("加绒牛仔怎么清洗？", "加绒牛仔：水温≤30℃，中性洗涤剂，翻面清洗，机洗选轻柔模式，避免长时间浸泡。"),
    ("收纳加绒牛仔要注意什么？", "收纳加绒牛仔时折叠平放，避免重压破坏绒层。"),
    ("纯棉保暖内衣可以漂白吗？", "纯棉保暖内衣可机洗或手洗，水温≤30℃，禁止使用漂白剂。"),
    ("德绒保暖内衣能高温熨烫吗？", "德绒保暖内衣避免高温熨烫，防止破坏保暖纤维。"),
    ("身高170体重110斤推荐什么尺码？", "尺码推荐：身高170厘米，体重90–115斤建议M码，体重115–135斤建议L码。"),
    ("牛仔裤尺码怎么选？", "牛仔裤尺码按腰围选择，宽松款可比平时大一号。"),
    ("春季适合什么颜色？", "春季适合清新柔和的颜色：樱花粉、薄荷绿、浅蓝色。"),
    ("服装搭配有什么原则？", "服装搭配遵循三色原则，全身颜色不超过三种，同色系更显高级。"),
]

# Light paraphrases so the model sees varied instruction wording for the same fact.
PROMPT_WRAPPERS = [
    "请问{}",
    "我想了解：{}",
    "帮我看看{}",
    "{}请给出要点",
    "请回答：{}",
]

SYSTEM = "你是一名专业的企业知识问答助手，回答要准确、简洁。"


def build_records(n: int, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    records = []
    for i in range(n):
        question, answer = rng.choice(PAIRS)
        prompt = rng.choice(PROMPT_WRAPPERS).format(question)
        records.append(
            {
                "id": i,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": answer},
                ],
            }
        )
    return records


def main():
    records = build_records(160)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} records -> {OUT}")


if __name__ == "__main__":
    main()
