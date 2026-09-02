"""Locally fine-tuned Qwen2.5 model (LoRA adapter) via transformers + peft.

Loaded lazily so the backend can start without the heavy dependencies / a GPU.
The adapter (bit mapped to :data:`~app.config.FT_OUTPUT_ADAPTER`) is created by
``backend/finetune/train_lora.py``; if it is absent we fall back to the base
model so the system still runs.
"""
from __future__ import annotations

from typing import Iterable

from .. import config
from .base import ModelBackend


class LocalFTModel(ModelBackend):
    name = "local_ft"

    def __init__(self, model_path: str | None = None, adapter: str | None = None):
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import torch

        model_path = model_path or config.FINE_TUNE_BASE_MODEL
        adapter = adapter or str(config.FT_OUTPUT_ADAPTER)

        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            model_path, torch_dtype=dtype, trust_remote_code=True
        )
        # attach the LoRA adapter if it exists
        try:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, adapter)
        except Exception:
            pass

        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        self.model = model.to(self._device).eval()
        self.tokenizer = tokenizer

    def generate(self, messages: list[dict]) -> str:
        prompt = self._build_prompt(messages)
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self._device)
        with self.tokenizer:  # noqa: SIM117
            out = self.model.generate(
                **inputs,
                max_new_tokens=256,
                do_sample=True,
                top_p=0.9,
                temperature=0.7,
                pad_token_id=self.tokenizer.pad_token_id,
            )
        generated = out[0][inputs["input_ids"].shape[1]:]
        return self.tokenizer.decode(generated, skip_special_tokens=True).strip()

    def stream(self, messages: list[dict]) -> Iterable[str]:
        # simple chunked streaming over the full generation (good enough for UI)
        text = self.generate(messages)
        step = 8
        for i in range(0, len(text), step):
            yield text[i : i + step]

    @staticmethod
    def _build_prompt(messages: list[dict]) -> str:
        # Qwen chat template (chatml style)
        parts = []
        for m in messages:
            role = m["role"]
            if role == "system":
                parts.append(f"<|im_start|>system\n{m['content']}<|im_end|>")
            elif role == "user":
                parts.append(f"<|im_start|>user\n{m['content']}<|im_end|>")
            elif role == "assistant":
                parts.append(f"<|im_start|>assistant\n{m['content']}<|im_end|>")
        parts.append("<|im_start|>assistant\n")
        return "".join(parts)
