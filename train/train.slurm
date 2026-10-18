#!/usr/bin/env bash
#SBATCH --job-name=qwen_lora
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=/public/home/cjzhou/seniortalk_voice_agent_20260929/skill/outputs/slurm/lora_%j.log
#SBATCH --error=/public/home/cjzhou/seniortalk_voice_agent_20260929/skill/outputs/slurm/lora_%j.err

# 正式 LoRA 训练（分片可续版）
#
# 【为什么时限只给 4 小时】
#   gpu 分区 7 台机器共 14 张 A100，长期被别人占满。Slurm 的 backfill 只让
#   「能在空隙内跑完」的作业插队：request 12h 几乎只能等大空隙，request 4h
#   能塞进各种短空隙，实际开跑时间明显提前。
#   代价：可能被超时杀掉 → 每 100 步存一次盘，重提作业会自动从断点续。
#
# 【用法】
#   sbatch train/train.slurm     # 第一次
#   sbatch train/train.slurm     # 超时后再提一次，自动续训；不要删 outputs/lora_v1
#   bash train/cluster_status.sh  # 看排队情况

set -euo pipefail

# ⚠️ 本集群的 Slurm 会把批处理脚本复制到 spool 目录再执行，
#    `dirname $0` 拿到的是 spool 路径，不能用它定位仓库；
#    日志路径同样必须是绝对路径。
ROOT="${SLURM_SUBMIT_DIR:-$PWD}"
if [[ ! -d "$ROOT/train" ]]; then
  echo "请在仓库根目录提交：cd <repo> && sbatch train/train.slurm" >&2
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
OUT="$ROOT/outputs/lora_v1"

mkdir -p "$ROOT/outputs/slurm" "$ROOT/data/sft"

echo "=== 环境 ==="
date
nvidia-smi --query-gpu=name,memory.total --format=csv || true

# 已全部跑完就退出，避免重复排队
if [[ -f "$OUT/DONE" ]]; then
  echo "训练+评测已完成（$OUT/DONE 存在），无需重跑"
  exit 0
fi

echo "=== 1/4 数据预检（不需要 GPU，几秒） ==="
"$PY" train/precheck.py --model "$MODEL" --data-dir data/sft

echo "=== 2/4 生成训练数据（已存在则跳过） ==="
if [[ ! -s data/sft/train.jsonl ]]; then
  "$PY" train/gen_data.py --out-dir data/sft --n-train 4500 --n-val 400
else
  echo "已存在 data/sft/train.jsonl，跳过生成（要重新生成请先删除）"
fi

echo "=== 3/4 训练（可断点续）==="
if [[ -f "$OUT/TRAIN_COMPLETE" ]]; then
  echo "训练已完成，跳到评测"
else
  "$PY" train/train_lora.py \
    --model "$MODEL" \
    --data-dir data/sft \
    --out-dir "$OUT" \
    --epochs 2 \
    --lr 1e-4 \
    --batch-size 1 \
    --grad-accum 16 \
    --lora-r 16 \
    --lora-alpha 32 \
    --max-len 6144 \
    --save-steps 100 \
    --resume
fi

echo "=== 4/4 评测（基座 vs LoRA）==="
"$PY" train/eval_lora.py --model "$MODEL" --data-dir data/sft \
  --limit 150 --out "$OUT/eval_base.json"
"$PY" train/eval_lora.py --model "$MODEL" --adapter "$OUT/adapter" \
  --data-dir data/sft --limit 150 --out "$OUT/eval_lora.json"

touch "$OUT/DONE"
echo "=== DONE ==="
ls -la "$OUT"
