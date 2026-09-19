"""用药提醒 skill 的参数模型。

这是本 skill 最核心的交付物：一份定义，两边使用。
  - 给程序用：Pydantic 自动做类型/范围/必填校验（规划里「程序检查填得对不对」）
  - 给 Qwen 用：model_json_schema() 直接生成 function calling 的 parameters

所以千万不要在这里写「解释型注释」代替校验——写成校验规则，Qwen 和程序都能受益。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from datetime import date as DateType  # 见下方 QueryScheduleParams 的说明
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

# 24 小时制 HH:mm，例如 08:00 / 20:30
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ======================================================================
# 枚举
# ======================================================================
class DosageUnit(str, Enum):
    """剂量单位。"""

    tablet = "tablet"              # 片
    capsule = "capsule"            # 粒
    bag = "bag"                    # 袋
    ml = "ml"                      # 毫升
    mg = "mg"                      # 毫克
    g = "g"                        # 克
    drop = "drop"                  # 滴
    puff = "puff"                  # 喷
    suppository = "suppository"    # 栓
    patch = "patch"                # 贴
    unit = "unit"                  # 单位/支


class Frequency(str, Enum):
    """服药频次。"""

    once_daily = "once_daily"              # 每日一次
    twice_daily = "twice_daily"            # 每日两次
    three_times_daily = "three_times_daily"  # 每日三次
    every_other_day = "every_other_day"    # 隔日一次
    weekly = "weekly"                      # 每周（需配合 weekdays）
    as_needed = "as_needed"                # 按需服用，不生成固定提醒


class Timing(str, Enum):
    """服药时机。"""

    before_meal = "before_meal"      # 饭前
    after_meal = "after_meal"        # 饭后
    with_meal = "with_meal"          # 随餐
    bedtime = "bedtime"              # 睡前
    empty_stomach = "empty_stomach"  # 空腹
    any = "any"                      # 不限


# 频次 -> 需要的提醒时间点个数。这是跨字段校验的依据，单独抽出来方便复用。
FREQUENCY_TIME_COUNT: dict[Frequency, int] = {
    Frequency.once_daily: 1,
    Frequency.twice_daily: 2,
    Frequency.three_times_daily: 3,
    Frequency.every_other_day: 1,
    Frequency.weekly: 1,
}

FREQUENCY_CN: dict[Frequency, str] = {
    Frequency.once_daily: "每天一次",
    Frequency.twice_daily: "每天两次",
    Frequency.three_times_daily: "每天三次",
    Frequency.every_other_day: "隔天一次",
    Frequency.weekly: "每周",
    Frequency.as_needed: "按需服用",
}

UNIT_CN: dict[DosageUnit, str] = {
    DosageUnit.tablet: "片",
    DosageUnit.capsule: "粒",
    DosageUnit.bag: "袋",
    DosageUnit.ml: "毫升",
    DosageUnit.mg: "毫克",
    DosageUnit.g: "克",
    DosageUnit.drop: "滴",
    DosageUnit.puff: "喷",
    DosageUnit.suppository: "粒（栓剂）",
    DosageUnit.patch: "贴",
    DosageUnit.unit: "支",
}

TIMING_CN: dict[Timing, str] = {
    Timing.before_meal: "饭前",
    Timing.after_meal: "饭后",
    Timing.with_meal: "随餐",
    Timing.bedtime: "睡前",
    Timing.empty_stomach: "空腹",
    Timing.any: "不限",
}


def _check_times_format(times: list[str]) -> list[str]:
    for t in times:
        if not TIME_RE.match(t):
            raise ValueError(
                f"时间点 {t!r} 格式不合法，必须是 24 小时制 HH:mm，例如 08:00、20:30"
            )
    return times


# ======================================================================
# 1. 创建提醒
# ======================================================================
class CreateReminderParams(BaseModel):
    """新增一条用药提醒。

    触发话术示例：
        「每天早上八点提醒我吃一片阿司匹林」
        「我饭后得吃两粒二甲双胍，一天两次，早上和晚上」
    """

    medicine_name: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="药品名称。必须用老人说出的药名，例如：阿司匹林、硝苯地平、二甲双胍。不要自行编造或翻译成英文。",
    )
    dosage: float = Field(
        ...,
        gt=0,
        le=100,
        description="单次服用剂量数值，必须大于 0 且不超过 100。例如 1 片填 1，半片填 0.5。",
    )
    dosage_unit: DosageUnit = Field(
        ...,
        description=(
            "剂量单位。取值：tablet=片, capsule=粒, bag=袋, ml=毫升, mg=毫克, "
            "g=克, drop=滴, puff=喷, suppository=栓剂, patch=贴, unit=支。"
        ),
    )
    frequency: Frequency = Field(
        ...,
        description=(
            "服药频次。取值：once_daily=每日一次, twice_daily=每日两次, "
            "three_times_daily=每日三次, every_other_day=隔日一次, weekly=每周, as_needed=按需服用。"
        ),
    )
    times: list[str] = Field(
        ...,
        min_length=1,
        max_length=6,
        description=(
            "提醒时间点数组，24 小时制 HH:mm 字符串。个数必须与 frequency 匹配："
            "once_daily=1 个, twice_daily=2 个, three_times_daily=3 个, "
            "every_other_day=1 个, weekly=1 个。"
            "例如每日两次填 ['08:00', '20:00']。老人只说「早上」时，默认 08:00；"
            "说「中午」默认 12:00；说「晚上」默认 20:00；说「睡前」默认 21:30。"
        ),
    )
    timing: Timing = Field(
        Timing.any,
        description=(
            "服药时机。取值：before_meal=饭前, after_meal=饭后, with_meal=随餐, "
            "bedtime=睡前, empty_stomach=空腹, any=不限。"
        ),
    )
    weekdays: list[int] | None = Field(
        None,
        description=(
            "星期几服药，仅在 frequency=weekly 时必填。0=周一, 1=周二, 2=周三, 3=周四, "
            "4=周五, 5=周六, 6=周日。例如每周一和周四填 [0, 3]。"
        ),
    )
    start_date: date | None = Field(
        None,
        description="开始日期，格式 YYYY-MM-DD。不填表示从今天开始。",
    )
    end_date: date | None = Field(
        None,
        description="结束日期，格式 YYYY-MM-DD。不填表示长期服用。医生约定了疗程时一定要填。",
    )
    target_person: str | None = Field(
        None,
        description="服药人姓名或 ID。只在一位家属给多位老人设置时填写，不填表示当前说话人本人。",
    )
    note: str | None = Field(
        None,
        max_length=200,
        description="备注，例如「心内科张医生开的」「血压高时才吃」。",
    )

    @field_validator("times")
    @classmethod
    def _validate_times(cls, v: list[str]) -> list[str]:
        return _check_times_format(v)

    @field_validator("weekdays")
    @classmethod
    def _validate_weekdays(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return v
        if len(set(v)) != len(v):
            raise ValueError("weekdays 中存在重复的星期")
        for d in v:
            if d < 0 or d > 6:
                raise ValueError(f"星期 {d} 越界，取值范围是 0（周一）到 6（周日）")
        return sorted(v)

    @model_validator(mode="after")
    def _cross_field_check(self) -> "CreateReminderParams":
        # 规则 1：提醒时间点个数必须和频次对得上
        expected = FREQUENCY_TIME_COUNT.get(self.frequency)
        if expected is not None and len(self.times) != expected:
            raise ValueError(
                f"frequency={self.frequency.value}（{FREQUENCY_CN[self.frequency]}）"
                f"需要 {expected} 个提醒时间点，但收到 {len(self.times)} 个：{self.times}。"
                f"请把它补齐或改成符合老人描述的时间点。"
            )

        # 规则 2：按需服用的药不排固定时间
        if self.frequency == Frequency.as_needed:
            raise ValueError(
                "frequency=as_needed（按需服用）不设置固定提醒时间。"
                "如果老人说的其实是每天固定时间吃药，请改选 once_daily / twice_daily 等频次。"
            )

        # 规则 3：weekly 必须给星期
        if self.frequency == Frequency.weekly and not self.weekdays:
            raise ValueError(
                "frequency=weekly 时必须提供 weekdays，例如 [0] 表示每周一。"
                "请追问老人是每周的哪一天。"
            )
        if self.frequency != Frequency.weekly and self.weekdays:
            raise ValueError("weekdays 只在 frequency=weekly 时使用，其他频次请去掉该字段。")

        # 规则 4：日期区间
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError(
                f"end_date（{self.end_date}）不能早于 start_date（{self.start_date}）"
            )

        # 规则 5：重复时间点没有意义
        if len(set(self.times)) != len(self.times):
            raise ValueError(f"times 中存在重复的时间点：{self.times}，请合并后重填。")

        # 归一化：时间排序，方便后续展示和比对
        self.times = sorted(self.times)
        return self


# ======================================================================
# 2. 查询用药计划 / 服药记录
# ======================================================================
class QueryScheduleParams(BaseModel):
    """查询某天的用药安排、还有哪些药没吃、或者过去的服药记录。

    触发话术示例：
        「我今天要吃什么药」「降压药吃了吗」「我早上吃过药了没有」
    """

    medicine_name: str | None = Field(
        None,
        max_length=50,
        description="要查询的药品名称。不填表示查询该日期的全部用药计划，这是最常见的情况。",
    )
    # 坑：字段名如果直接叫 date，会在类命名空间里把 datetime.date 类型遮蔽掉，
    # Pydantic 解析 "date | None" 时会拿到 FieldInfo 而报 TypeError。
    # 所以这里的类型注解统一用别名 DateType。
    date: DateType | None = Field(
        None,
        description="要查询哪一天的用药计划，格式 YYYY-MM-DD。不填表示今天。老人说「昨天」时请换算成具体日期。",
    )
    un_taken_only: bool = Field(
        False,
        description="是否只看还没吃、还没确认的药。老人问「还有哪些药没吃」时填 true。",
    )
    include_history: bool = Field(
        False,
        description="是否附带最近的历史服药记录。老人问「我前几天吃了什么」时填 true。",
    )
    target_person: str | None = Field(
        None,
        description="要查询哪位老人的记录。不填表示当前说话人本人。",
    )


# ======================================================================
# 3. 修改提醒
# ======================================================================
class UpdateReminderParams(BaseModel):
    """调整已有提醒的时间 / 剂量 / 频次。

    触发话术示例：
        「把晚上的药改成九点」「降压药我改成吃半片」
    """

    reminder_id: str | None = Field(
        None,
        description="要修改的提醒 ID。只有在上下文里已经明确知道 ID（例如上一轮查询结果里给了）时才填。",
    )
    medicine_name: str | None = Field(
        None,
        max_length=50,
        description="按药名定位要修改的提醒。不知道 reminder_id 时用这个。若同一药名有多条提醒，执行时会让老人再确认。",
    )
    new_times: list[str] | None = Field(
        None,
        min_length=1,
        max_length=6,
        description="新的提醒时间点数组，HH:mm 格式。注意这里给的是【完整的新时间列表】，不是增量。例如原来 ['08:00','20:00']，老人说晚上改九点，应填 ['08:00','21:00']。",
    )
    new_dosage: float | None = Field(None, gt=0, le=100, description="新的单次剂量数值。")
    new_dosage_unit: DosageUnit | None = Field(None, description="新的剂量单位。")
    new_frequency: Frequency | None = Field(
        None,
        description="新的服药频次。注意：改了频次通常也要一起给出 new_times，否则会出现时间点个数对不上的情况。",
    )
    new_timing: Timing | None = Field(None, description="新的服药时机，例如从饭后改到饭前。")
    new_end_date: date | None = Field(
        None, description="新的结束日期，格式 YYYY-MM-DD。用于「吃到月底就不吃了」这类说法。"
    )
    target_person: str | None = Field(None, description="要修改哪位老人的提醒。不填表示当前说话人。")

    @field_validator("new_times")
    @classmethod
    def _validate_times(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _check_times_format(v)

    @model_validator(mode="after")
    def _cross_field_check(self) -> "UpdateReminderParams":
        if not self.reminder_id and not self.medicine_name:
            raise ValueError(
                "必须提供 reminder_id 或 medicine_name 来定位要修改的提醒。"
                "老人说「把那个药改了」但没说是哪个药时，请先追问药名。"
            )
        changes = {
            "new_times": self.new_times,
            "new_dosage": self.new_dosage,
            "new_dosage_unit": self.new_dosage_unit,
            "new_frequency": self.new_frequency,
            "new_timing": self.new_timing,
            "new_end_date": self.new_end_date,
        }
        if all(v is None for v in changes.values()):
            raise ValueError(
                "至少要提供一个要修改的字段（new_times / new_dosage / new_frequency / "
                "new_timing / new_end_date）。请追问老人想把什么改成什么。"
            )
        return self


# ======================================================================
# 4. 取消提醒
# ======================================================================
class CancelReminderParams(BaseModel):
    """停用一条用药提醒。

    触发话术示例：
        「我不想吃那个药了，别提醒我了」「把阿司匹林的提醒删掉」

    注意：这是高风险操作。停药可能是医生调整方案，也可能是老人忘了医嘱。
    执行前一定要复述确认（由 Agent 层基于 risk_level 触发）。
    """

    reminder_id: str | None = Field(None, description="要取消的提醒 ID。")
    medicine_name: str | None = Field(
        None, max_length=50, description="按药名定位要取消的提醒。"
    )
    keep_history: bool = Field(
        True,
        description="是否保留历史服药记录。默认 true，只停用提醒、不删除数据。只有老人明确说「删掉记录」时才填 false。",
    )
    reason: str | None = Field(
        None,
        max_length=200,
        description="取消原因。老人说「医生让我停药了」这类信息一定要记下来。",
    )
    target_person: str | None = Field(None, description="要取消哪位老人的提醒。不填表示当前说话人。")

    @model_validator(mode="after")
    def _cross_field_check(self) -> "CancelReminderParams":
        if not self.reminder_id and not self.medicine_name:
            raise ValueError(
                "必须提供 reminder_id 或 medicine_name 来定位要取消的提醒。"
                "不确定老人指的是哪个药时，请先追问。"
            )
        return self


# ======================================================================
# 5. 确认已服药
# ======================================================================
class ConfirmTakenParams(BaseModel):
    """老人主动说自己已经吃过药了。

    触发话术示例：
        「我吃过了」「刚吃完降压药」

    这是「反向查询/反馈」的入口，对应图1里「老人问救助来了吗，可以查询进度给出反馈」那个思路：
    老人不只是被动接收提醒，也能主动上报状态。
    """

    medicine_name: str | None = Field(
        None,
        max_length=50,
        description="已服用的药品名称。不填表示确认该时间点所有待服提醒都已经吃了。",
    )
    taken_at: datetime | None = Field(
        None,
        description="实际服用时间，ISO 格式。不填表示现在。老人说「早上吃的」时请填当天早上对应的时间。",
    )
    target_person: str | None = Field(None, description="哪位老人服的药。不填表示当前说话人。")
