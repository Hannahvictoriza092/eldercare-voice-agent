"""呼救 skill 的注册元数据和统一入口。"""

from typing import Any

from common import BaseSkill, RiskLevel, SkillContext, SkillResult

from .executor import EmergencyCallExecutor
from .schema import CancelParams, CheckProgressParams, ConfirmSafeParams, TriggerParams


class EmergencyCallSkill(BaseSkill):
    name = "emergency_call"
    display_name = "呼救"
    description = ("老人说救命、摔倒、胸闷、喘不上气等需要紧急帮助时立即发起呼救；"
                   "询问救助是否到来时查询进度；明确误报时取消；确认安全后报平安。"
                   "发起呼救不需要二次确认。")
    risk_level = RiskLevel.HIGH
    ACTIONS = {
        "trigger": TriggerParams,
        "check_progress": CheckProgressParams,
        "cancel": CancelParams,
        "confirm_safe": ConfirmSafeParams,
    }

    def __init__(self, executor: EmergencyCallExecutor | None = None):
        self.executor = executor if executor is not None else EmergencyCallExecutor()

    def action_description(self, action: str) -> str:
        return {
            "trigger": "老人呼救、摔倒或严重不适时立即记录紧急事件并生成待发送通知；不要先追问或二次确认。",
            "check_progress": "老人询问救助来了吗、人到了没有时，查询本人呼救的最新进度。",
            "cancel": "老人说按错了、要取消呼救时，先确认，再取消并生成通知。",
            "confirm_safe": "老人明确报平安并确认结束呼救时，记录安全并生成通知。",
        }[action]

    def execute(self, action: str, params: Any, ctx: SkillContext) -> SkillResult:
        return getattr(self.executor, action)(params, ctx)

    def followup_for(self, action: str, exc: Exception, field_name: str = "") -> str:
        if field_name == "incident_id":
            return "您说的是哪一次呼救？我也可以查最近的一次。"
        return "我没听清，您再说一遍好吗？如果需要紧急帮助，请立即拨打120。"
