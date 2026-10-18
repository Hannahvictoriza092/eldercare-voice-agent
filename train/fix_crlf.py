"""把仓库里脚本文件的 CRLF 换成 LF。

为什么需要：这些文件在 Windows 上编辑，换行是 \\r\\n。
Slurm 的 sbatch 会直接拒绝含 \\r 的批处理脚本：
    sbatch: error: Batch script contains DOS line breaks (\\r\\n)

用法（在仓库根目录）：
    python train/fix_crlf.py            # 修 train/ 下的 .slurm/.sh
    python train/fix_crlf.py . --all    # 修整个仓库的脚本类文件
"""

from __future__ import annotations

import sys
from pathlib import Path

SUFFIXES = {".slurm", ".sh"}


def fix(path: Path) -> bool:
    raw = path.read_bytes()
    if b"\r\n" not in raw:
        return False
    path.write_bytes(raw.replace(b"\r\n", b"\n"))
    return True


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    changed = [p for p in target.rglob("*")
               if p.is_file() and p.suffix in SUFFIXES and fix(p)]
    for p in changed:
        print(f"fixed: {p}")
    print(f"共修复 {len(changed)} 个文件")


if __name__ == "__main__":
    main()
