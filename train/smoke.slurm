#!/usr/bin/env bash
#SBATCH --job-name=qwen_lora_smoke
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=00:40:00
#SBATCH --output=/public/home/cjzhou/seniortalk_voice_agent_20260929/skill/outputs/slurm/lora_smoke_%j.log
#SBATCH --error=/public/home/cjzhou/seniortalk_voice_agent_20260929/skill/outputs/slurm/lora_smoke_%j.err

# 冒烟训练：只用 200 条数据跑 20 步，验证「环境 + 数据 + 显卡 + 保存」全部打通。
# 目的不是效果，是别把 12 小时的正式作业浪费在一个 import 错误上。

set -euo pipefail

# ⚠️ 本集群的 Slurm 会把批处理脚本复制到 spool 目录再执行，
#    `dirname $0` 拿到的是 spool 路径，不能用它定位仓库；
#    日志路径同样必须是绝对路径。
ROOT="${SLURM_SUBMIT_DIR:-$PWD}"
if [[ ! -d "$ROOT/train" ]]; then
  echo "请在仓库根目录提交：cd <repo> && sbatch train/smoke.slurm" >&2
  exit 2
fi
cd "$ROOT"
export PYTHONPATH="$ROOT"
export PYTHONUNBUFFERED=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"

PY="$ROOT/../envs/qwen_agent_py310/bin/python"
MODEL="$ROOT/../models/Qwen2.5-7B-Instruct"
OUT="$ROOT/outputs/lora_smoke"

mkdir -p "$ROOT/outputs/slurm" "$ROOT/data/sft_smoke"

echo "=== GPU ==="
nvidia-smi --query-gpu=name,memory.total --format=csv || true

echo "=== 1/2 生成小数据集 ==="
"$PY" train/gen_data.py \
  --out-dir data/sft_smoke \
  --n-train 200 --n-val 40 \
  --tools-out data/sft_smoke/tools.json

echo "=== 2/2 训练 20 步 ==="
"$PY" train/train_lora.py \
  --model "$MODEL" \
  --data-dir data/sft_smoke \
  --out-dir "$OUT" \
  --max-steps 20 \
  --save-steps 20 \
  --grad-accum 2 \
  --max-len 6144

echo "=== SMOKE OK ==="
ls -la "$OUT"
