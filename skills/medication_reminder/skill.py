"""用药提醒 skill 的对外封装。

这个文件只干一件事：把参数模型、执行器、给 Qwen 的描述拼成一个符合 BaseSkill 约定的对象。
"""

from __future__ import annotations

from typing import Any

from common.base import BaseSkill, RiskLevel, SkillContext, SkillResult

from .executor import MedicationExecutor
from .schema import (
    CancelReminderParams,
    ConfirmTakenParams,
    CreateReminderParams,
    QueryScheduleParams,
    UpdateReminderParams,
)
from .store import ReminderStore

# 给 Qwen 看的 action 说明。写清楚「什么话该用我」，比把字段描述写长更有效。
ACTION_DESCRIPTIONS: dict[str, str] = {
    "create": (
        "【新增用药提醒】当老人或家属要求设置、添加、新增一个吃药提醒时调用。"
        "例如：「每天早上八点提醒我吃一片阿司匹林」「我饭后要吃两粒二甲双胍，一天两次」。"
        "调用前必须从话里拿到药名、单次剂量、剂量单位、每天吃几次、几点提醒这五项。"
        "缺任何一项都不要猜，先向老人追问。"
    ),
    "query": (
        "【查询用药安排】当老人询问今天/某天要吃什么药、还有哪些药没吃、"
        "某次药吃了没有、或最近的服药记录时调用。"
        "例如：「我今天要吃什么药」「降压药吃了吗」「我早上吃过药了没有」「昨天吃了什么药」。"
        "这是只读操作，可以放心调用，不会改变任何提醒设置。"
    ),
    "update": (
        "【修改用药提醒】当老人要调整已有提醒的时间、剂量、频次或服药时机时调用。"
        "例如：「把晚上的药改成九点」「降压药我改成吃半片」「这个药吃到月底就不吃了」。"
        "注意 new_times 要求给完整的新的时间列表，不是只给改动的那个时间。"
    ),
    "cancel": (
        "【取消用药提醒】当老人明确表示不想再吃某个药、不用再提醒时调用。"
        "例如：「别提醒我吃阿司匹林了」「那个药我不吃了」。"
        "这是高风险操作——停药可能是医生调整方案，也可能是老人记错了医嘱。"
        "调用前必须先跟老人确认一次，并建议他先问医生。"
    ),
    "confirm_taken": (
        "【确认已服药】当老人主动说自己已经吃过药时调用。"
        "例如：「我吃过了」「刚吃完降压药」「早上那个药吃了」。"
        "调用后系统会帮他记上服药记录，并告诉他今天还剩几次药。"
    ),
}


class MedicationReminderSkill(BaseSkill):
    """用药提醒。负责老人吃药这件事的全流程：设置 → 提醒 → 确认 → 记录 → 查询。"""

    name = "medication_reminder"
    display_name = "用药提醒"
    description = (
        "帮老人管理吃药：设置/修改/取消用药提醒，到点语音提醒，"
        "记录和查询服药情况，漏服时通知子女。"
        "当老人提到「吃药」「服药」「用药」「提醒我吃」「吃过了」「药」等话题时优先考虑本 skill。"
    )
    risk_level = RiskLevel.HIGH  # 涉及用药安全，任何写操作都要谨慎

    ACTIONS = {
        "create": CreateReminderParams,
        "query": QueryScheduleParams,
        "update": UpdateReminderParams,
        "cancel": CancelReminderParams,
        "confirm_taken": ConfirmTakenParams,
    }

    def __init__(self, store: ReminderStore | None = None, event_store=None):
        self.executor = MedicationExecutor(store, event_store)

    def action_description(self, action: str) -> str:
        base = ACTION_DESCRIPTIONS.get(action, "")
        return f"{self.display_name}｜{base}" if base else f"{self.display_name}：{action}"

    def execute(self, action: str, params: Any, ctx: SkillContext) -> SkillResult:
        return getattr(self.executor, action)(params, ctx)

    # 覆盖成更适合老人的追问话术
    def followup_for(self, action: str, exc: Exception, field_name: str = "") -> str:
        text = str(exc)

        # 判断顺序很关键：跨字段校验（比如「一天三次却只给两个时间点」）的 loc 是空的，
        # 只能看文本，而 Pydantic 的报错文本里会回显 input_value、含其它字段的字面量，
        # 所以先把最具体的时间/频次问题挑出来，再按字段名精确匹配。
        if field_name in ("times", "frequency", "weekdays") or any(
            k in text for k in ("时间点", "HH:mm", "weekdays", "星期")
        ):
            return "您想让我几点提醒您呢？一天吃几次就说几个时间，比如早上八点、晚上八点。"

        if field_name == "medicine_name" or "药品名称" in text:
            return "请问是哪种药呀？您说个名字我好帮您记下来。"

        if field_name in ("dosage", "dosage_unit") or "剂量" in text:
            return "这个药一次吃多少呢？比如一片还是半片？"

        if field_name in ("start_date", "end_date", "new_end_date") or "end_date" in text:
            return "这个药要吃到什么时候呢？您说个日子我好记下来。"

        if action == "update" and not field_name:
            return "您想把哪个药改成什么样呢？说得细一点我好帮您改。"

        if action == "cancel" and not field_name:
            return "您说的是哪个药不用提醒了呀？"

        return "有个信息我还没听清，您再说一遍好吗？"

    # 方便其它模块直接拿执行器的调度能力
    def due_reminders(self, now=None):
        return self.executor.get_due_reminders(now)
