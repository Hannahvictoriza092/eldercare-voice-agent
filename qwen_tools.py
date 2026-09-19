"""把 skill 库导出成 Qwen 能吃的格式。

用法：
    python qwen_tools.py              # 导出 function calling 的 tools 数组
    python qwen_tools.py --index      # 只导出 skill 清单（塞 system prompt 用）
    python qwen_tools.py --all        # 导出 tools + index 的完整结构
    python qwen_tools.py --write      # 写到 data/qwen_tools.json

对应规划里的两步：「程序把可用 skill 告诉给 qwen」「根据 skill 库建立 qwen 的 schema」。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import skills
from skills import export_qwen_tools, skill_index

SYSTEM_PROMPT_HINT = """你是一个面向独居老人的语音助手。用户的话会先经过语音识别转成文字，可能有错别字。

工作流程：
1. 判断老人想做什么。如果属于下面任意一个 skill 的范围，就调用对应的工具。
2. 如果只是闲聊或安抚，不要调用工具，直接温和地回答。
3. 参数必须全部来自老人说的话。没听清就问，绝对不要编造药名、剂量或时间。
4. 调用工具后，把工具返回的 speech 字段作为你要说的话，不要自己改写，也不要念出英文参数名。
"""


def build_payload() -> dict:
    return {
        "system_prompt": SYSTEM_PROMPT_HINT,
        "skills": skill_index(),
        "tools": export_qwen_tools(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="导出 Qwen tool schema")
    parser.add_argument("--index", action="store_true", help="只导出 skill 清单")
    parser.add_argument("--all", action="store_true", help="导出完整结构（含 system prompt）")
    parser.add_argument("--write", action="store_true", help="写入 data/qwen_tools.json")
    args = parser.parse_args()

    if args.index:
        payload = skill_index()
    elif args.all:
        payload = build_payload()
    else:
        payload = export_qwen_tools()

    text = json.dumps(payload, ensure_ascii=False, indent=2)

    if args.write:
        out = Path("data/qwen_tools.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"已写入 {out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
