"""Merge the fine-tuned LoRA adapter back into the base model.

Produces a standalone merged model under ``finetune/outputs/merged`` that can be
loaded by ``LocalFTModel`` for inference without PEFT.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

import sys
sys.path.insert(0, str(Path(__file__).parents[1]))
from app import config


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=config.FINE_TUNE_BASE_MODEL)
    ap.add_argument("--adapter", default=str(config.FT_OUTPUT_ADAPTER))
    ap.add_argument("--out", default=str(config.FT_MERGED_MODEL))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    base = AutoModelForCausalLM.from_pretrained(args.model, torch_dtype=torch.float16, trust_remote_code=True)
    merged = PeftModel.from_pretrained(base, args.adapter)
    merged = merged.merge_and_unload()

    merged.save_pretrained(str(out))
    tokenizer.save_pretrained(str(out))
    print(f"[export] merged model -> {out}")


if __name__ == "__main__":
    main()
