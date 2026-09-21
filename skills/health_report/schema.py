"""健康和照顾反馈 skill 的参数模型。

这是本 skill 最核心的交付物：一份定义，两边使用。
  - 给程序用：Pydantic 自动做类型/范围/必填校验
  - 给 Qwen 用：model_json_schema() 直接生成 function calling 的 parameters

本 skill 是「下游」：消费用药提醒产出的 MedicationLog 和呼救产出的 Incident，
生成周报摘要反馈给医院/子女，并长期积累个性化档案。
所以参数模型大多是「查什么范围、发给谁」，字段描述要写清楚 Qwen 什么时候该填。
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, model_validator

from common.domain import NotifyTarget


# ======================================================================
# 1. 生成周报
# ======================================================================
class GenerateWeeklyParams(BaseModel):
    """生成某位老人某一周的周报摘要（可预览，不发送）。

    触发话术示例：
        「这周我表现怎么样」「帮我看看这周的情况」
        「上周我吃药按时吗」
    """

    person_id: str = Field(
        ...,
        min_length=1,
        description="要生成周报的老人 ID。不填表示当前说话人本人，但这里建议显式给出，方便 Qwen 从上下文取。",
    )
    week_start: date | None = Field(
        None,
        description=(
            "周报覆盖的起始日期（周一），格式 YYYY-MM-DD。"
            "不填表示本周（从本周一到今天）。老人说「上周」时请换算成上周一的日期。"
        ),
    )


# ======================================================================
# 2. 发送周报
# ======================================================================
class SendReportParams(BaseModel):
    """把某位老人某一周的周报摘要发给医院/子女。

    触发话术示例：
        「把周报发给医生」「把上周的情况发给我儿子」
        「给我女儿发一份这周的总结」

    注意：这是有副作用的操作（会真的发通知），执行前最好让老人确认接收方。
    """

    person_id: str = Field(
        ...,
        min_length=1,
        description="要发送周报的老人 ID。",
    )
    week_start: date | None = Field(
        None,
        description=(
            "周报覆盖的起始日期（周一），格式 YYYY-MM-DD。"
            "不填表示本周。老人说「上周」时请换算成上周一的日期。"
        ),
    )
    targets: list[NotifyTarget] = Field(
        ...,
        min_length=1,
        description=(
            "接收方列表。取值：family=子女, hospital=医院/家庭医生, community=社区。"
            "老人说「发给医生」填 ['hospital']，说「发给我儿子」填 ['family']，"
            "说「都发一份」填 ['family', 'hospital']。"
        ),
    )

    @model_validator(mode="after")
    def _check_targets(self) -> "SendReportParams":
        # 周报是正式摘要，不该发给 120/110 这类紧急通道
        if NotifyTarget.EMERGENCY in self.targets:
            raise ValueError(
                "周报摘要不能发给 EMERGENCY（120/110）紧急通道。"
                "请只选 family / hospital / community。"
            )
        return self


# ======================================================================
# 3. 查询个性化档案
# ======================================================================
class QueryArchiveParams(BaseModel):
    """查询老人长期积累的个性化档案（历史趋势、画像）。

    触发话术示例：
        「我上个月吃药怎么样」「这半年来我身体情况有什么变化」
        「我最近有没有经常漏服」
    """

    person_id: str = Field(
        ...,
        min_length=1,
        description="要查询档案的老人 ID。",
    )
    start_date: date | None = Field(
        None,
        description="查询时间范围的起始日期，格式 YYYY-MM-DD。不填表示不限起始。",
    )
    end_date: date | None = Field(
        None,
        description="查询时间范围的结束日期，格式 YYYY-MM-DD。不填表示到今天。",
    )

    @model_validator(mode="after")
    def _check_range(self) -> "QueryArchiveParams":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError(
                f"end_date（{self.end_date}）不能早于 start_date（{self.start_date}）"
            )
        return self


# ======================================================================
# 4. 快速问答
# ======================================================================
class QuerySummaryParams(BaseModel):
    """快速回答老人关于本周/近期表现的问题，当场答老人，不生成完整周报。

    触发话术示例：
        「我这周吃药按时吗」「我最近有没有漏吃药」
        「这周有没有出什么事」

    这是只读操作，可以放心调用。
    """

    person_id: str = Field(
        ...,
        min_length=1,
        description="要查询的老人 ID。",
    )
    days: int | None = Field(
        None,
        ge=1,
        le=90,
        description=(
            "统计最近多少天。不填默认最近 7 天。老人说「这周」填 7，"
            "说「这个月」填 30，说「最近」填 7。"
        ),
    )