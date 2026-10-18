"""训练前预检：只加载 tokenizer（不需要 GPU），检查数据能否正确编码。

它在验证三件最容易出事的事：
  1. `apply_chat_template` 的前缀拼接是否符合预期（多轮样本最容易不匹配）
  2. 每条样本是否超长
  3. mask 之后，真正参与 loss 的 token 是不是**只有** assistant 的回复

用法（在仓库根目录，登录节点即可，很轻）
    python train/precheck.py --model ../models/Qwen2.5-7B-Instruct --data-dir data/sft
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from transformers import AutoTokenizer  # noqa: E402

from train.train_lora import ToolCallDataset  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data-dir", default="data/sft")
    ap.add_argument("--max-len", type=int, default=6144)
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    tools = json.loads((data_dir / "tools.json").read_text(encoding="utf-8"))
    tok = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    ok = True
    for split in ("train", "val"):
        ds = ToolCallDataset(data_dir / f"{split}.jsonl", tools, tok, args.max_len)
        total = sum(1 for line in (data_dir / f"{split}.jsonl")
                    .read_text(encoding="utf-8").splitlines() if line.strip())
        print(f"[{split}] 可编码 {len(ds)}/{total}  "
              f"超长丢弃 {ds.skipped_long}  前缀不匹配 {ds.skipped_prefix}")
        if not ds.rows:
            ok = False
            continue

        # 长度分布：用来决定 max_len 该设多少
        lens = sorted(len(r["input_ids"]) for r in ds.rows)
        pick = lambda q: lens[min(len(lens) - 1, int(len(lens) * q))]  # noqa: E731
        print(f"    长度 min={lens[0]}  p50={pick(0.5)}  p95={pick(0.95)}  "
              f"max={lens[-1]}")
        # 工具定义本身占多少（system + tools，不含用户话术）
        solo = tok(tok.apply_chat_template(
            [{"role": "user", "content": "x"}], tools=tools,
            tokenize=False, add_generation_prompt=True), add_special_tokens=False)
        print(f"    其中 system+tools 约 {len(solo['input_ids'])} token")

        item = ds.rows[0]
        answer_ids = [t for t, lab in zip(item["input_ids"], item["labels"]) if lab != -100]
        prompt_len = len(item["input_ids"]) - len(answer_ids)
        print(f"    样本长度 {len(item['input_ids'])}，prompt {prompt_len}，"
              f"参与 loss 的 token {len(answer_ids)}")
        print(f"    loss 覆盖的文本: {tok.decode(answer_ids)!r}")

    print("\n" + ("✅ 预检通过，可以提交训练" if ok else "❌ 有问题，先修数据"))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
