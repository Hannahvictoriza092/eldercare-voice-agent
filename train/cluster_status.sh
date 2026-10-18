#!/usr/bin/env bash
# 集群状态速查：GPU 占用 + 我们的作业 + 预计开始时间
set -uo pipefail

echo "===== 我们的作业 ====="
squeue -u "$USER" -o "%.8i %.14j %.9T %.10M %.6D %R"

echo
echo "===== GPU 节点占用（AllocTRES 里的 gres/gpu）====="
# -N 让 sinfo 每个节点输出一行（不加会压缩成 gpu[3-5,7-9,13]）
for n in $(sinfo -p gpu -h -N -o "%n" | sort -u); do
  line=$(scontrol show node "$n" | grep -e AllocTRES -e CPUTot)
  alloc=$(echo "$line" | sed -n 's/.*AllocTRES=\([^ ]*\).*/\1/p')
  cputot=$(echo "$line" | sed -n 's/.*CPUTot=\([0-9]*\).*/\1/p')
  gpu=$(echo "$alloc" | sed -n 's/.*gres\/gpu=\([0-9]*\).*/\1/p')
  printf "%-8s GPU占用=%s/2  CPU=%s/%s\n" "$n" "${gpu:-?}" "${cputot:-?}" "${cputot:-?}"
  printf "         %s\n" "$alloc"
done

echo
echo "===== 分区状态 ====="
sinfo -p gpu -o "%.10P %.8a %.12l %.6D %.10t %N"

echo
echo "===== 我的作业预计开始 ====="
squeue --start -u "$USER" -o "%.8i %.14j %.20S %.10R"
