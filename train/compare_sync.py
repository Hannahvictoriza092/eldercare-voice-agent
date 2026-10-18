#!/usr/bin/env python3
"""同步校验：比对本地仓库与服务朎副本，或生成/使用清单。

为什么需要：服务器没装 git，两边靠手动 scp，容易漂移。

三种用法
---------
1) 在本地生成清单（上传前）：
       python train/compare_sync.py manifest <本地仓库根> > manifest.json
2) 在服务器比对清单（上传后）：
       python train/compare_sync.py check <服务器仓库根> manifest.json
3) 直接比两个目录（同一台机器上）：
       python train/compare_sync.py diff <目录A> <目录B>

输出分类：只在A / 只在B / 内容不同，按 md5 算。
"""


from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

IGNORE_DIRS = {"__pycache__", ".git", ".pytest_cache", ".ruff_cache",
               "data", "outputs", "envs", ".venv", "venv"}
IGNORE_SUFFIX = {".pyc", ".pyo", ".log"}


def walk(root: Path) -> dict[str, str]:
    """返回 {相对路径: sha256}，跳过数据/缓存/输出目录。"""
    result: dict[str, str] = {}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in IGNORE_DIRS for part in rel.parts):
            continue
        if p.suffix in IGNORE_SUFFIX:
            continue
        result[rel.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    mode = sys.argv[1]

    if mode == "manifest":
        root = Path(sys.argv[2])
        json.dump(walk(root), sys.stdout, indent=0, sort_keys=True)
        print()
        return

    if mode == "check":
        root, mf = Path(sys.argv[2]), Path(sys.argv[3])
        a = json.loads(mf.read_text(encoding="utf-8"))
        b = walk(root)
    elif mode == "diff":
        a, b = walk(Path(sys.argv[2])), walk(Path(sys.argv[3]))
    else:
        print(__doc__)
        raise SystemExit(2)

    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    differ = sorted(k for k in set(a) & set(b) if a[k] != b[k])

    print(f"A 有 {len(a)} 个文件 / B 有 {len(b)} 个文件\n")

    print(f"== 只在 A（本地新增，需上传）{len(only_a)} ==")
    for k in only_a:
        print("  +", k)

    print(f"\n== 只在 B（服务器有、本地无，可能是服务器上改的）{len(only_b)} ==")
    for k in only_b:
        print("  R", k)

    print(f"\n== 内容不同 {len(differ)} ==")
    for k in differ:
        print("  ≠", k)

    if not (only_a or only_b or differ):
        print("\n✅ 完全一致")

    raise SystemExit(0 if not (only_a or only_b or differ) else 1)


if __name__ == "__main__":
    main()
