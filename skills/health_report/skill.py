"""健康和照顾反馈 skill 的对外封装。

这个文件只干一件事：把参数模型、执行器、给 Qwen 的描述拼成一个符合 BaseSkill 约定的对象。
"""

from __future__ import annotations

from typing import Any

from common.base import BaseSkill, RiskLevel, SkillContext, SkillResult

from .executor import HealthReportExecutor
from .schema import (
    GenerateWeeklyParams,
    QueryArchiveParams,
    QuerySummaryParams,
    SendReportParams,
)

# 给 Qwen 看的 action 说明。写清楚「什么话该用我」，比把字段描述写长更有效。
ACTION_DESCRIPTIONS: dict[str, str] = {
    "generate_weekly": (
        "【生成周报】当老人或家属要求生成一周的健康/行为总结时调用。"
        "例如：「这周我表现怎么样」「帮我看看这周的情况」「上周我吃药按时吗」。"
        "这是只读操作，只生成摘要预览，不会发送给任何人。"
    ),
    "send_report": (
        "【发送周报】当老人或家属要求把周报发给医生、子女或社区时调用。"
        "例如：「把周报发给医生」「把上周的情况发给我儿子」「给我女儿发一份这周的总结」。"
        "这是有副作用的操作（会真的发通知），调用前最好确认接收方。"
    ),
    "query_archive": (
        "【查询个性化档案】当老人询问长期积累的健康趋势、历史表现时调用。"
        "例如：「我上个月吃药怎么样」「这半年来我身体情况有什么变化」「我最近有没有经常漏服」。"
        "这是只读操作，可以放心调用。"
    ),
    "query_summary": (
        "【快速问答】当老人问近期（本周/最近几天）的简单健康问题时调用，当场答老人。"
        "例如：「我这周吃药按时吗」「我最近有没有漏吃药」「这周有没有出什么事」。"
        "这是只读操作，不生成完整周报，也不发送。"
    ),
}


class HealthReportSkill(BaseSkill):
    """健康和照顾反馈。消费用药提醒和呼救产出的数据，生成周报反馈给医院/子女，并长期积累个性化档案。"""

    name = "health_report"
    display_name = "健康和照顾反馈"
    description = (
        "汇总老人每周的行为记录（服药依从性、漏服、异常事件），生成周报摘要反馈给医院和子女，"
        "并自动建立长期个性化档案。当老人提到「周报」「这周表现」「吃药按时吗」「健康总结」"
        "「发给医生/儿子」等话题时优先考虑本 skill。"
    )
    risk_level = RiskLevel.LOW  # 周报是只读汇总，没有副作用（send_report 除外，但只产出通知对象）

    ACTIONS = {
        "generate_weekly": GenerateWeeklyParams,
        "send_report": SendReportParams,
        "query_archive": QueryArchiveParams,
        "query_summary": QuerySummaryParams,
    }

    def __init__(self, executor: HealthReportExecutor | None = None):
        self.executor = executor or HealthReportExecutor()

    def action_description(self, action: str) -> str:
        base = ACTION_DESCRIPTIONS.get(action, "")
        return f"{self.display_name}｜{base}" if base else f"{self.display_name}：{action}"

    def execute(self, action: str, params: Any, ctx: SkillContext) -> SkillResult:
        return getattr(self.executor, action)(params, ctx)

    # 覆盖成更适合老人的追问话术
    def followup_for(self, action: str, exc: Exception, field_name: str = "") -> str:
        text = str(exc)

        if field_name == "person_id" or "老人 ID" in text:
            return "请问是给哪位老人做健康反馈呀？"

        if field_name == "targets" or "EMERGENCY" in text or "接收方" in text:
            return "您想把报告发给谁呢？医生、家里人还是社区？"

        if field_name in ("week_start", "start_date", "end_date") or "日期" in text:
            return "您说的是哪一周的情况呀？这周还是上周？"

        if action == "send_report" and not field_name:
            return "您想把报告发给谁呢？医生、家里人还是社区？"

        return "有个信息我还没听清，您再说一遍好吗？"