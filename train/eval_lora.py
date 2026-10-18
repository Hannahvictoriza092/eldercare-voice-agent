"""评测：基座模型 vs LoRA 微调后的工具调用准确率。

指标
----
  JSON 合法率     输出能被解析成 {"name","arguments"}
  工具选择准确率    name 是否完全正确
  参数完全匹配率    arguments 逐字段完全相等（最严格）
  字段级 F1        对多字段样本更公平（漏填/多填各算错）
  Schema 合法率    参数能否通过真实 Pydantic 校验
  闲聊正确率       该不调工具的时候确实没调

用法（在仓库根目录，需要 GPU 分配）
----------------------------------
    python train/eval_lora.py --model ../models/Qwen2.5-7B-Instruct \
        --adapter outputs/lora_v1/adapter --data-dir data/sft --limit 200
    # 不给 --adapter 就是测基座模型，用来算提升幅度
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import torch  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

import skills  # noqa: E402

CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)


def parse(raw: str) -> tuple[str, dict] | None:
    match = CALL_RE.search(raw or "")
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or "name" not in payload:
        return None
    return payload.get("name"), payload.get("arguments") or {}


def schema_ok(name: str, args: dict) -> bool:
    found = skills.find_by_tool_name(name)
    if found is None:
        return False
    skill, action = found
    model = skill.ACTIONS[action]
    probe = dict(args)
    if "person_id" in model.model_fields:
        probe["person_id"] = "elder_01"
    try:
        model.model_validate(probe)
        return True
    except Exception:  # noqa: BLE001
        return False


def field_scores(gold: dict, pred: dict) -> tuple[int, int, int]:
    """返回 (命中字段数, 预测字段数, 标签字段数)，用于算字段级 P/R/F1。"""
    hit = sum(1 for k, v in gold.items() if k in pred and pred[k] == v)
    return hit, len(pred), len(gold)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--data-dir", default="data/sft")
    ap.add_argument("--split", default="val")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-new-tokens", type=int, default=256)
    ap.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    tools = json.loads((data_dir / "tools.json").read_text(encoding="utf-8"))
    rows = [json.loads(x) for x in
            (data_dir / f"{args.split}.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    if args.limit:
        rows = rows[: args.limit]

    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    dtype = torch.bfloat16 if args.device == "cuda" else torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        args.model, local_files_only=True, torch_dtype=dtype,
        attn_implementation="sdpa").to(args.device).eval()
    if args.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, args.adapter).eval()

    stats = {"json": 0, "tool": 0, "exact": 0, "hit": 0, "pred": 0, "gold": 0,
             "schema": 0, "no_tool_gold": 0, "no_tool_ok": 0,
             "n": 0, "tool_n": 0}
    failures: list[dict] = []

    for i, row in enumerate(rows, 1):
        messages = row["messages"]
        gold_raw = messages[-1]["content"]
        gold = parse(gold_raw)
        prompt = tokenizer.apply_chat_template(
            messages[:-1], tools=tools, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.inference_mode():
            output = model.generate(
                **inputs, max_new_tokens=args.max_new_tokens, do_sample=False,
                pad_token_id=tokenizer.eos_token_id)
        raw = tokenizer.decode(output[0, inputs.input_ids.shape[1]:], skip_special_tokens=True)
        pred = parse(raw)

        stats["n"] += 1
        if gold is None:
            stats["no_tool_gold"] += 1
            if pred is None:
                stats["no_tool_ok"] += 1
            else:
                failures.append({"i": i, "gold": gold_raw, "pred": raw, "why": "不该调工具"})
            continue

        stats["tool_n"] += 1
        if pred is not None:
            stats["json"] += 1
            if pred[0] == gold[0]:
                stats["tool"] += 1
                h, p, g = field_scores(gold[1], pred[1])
                stats["hit"] += h
                stats["pred"] += p
                stats["gold"] += g
                if pred[1] == gold[1]:
                    stats["exact"] += 1
                if schema_ok(pred[0], pred[1]):
                    stats["schema"] += 1
        if pred is None or pred[0] != gold[0] or pred[1] != gold[1]:
            failures.append({"i": i, "gold": gold_raw, "pred": raw})

        if i % 25 == 0:
            print(f"  ...{i}/{len(rows)}", flush=True)

    n, tn = stats["n"], stats["tool_n"]
    precision = stats["hit"] / stats["pred"] if stats["pred"] else 0.0
    recall = stats["hit"] / stats["gold"] if stats["gold"] else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    report = {
        "adapter": args.adapter or "（基座）",
        "n": n,
        "json_valid_rate": round(stats["json"] / tn, 4) if tn else 0.0,
        "tool_accuracy": round(stats["tool"] / tn, 4) if tn else 0.0,
        "args_exact_rate": round(stats["exact"] / tn, 4) if tn else 0.0,
        "schema_valid_rate": round(stats["schema"] / tn, 4) if tn else 0.0,
        "field_precision": round(precision, 4),
        "field_recall": round(recall, 4),
        "field_f1": round(f1, 4),
        "no_tool_accuracy": round(stats["no_tool_ok"] / stats["no_tool_gold"], 4)
        if stats["no_tool_gold"] else None,
        "tool_samples": tn,
    }
    print("\n" + "=" * 60)
    for k, v in report.items():
        print(f"{k:24s} {v}")
    print("=" * 60)
    for f in failures[:5]:
        print(f"\n[失败样例 {f['i']}] {f.get('why', '')}")
        print(f"  标签: {f['gold'][:180]}")
        print(f"  预测: {f['pred'][:180]}")

    out = Path(args.out) if args.out else (
        Path(args.adapter) / "eval_report.json" if args.adapter
        else data_dir / "eval_base.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"report": report, "failures": failures[:50]},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已写入 {out}")


if __name__ == "__main__":
    main()
