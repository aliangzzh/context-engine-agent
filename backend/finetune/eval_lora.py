"""Evaluate base vs LoRA-fine-tuned Qwen on a small held-out set.

Shows the before/after improvement that an interviewer will ask about. Metrics
are simple but honest: token-level recall / F1 of the generated answer vs the
reference fact (normalized), plus the raw outputs for inspection.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

import sys
sys.path.insert(0, str(Path(__file__).parents[1]))
from app import config

EVAL = [
    ("加绒牛仔应该怎么洗？", "加绒牛仔水温不超过30度，用中性洗涤剂，翻面清洗，机洗选轻柔模式，避免长时间浸泡。"),
    ("纯棉保暖内衣可以漂白吗？", "纯棉保暖内衣禁止使用漂白剂，水温不超过30度。"),
    ("身高170体重120斤推荐什么尺码？", "身高170厘米体重115到135斤建议L码。"),
    ("德绒内衣能高温熨烫吗？", "德绒保暖内衣避免高温熨烫，防止破坏保暖纤维。"),
    ("春季搭配衣服有什么原则？", "服装搭配遵循三色原则，全身颜色不超过三种，同色系更显高级。"),
]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text.lower()))


def _f1(ref: str, hyp: str) -> float:
    r, h = _tokens(ref), _tokens(hyp)
    if not r or not h:
        return 0.0
    inter = len(r & h)
    rec = inter / len(r)
    prec = inter / len(h)
    return round(2 * prec * rec / (prec + rec), 4) if (prec + rec) else 0.0


def _generate(model, tokenizer, prompt, device):
    msgs = [{"role": "system", "content": "你是一名专业的企业知识问答助手。"},
            {"role": "user", "content": prompt}]
    text = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt", truncation=True).to(device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=128, do_sample=False,
                             pad_token_id=tokenizer.pad_token_id)
    gen = out[0][inputs["input_ids"].shape[1]:]
    return tokenizer.decode(gen, skip_special_tokens=True).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=config.FINE_TUNE_BASE_MODEL)
    ap.add_argument("--adapter", default=str(config.FT_OUTPUT_ADAPTER))
    ap.add_argument("--base-only", action="store_true")
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32

    base = AutoModelForCausalLM.from_pretrained(args.model, torch_dtype=dtype, trust_remote_code=True).to(device)

    rows = []
    # base scores
    base_rows = []
    for q, ref in EVAL:
        out = _generate(base, tokenizer, q, device)
        base_rows.append({"q": q, "ref": ref, "out": out, "f1": _f1(ref, out)})
    base_avg = round(sum(r["f1"] for r in base_rows) / len(base_rows), 4)

    ft_rows, ft_avg = [], None
    if not args.base_only and (args.adapter and Path(args.adapter).exists()):
        ft = PeftModel.from_pretrained(base, args.adapter)
        ft = ft.to(device).eval()
        for q, ref in EVAL:
            out = _generate(ft, tokenizer, q, device)
            ft_rows.append({"q": q, "ref": ref, "out": out, "f1": _f1(ref, out)})
        ft_avg = round(sum(r["f1"] for r in ft_rows) / len(ft_rows), 4)

    print("=" * 60)
    print(f"Base model F1 avg = {base_avg}")
    if ft_avg is not None:
        print(f"Fine-tuned F1 avg = {ft_avg}  (delta {round(ft_avg - base_avg, 4)})")
    print("=" * 60)
    for i, r in enumerate(base_rows):
        print(f"\n[{i}] Q: {r['q']}")
        print(f"    base F1={r['f1']}  -> {r['out'][:70]}")
        if ft_rows:
            print(f"    ft   F1={ft_rows[i]['f1']}  -> {ft_rows[i]['out'][:70]}")

    out_path = config.OUTPUTS_DIR / (Path(args.adapter).name if args.adapter and not args.base_only else "base") / "eval.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import json
    payload = {"base_avg": base_avg, "ft_avg": ft_avg,
               "base": base_rows, "ft": ft_rows}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved eval -> {out_path}")


if __name__ == "__main__":
    main()
