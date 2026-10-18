"""造一个「袖珍版 Qwen」用于 CPU 冒烟：只验证训练代码链路，不验证效果。

为什么需要它
------------
gpu 分区长期排满（预计要等 2-3 天）。如果用真实 7B 模型做冒烟，只能等 GPU；
而训练代码里最容易出错的地方（dataset 编码、loss mask、collator、peft 挂载、
checkpoint 保存、断点续训）**和模型大小无关**。所以用一个几 MB 的随机权重小模型
在 cpu 分区跑一遍，就能把这些坑提前排掉。

产物目录里会有：
    config.json / model.safetensors    随机初始化的迷你 Qwen2
    tokenizer*                         从真实模型复制（保证 chat_template 一致）

用法：
    python train/make_tiny_model.py --src ../models/Qwen2.5-7B-Instruct \
        --out data/tiny_qwen
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import torch
from transformers import AutoTokenizer, Qwen2Config, Qwen2ForCausalLM

# 迷你配置：能跑通 forward/backward 即可，参数尽量少
TINY = dict(
    vocab_size=151936,      # 必须与真实 tokenizer 的 vocab 一致，否则 token id 越界
    hidden_size=64,
    intermediate_size=128,
    num_hidden_layers=2,
    num_attention_heads=4,
    num_key_value_heads=2,
    max_position_embeddings=16384,   # 样本约 5700 token，必须够长
    tie_word_embeddings=True,
)

TOKENIZER_FILES = [
    "tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt",
    "special_tokens_map.json", "added_tokens.json", "generation_config.json",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="真实模型目录（只取 tokenizer）")
    ap.add_argument("--out", default="data/tiny_qwen")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    src, out = Path(args.src), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    torch.manual_seed(args.seed)
    config = Qwen2Config(**TINY)
    model = Qwen2ForCausalLM(config)
    model.save_pretrained(str(out))
    n = sum(p.numel() for p in model.parameters())
    print(f"迷你模型已保存: {out}  参数量={n / 1e6:.2f}M")

    # tokenizer 必须与真实模型完全一致：chat_template 里含 tools 渲染逻辑，
    # 模板不一致的话「前缀拼接」检查会失败，冒烟就失去意义。
    tokenizer = AutoTokenizer.from_pretrained(str(src), local_files_only=True)
    tokenizer.save_pretrained(str(out))
    for name in TOKENIZER_FILES:
        s = src / name
        if s.exists() and not (out / name).exists():
            shutil.copy2(s, out / name)

    print(f"tokenizer 已复制（vocab={len(tokenizer)}）")
    print("接下来：python train/precheck.py --model", out, "--data-dir data/sft")


if __name__ == "__main__":
    main()
