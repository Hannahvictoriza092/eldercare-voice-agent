#!/usr/bin/env bash
#SBATCH --job-name=qwen_cpu_smoke
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=00:30:00
#SBATCH --output=/public/home/cjzhou/seniortalk_voice_agent_20260929/skill/outputs/slurm/cpu_smoke_%j.log
#SBATCH --error=/public/home/cjzhou/seniortalk_voice_agent_20260929/skill/outputs/slurm/cpu_smoke_%j.err

# CPU 冒烟：用「袖珍 Qwen」把训练代码全链路跑通，不需要 GPU。
#
# 它验证的是：数据编码 → loss mask → collator → peft 挂载 → Trainer 训练 →
#            checkpoint 保存 → 断点续训 → adapter 导出
# 这些环节和模型大小无关，所以 CPU + 小模型就能排掉绝大部分 bug。

set -euo pipefail

# ⚠️ 本集群的 Slurm 会把批处理脚本复制到 spool 目录再执行，所以
#    `dirname $0` 拿到的是 spool 路径，不能用它定位仓库。
#    日志路径也因为同样原因必须是绝对路径（见上面 #SBATCH --output）。
ROOT="${SLURM_SUBMIT_DIR:-$PWD}"
if [[ ! -d "$ROOT/train" ]]; then
  echo "请在仓库根目录提交：cd <repo> && sbatch train/cpu_smoke.slurm" >&2
  exit 2
fi
cd "$ROOT"
export PYTHONPATH="$ROOT"
export PYTHONUNBUFFERED=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-8}"
export TOKENIZERS_PARALLELISM=false

PY="$ROOT/../envs/qwen_agent_py310/bin/python"
MODEL="$ROOT/../models/Qwen2.5-7B-Instruct"
TINY="$ROOT/data/tiny_qwen"
OUT="$ROOT/outputs/cpu_smoke"

mkdir -p "$ROOT/outputs/slurm" data/sft data/tiny_qwen
rm -rf "$OUT"

echo "=== 1/5 造迷你模型（只取真实 tokenizer）==="
"$PY" train/make_tiny_model.py --src "$MODEL" --out "$TINY"

echo
echo "=== 2/5 造小数据子集（避免编码全部 4500 条，很快）==="
SMOKE_DATA="$ROOT/data/sft_smoke"
mkdir -p "$SMOKE_DATA"
head -n 40 data/sft/train.jsonl > "$SMOKE_DATA/train.jsonl"
head -n 10 data/sft/val.jsonl > "$SMOKE_DATA/val.jsonl"
cp data/sft/tools.json "$SMOKE_DATA/tools.json"
echo "子集: $(wc -l < "$SMOKE_DATA/train.jsonl") train / $(wc -l < "$SMOKE_DATA/val.jsonl") val"

echo
echo "=== 3/5 数据预检（用迷你模型，长度应与真实模型一致）==="
"$PY" train/precheck.py --model "$TINY" --data-dir "$SMOKE_DATA" --max-len 6144

echo
echo "=== 4/5 训练 3 步 ==="
"$PY" train/train_lora.py \
  --model "$TINY" \
  --data-dir "$SMOKE_DATA" \
  --out-dir "$OUT" \
  --max-steps 3 \
  --save-steps 3 \
  --batch-size 1 \
  --grad-accum 1 \
  --max-len 6144 \
  --no-bf16 \
  --no-grad-ckpt

echo
echo "=== 4b/5 模拟「被超时杀掉」后断点续训 ==="
rm -f "$OUT/TRAIN_COMPLETE"
"$PY" train/train_lora.py \
  --model "$TINY" \
  --data-dir "$SMOKE_DATA" \
  --out-dir "$OUT" \
  --max-steps 6 \
  --save-steps 3 \
  --batch-size 1 \
  --grad-accum 1 \
  --max-len 6144 \
  --no-bf16 \
  --no-grad-ckpt \
  --resume

echo
echo "=== 5/6 评测代码路径（迷你模型，只看流程是否跑通）==="
"$PY" train/eval_lora.py \
  --model "$TINY" \
  --adapter "$OUT/adapter" \
  --data-dir "$SMOKE_DATA" \
  --limit 2 \
  --max-new-tokens 24 \
  --device cpu \
  --out "$OUT/eval_probe.json"
test -f "$OUT/eval_probe.json" && echo "eval_probe.json 已生成"

echo
echo "=== 6/6 检查产物 ==="
test -f "$OUT/adapter/adapter_config.json" && echo "adapter_config.json OK"
test -f "$OUT/adapter/adapter_model.safetensors" && echo "adapter 权重 OK"
test -f "$OUT/TRAIN_COMPLETE" && echo "TRAIN_COMPLETE 标记 OK"
ls -la "$OUT" "$OUT/adapter"

echo
echo "=== CPU 冒烟通过 ==="
