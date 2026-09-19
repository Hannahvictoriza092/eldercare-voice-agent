"""端到端演示：不接真实 Qwen，用假的 tool_call 把整条链路走一遍。

这个脚本的作用是给组内对齐用：
    程序把可用 skill 告诉 qwen  ->  qwen 选 skill 并填参数  ->  程序查注册表
    ->  验证数据齐全 / 填得对不对  ->  执行  ->  返回结果

跑法：
    python demo.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import skills
from skills import SkillContext, find_by_tool_name
from skills.medication_reminder import MedicationReminderSkill, ReminderStore

DEMO_DB = Path("data/demo_reminders.json")

# 固定「现在」，让演示结果可复现
CTX = SkillContext(
    speaker_id="elder_01",
    speaker_name="张奶奶",
    now=datetime(2026, 9, 19, 7, 50),
)


def fresh_registry() -> None:
    """每次演示都用全新的空库，避免上次跑的数据混进来，结果对不上。"""
    DEMO_DB.unlink(missing_ok=True)
    skills.unregister("medication_reminder")
    skills.register(MedicationReminderSkill(ReminderStore(DEMO_DB)))


def hr(char: str = "=") -> None:
    print(char * 72)


def handle(utterance: str, tool_name: str | None, arguments: dict, ctx: SkillContext = CTX):
    """模拟 Agent 层：拿到 Qwen 的输出后该怎么处理。"""
    hr()
    print(f"老人说：{utterance}")
    hr("-")

    if tool_name is None:
        print("Qwen 判断：不需要调用工具，直接闲聊回应")
        print("助手说：张奶奶早上好呀，今天天气不错，记得多穿件衣服。")
        return None

    print(f"1. Qwen 返回 tool_call")
    print(f"   工具名：{tool_name}")
    print(f"   参数：{json.dumps(arguments, ensure_ascii=False)}")

    found = find_by_tool_name(tool_name)
    if found is None:
        print("2. 查注册表：没找到这个工具，忽略这次调用")
        return None
    skill, action = found
    print(f"2. 查注册表：命中 skill={skill.name}  action={action}  "
          f"风险等级={skill.risk_level.value}")

    result = skill.run(action, arguments, ctx)

    if result.need_followup:
        print(f"3. 校验参数：不通过 -> 需要向老人追问")
        print(f"   错误详情：{result.error}")
        print(f"4. 助手说：{result.followup_question}")
    elif result.ok:
        print(f"3. 校验参数：通过")
        print(f"4. 执行完成  结构化结果：{json.dumps(result.data, ensure_ascii=False)}")
        print(f"5. 助手说（TTS 直接播这句）：{result.speech}")
    else:
        print(f"3. 执行失败：{result.error}")
        print(f"4. 助手说：{result.speech}")

    return result


def main() -> None:
    fresh_registry()
    print()
    print("### 第一步：程序把可用的 skill 清单告诉 Qwen ###")
    print(json.dumps(skills.skill_index(), ensure_ascii=False, indent=2))
    print()
    tools = skills.export_qwen_tools()
    print(f"### 第二步：再把 {len(tools)} 个工具的详细参数 schema 交给 Qwen ###")
    for t in tools:
        fn = t["function"]
        required = fn["parameters"].get("required", [])
        print(f"  - {fn['name']}  必填字段：{required}")
    print()

    # ---------------- 场景 1：正常设置 ----------------
    handle(
        "每天早上八点提醒我吃一片阿司匹林，饭后吃",
        "medication_reminder_create",
        {
            "medicine_name": "阿司匹林",
            "dosage": 1,
            "dosage_unit": "tablet",
            "frequency": "once_daily",
            "times": ["08:00"],
            "timing": "after_meal",
        },
    )

    # ---------------- 场景 2：Qwen 填错参数 ----------------
    handle(
        "我饭后要吃两粒二甲双胍，一天三次",
        "medication_reminder_create",
        {
            "medicine_name": "二甲双胍",
            "dosage": 2,
            "dosage_unit": "capsule",
            "frequency": "three_times_daily",
            # 一天三次却只给了两个时间点 —— 程序必须拦住
            "times": ["08:00", "20:00"],
        },
    )

    # ---------------- 场景 3：查询 ----------------
    handle("我今天还有什么药没吃", "medication_reminder_query", {})

    # ---------------- 场景 4：老人主动说吃了 ----------------
    handle("我刚吃完阿司匹林了", "medication_reminder_confirm_taken",
           {"medicine_name": "阿司匹林"})

    # ---------------- 场景 5：再查一次 ----------------
    handle("我今天的药吃完了吗", "medication_reminder_query", {})

    # ---------------- 场景 6：改时间 ----------------
    handle("把阿司匹林改成早上七点提醒", "medication_reminder_update",
           {"medicine_name": "阿司匹林", "new_times": ["07:00"]})

    # ---------------- 场景 7：闲聊不调工具 ----------------
    handle("今天天气怎么样呀", None, {})

    # ---------------- 场景 8：后台调度器（不走 Qwen） ----------------
    hr()
    print("【后台】定时调度器每分钟问一次：现在该提醒谁吃药？")
    hr("-")
    med = skills.get("medication_reminder")
    due = med.due_reminders(datetime(2026, 9, 19, 7, 0))
    if due:
        for d in due:
            if d.get("escalate"):
                print(f"  [升级通知子女] {d['person']} 的 {d['slot']} 那次药已漏服 "
                      f"{d['overdue_minutes']} 分钟")
            else:
                print(f"  [语音提醒] 播放：{d['speech']}")
    else:
        print("  当前没有到点的提醒")


if __name__ == "__main__":
    main()
