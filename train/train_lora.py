"""Qwen2.5-7B 工具调用 LoRA 微调。

设计要点
--------
1. **只训练回答部分**：system prompt + tools 定义 + 用户话术全部 mask 成 -100，
   只在 `<tool_call>...</tool_call>` 这段算 loss。否则模型会把大量算力花在
   复述工具定义上，而且容易学到「背 schema」而不是「选工具、填参数」。
2. **prompt 与推理完全一致**：直接复用 `train/gen_data.py` 生成的 messages，
   它内部的 system + tools 与 `qwen_agent.py` 运行时一模一样。
3. **LoRA**：7B 全参微调在 A100-40G 上放不下（AdamW 状态 + 梯度要 100G+），
   LoRA 只训练约 0.5% 参数，单卡 40G 足够。
4. **不截断对话**：超长样本直接丢弃并报数，避免训练出「半截对话」的行为。

用法（在仓库根目录）
--------------------
    python train/train_lora.py \
        --model ../models/Qwen2.5-7B-Instruct \
        --data-dir data/sft --out-dir outputs/lora_v1
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)


# ======================================================================
# 数据集
# ======================================================================
class ToolCallDataset(Dataset):
    """把 messages 编成 input_ids / labels，只保留 assistant 回复的 loss。"""

    def __init__(self, path: Path, tools: list[dict[str, Any]], tokenizer,
                 max_len: int = 2048):
        self.rows: list[dict[str, Any]] = []
        self.max_len = max_len
        self.tokenizer = tokenizer
        self.tools = tools
        self.skipped_long = 0
        self.skipped_prefix = 0

        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            item = self._encode(row)
            if item is not None:
                self.rows.append(item)

    def _encode(self, row: dict) -> dict | None:
        messages = row["messages"]
        full = self.tokenizer.apply_chat_template(
            messages, tools=self.tools, tokenize=False, add_generation_prompt=False)
        prefix = self.tokenizer.apply_chat_template(
            messages[:-1], tools=self.tools, tokenize=False, add_generation_prompt=True)

        # 前缀必须是全文的字符串前缀，否则说明模板拼接方式超出预期，宁可丢弃
        if not full.startswith(prefix):
            self.skipped_prefix += 1
            return None

        full_ids = self.tokenizer(full, add_special_tokens=False)["input_ids"]
        prefix_ids = self.tokenizer(prefix, add_special_tokens=False)["input_ids"]
        if prefix_ids != full_ids[: len(prefix_ids)]:
            self.skipped_prefix += 1
            return None
        if len(full_ids) > self.max_len:
            self.skipped_long += 1
            return None

        labels = list(full_ids)
        for i in range(len(prefix_ids)):
            labels[i] = -100
        return {"input_ids": full_ids, "labels": labels}

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, i: int) -> dict:
        return self.rows[i]


@dataclass
class PadCollator:
    pad_id: int

    def __call__(self, batch: list[dict]) -> dict:
        width = max(len(x["input_ids"]) for x in batch)
        input_ids, labels, attention = [], [], []
        for item in batch:
            n = width - len(item["input_ids"])
            input_ids.append(item["input_ids"] + [self.pad_id] * n)
            labels.append(item["labels"] + [-100] * n)
            attention.append([1] * len(item["input_ids"]) + [0] * n)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "attention_mask": torch.tensor(attention, dtype=torch.long),
        }


# ======================================================================
# 主流程
# ======================================================================
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="基座模型目录")
    ap.add_argument("--data-dir", default="data/sft")
    ap.add_argument("--out-dir", default="outputs/lora_v1")
    ap.add_argument("--max-len", type=int, default=6144,
                    help="实测 system+tools≈5137 token，样本约 5600，2048 会全量丢弃")
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch-size", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=16)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--max-steps", type=int, default=-1, help=">0 时只跑这么多步（冒烟用）")
    ap.add_argument("--save-steps", type=int, default=200)
    ap.add_argument("--resume", action="store_true",
                    help="从 out_dir 里最新的 checkpoint-* 继续训练（分片作业用）")
    ap.add_argument("--no-bf16", action="store_true",
                    help="关闭 bf16（CPU 冒烟用；CPU 不支持 bf16 自动混合精度）")
    ap.add_argument("--no-grad-ckpt", action="store_true",
                    help="关闭 gradient checkpointing（小模型冒烟时可提速）")
    args = ap.parse_args()

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tools = json.loads((data_dir / "tools.json").read_text(encoding="utf-8"))
    print(f"tools: {len(tools)} 个")

    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    train_ds = ToolCallDataset(data_dir / "train.jsonl", tools, tokenizer, args.max_len)
    val_ds = ToolCallDataset(data_dir / "val.jsonl", tools, tokenizer, args.max_len)
    print(f"train={len(train_ds)}  val={len(val_ds)}  "
          f"(丢弃: 超长 {train_ds.skipped_long}, 前缀不匹配 {train_ds.skipped_prefix})")
    if len(train_ds) == 0:
        raise SystemExit("训练集为空，先检查 gen_data.py 的输出")

    model = AutoModelForCausalLM.from_pretrained(
        args.model, local_files_only=True,
        torch_dtype=torch.float32 if args.no_bf16 else torch.bfloat16,
        attn_implementation="sdpa",
    )
    model.config.use_cache = False
    if not args.no_grad_ckpt:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()

    from peft import LoraConfig, get_peft_model

    lora = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    training_args = TrainingArguments(
        output_dir=str(out_dir),
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        logging_steps=10,
        save_steps=args.save_steps,
        save_total_limit=2,
        eval_strategy="no" if args.max_steps > 0 else "steps",
        eval_steps=args.save_steps,
        bf16=not args.no_bf16,
        gradient_checkpointing=not args.no_grad_ckpt,
        report_to=[],
        dataloader_num_workers=2,
        remove_unused_columns=False,
        ddp_find_unused_parameters=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        data_collator=PadCollator(tokenizer.pad_token_id),
    )
    done_marker = out_dir / "TRAIN_COMPLETE"
    if args.resume and not done_marker.exists():
        ckpts = sorted(
            (p for p in out_dir.glob("checkpoint-*")
             if p.name.split("-")[-1].isdigit()),
            key=lambda p: int(p.name.split("-")[-1]))
        if ckpts:
            print(f"从断点继续：{ckpts[-1]}")
            trainer.train(resume_from_checkpoint=str(ckpts[-1]))
        else:
            print("没有可用断点，从头开始")
            trainer.train()
    else:
        trainer.train()

    adapter_dir = out_dir / "adapter"
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    done_marker.write_text("ok\n", encoding="utf-8")
    print(f"adapter 已保存: {adapter_dir}")


if __name__ == "__main__":
    main()
