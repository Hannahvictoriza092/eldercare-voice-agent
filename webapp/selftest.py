"""命令行自检：不开网页，直接把一串模拟对话跑一遍，看链路是否正常。

用法（在仓库根目录）：
    python webapp/selftest.py

它同时充当「演示脚本」——里面的话术就是给观众演示时按顺序念的台词。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from webapp.runtime import DemoRuntime  # noqa: E402

# 固定「现在」，让演示结果可复现（2026-10-10 是周六）
NOW = datetime(2026, 10, 10, 8, 30)

# (老人说的话, 期望的 stage)
SCRIPT: list[tuple[str, str]] = [
    # --- 用药提醒 ---
    ("每天早上八点提醒我吃一片阿司匹林，饭后吃", "ok"),
    ("我饭后要吃两粒二甲双胍，一天三次", "followup"),   # 一天三次却只给一个时间点 -> 程序追问
    ("还有什么药没吃", "ok"),
    ("我刚吃完阿司匹林了", "ok"),
    ("把阿司匹林改成早上七点提醒", "ok"),
    ("提醒我吃药", "followup"),                          # 参数不全 -> 追问（演示"程序检查"）
    ("别提醒我吃阿司匹林了", "ok"),                       # 高风险取消，但参数够 -> 执行
    # --- 呼救 ---
    ("哎呀我摔倒了，起不来了", "ok"),
    ("救护车来了吗", "ok"),
    ("我没事了，不用来了", "ok"),
    ("我按错了，取消吧", "ok"),
    # --- 健康反馈（消费上面产生的数据） ---
    ("我这周吃药按时吗", "ok"),
    ("帮我看看这周的表现", "ok"),
    ("把周报发给医生", "ok"),
    ("我上个月吃药怎么样", "ok"),
    # --- 闲聊 ---
    ("今天天气怎么样呀", "chitchat"),
]


def main() -> int:
    runtime = DemoRuntime()
    runtime.reset()

    print("=" * 78)
    print("老人语音助手 · Agent 链路自检（模拟 Qwen + 真实 skill）")
    print("=" * 78)

    failures = 0
    for utterance, expected in SCRIPT:
        trace = runtime.handle(utterance, now=NOW)
        stage = trace["stage"]
        speech = trace["speech"]
        ok = stage == expected
        failures += 0 if ok else 1
        mark = "✅" if ok else "❌"
        print(f"\n{mark} 老人说：{utterance}")
        qwen = trace["qwen"]
        print(f"   模拟Qwen：tool={qwen['tool_name']}  args={qwen['arguments']}")
        if trace["registry"]:
            reg = trace["registry"]
            print(f"   注册表命中：{reg['display_name']} / {reg['action']}  风险={reg['risk_level']}")
        if trace["result"]:
            r = trace["result"]
            print(f"   校验：{'追问' if r['need_followup'] else ('通过' if r['ok'] else '失败')}")
            if r["data"]:
                print(f"   结构化结果：{r['data']}")
            if r["notifications"]:
                print(f"   待发送通知：{[(n.get('target'), n.get('title') or n.get('content') or '') for n in r['notifications']]}")
        print(f"   助手说：{speech}")
        if stage != expected:
            print(f"   ⚠️ 期望 stage={expected}，实际={stage}")

    print("\n" + "=" * 78)
    print("事件流（三个 skill 共享，健康反馈就是从这里读数据的）")
    print("=" * 78)
    for row in runtime.events_snapshot():
        print("  ", " | ".join(str(c) for c in row))

    print("\n" + "=" * 78)
    due = runtime.due_reminders(datetime(2026, 10, 10, 8, 0))
    print(f"【后台调度】8:00 该提醒的：{len(due)} 条")
    for d in due:
        print("   ", d)

    print("\n" + "=" * 78)
    if failures:
        print(f"❌ 有 {failures} 条与预期不符")
        return 1
    print("✅ 全部符合预期")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
