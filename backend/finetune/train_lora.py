"""LoRA / QLoRA fine-tuning of Qwen2.5 on the domain QA set.

Usage (from ``backend/`` with the finetune venv):
    python finetune/train_lora.py --steps 40 --use-4bit
    python finetune/train_lora.py --steps 40 --no-4bit     # plain LoRA (fp16)

Outputs the LoRA adapter + a training-curve JSON under ``finetune/outputs/``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTTrainer, SFTConfig

import sys
sys.path.insert(0, str(Path(__file__).parents[1]))
from app import config

DEFAULT_DATA = config.FINETUNE_DATA_DIR / "domain_qa.jsonl"


def build_dataset(path, tokenizer):
    ds = load_dataset("json", data_files=str(path), split="train")

    def format_row(row):
        text = tokenizer.apply_chat_template(
            row["messages"], tokenize=False, add_generation_prompt=False
        )
        return {"text": text}

    ds = ds.map(format_row, remove_columns=ds.column_names)
    return ds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    ap.add_argument("--model", default=config.FINE_TUNE_BASE_MODEL)
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--use-4bit", dest="use_4bit", action="store_true")
    ap.add_argument("--no-4bit", dest="use_4bit", action="store_false")
    ap.set_defaults(use_4bit=config.USE_4BIT)
    ap.add_argument("--out", default=str(config.FT_OUTPUT_ADAPTER))
    args = ap.parse_args()

    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[train] device={device} model={args.model} 4bit={args.use_4bit}")

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model_kwargs = dict(trust_remote_code=True)
    if args.use_4bit and torch.cuda.is_available():
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
        model_kwargs["torch_dtype"] = torch.float16
    else:
        # plain LoRA: model in fp16 (or bf16 if supported)
        model_kwargs["torch_dtype"] = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float32

    model = AutoModelForCausalLM.from_pretrained(args.model, **model_kwargs)
    model.config.use_cache = False

    lora_config = LoraConfig(
        r=config.LORA_R,
        lora_alpha=config.LORA_ALPHA,
        lora_dropout=config.LORA_DROPOUT,
        bias="none",
        task_type="CAUSAL_LM",
    )

    ds = build_dataset(args.data, tokenizer)

    train_args = SFTConfig(
        output_dir=str(output_dir),
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=2,
        max_steps=args.steps,
        learning_rate=args.lr,
        logging_steps=max(1, args.steps // 8),
        save_strategy="steps",
        save_steps=args.steps,
        report_to=[],
        max_length=config.MAX_SEQ_LEN,
        packing=False,
        save_total_limit=1,
    )

    trainer = SFTTrainer(
        model=model,
        train_dataset=ds,
        args=train_args,
        tokenizer=tokenizer,
        peft_config=lora_config,
    )

    trainer.train()
    trainer.save_model(str(output_dir))

    if hasattr(trainer, "state") and trainer.state.log_history:
        with open(output_dir / "train_curve.json", "w", encoding="utf-8") as f:
            json.dump(trainer.state.log_history, f, ensure_ascii=False, indent=2)
        print(f"[train] saved adapter -> {output_dir}")
        print(f"[train] last logs: {trainer.state.log_history[-3:]}")
    else:
        print("[train] no log history available")


if __name__ == "__main__":
    main()
