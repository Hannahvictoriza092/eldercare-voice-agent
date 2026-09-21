"""用药提醒的语音话术模板。

为什么要单独一个文件：
1. 老人听的语气要统一、要短、要能听懂，不能把英文枚举念出来
2. 话术会反复改，集中放一处方便家属/医生帮着一起来调
3. 之后接 TTS 时，这里就是播报文案的唯一来源
"""

from __future__ import annotations

from datetime import date

from common import timefmt

from .schema import FREQUENCY_CN, TIMING_CN, UNIT_CN, DosageUnit, Frequency, Timing

# 时间/日期的口语化已抽到共享层（呼救、健康反馈也要用），
# 这里留别名，原来调用 msg._times_cn 的地方不用改。
_times_cn = timefmt.times_cn
_day_text = timefmt.day_cn


def _dosage_cn(dosage: float, unit: str) -> str:
    """把 0.5 + tablet 说成「半片」，让老人听得自然些。"""
    try:
        unit_cn = UNIT_CN[DosageUnit(unit)]
    except ValueError:
        unit_cn = unit
    if dosage == 0.5:
        return f"半{unit_cn}"
    if dosage == 0.25:
        return f"四分之一{unit_cn}"
    if float(dosage).is_integer():
        return f"{int(dosage)}{unit_cn}"
    return f"{dosage}{unit_cn}"


# ----------------------------------------------------------------------
# 创建
# ----------------------------------------------------------------------
CREATE_OK = (
    "{person}，已经帮您记好了：{medicine}，每次 {dosage}，{frequency}，{timing}，"
    "提醒时间是 {times}。到点我会喊您。"
)

CREATE_OK_WITH_RANGE = (
    "{person}，已经帮您记好了：{medicine}，每次 {dosage}，{frequency}，{timing}，"
    "提醒时间是 {times}，从 {start} 吃到 {end}。到点我会喊您。"
)

# 高风险：涉及新药或剂量变更时，让老人复述一遍
CREATE_CONFIRM_BACK = (
    "{person}，我确认一下：{medicine}，每次 {dosage}，{frequency}，{timing}，"
    "提醒时间 {times}，对吗？"
)

# ----------------------------------------------------------------------
# 查询
# ----------------------------------------------------------------------
QUERY_NO_PLAN = "{person}，{day}没有什么要吃的药，您可以放心休息。"
QUERY_ALL_DONE = "{person}，{day}的药都吃完啦，一共 {total} 次，您记得真好。"
QUERY_PENDING = "{person}，{day}还有 {pending} 次要吃：{plan}。"
QUERY_ONE_DONE = "{person}，{medicine}在{time}那次的记录是已经吃过了。"

# ----------------------------------------------------------------------
# 确认已服药
# ----------------------------------------------------------------------
TAKEN_OK = "好的{person}，已经帮您记上：{medicine}{time}吃过了。"
TAKEN_NOTHING_PENDING = "{person}，我这边没查到这会儿该吃的药，您是不是记错时间啦？"
TAKEN_NOT_FOUND = "{person}，我没找到{medicine}的用药提醒，要不要我帮您加一个？"

# ----------------------------------------------------------------------
# 修改
# ----------------------------------------------------------------------
UPDATE_OK = "{person}，{medicine}已经帮您改好了：{changes}。"
UPDATE_NEED_PICK = "{person}，我查到{medicine}有好几条提醒，您说的是{detail}哪一条呀？"

# ----------------------------------------------------------------------
# 取消
# ----------------------------------------------------------------------
CANCEL_CONFIRM = (
    "{person}，您是说以后不用再提醒您吃{medicine}了吗？"
    "停药的事最好先跟医生确认一下。要是确定，您跟我说一声「确定」就行。"
)
CANCEL_OK = "{person}，好的，以后不再提醒您吃{medicine}了。{reason_hint}"
CANCEL_OK_REASON_HINT = "我已经把原因记下来，会告诉您家里人。"
CANCEL_OK_NO_HINT = ""

# ----------------------------------------------------------------------
# 提醒触发（由调度器调用，不是 Qwen 生成）
# ----------------------------------------------------------------------
# 两套模板：知道老人名字时带称呼，不知道时用不带称呼的版本，
# 否则会播成「，该吃阿司匹林啦」这种开头带逗号的话。
REMIND = "{person}，该吃{medicine}啦，{dosage}，{timing}。吃完跟我说一声「吃了」。"
REMIND_NO_NAME = "该吃{medicine}啦，{dosage}，{timing}。吃完跟我说一声「吃了」。"
REMIND_AGAIN = "{person}，再提醒一次，{medicine}还没吃呢，{dosage}。"
REMIND_AGAIN_NO_NAME = "再提醒一次，{medicine}还没吃呢，{dosage}。"
# ★ 这句是发给【子女】的，不是念给老人的，所以用「麻烦您」。
# 调度器把它放进 notify_text 字段，别塞进 speech。
REMIND_ESCALATE = "{person}刚才的药一直没吃，麻烦您提醒一下。"

# ----------------------------------------------------------------------
# 错误 / 追问
# ----------------------------------------------------------------------
ASK_MEDICINE = "请问是哪种药呀？您说个名字我好记下来。"
ASK_DOSAGE = "这个药一次吃多少呢？比如一片还是半片？"
ASK_TIMES = "您想让我几点提醒您？比如早上八点。"
ASK_WEEKDAY = "是每周的星期几吃呢？"


def render(template: str, **kw) -> str:
    """统一渲染入口。缺变量时不要炸在播报环节。"""
    try:
        return template.format(**kw)
    except KeyError:
        return template


def describe_create(medicine: str, dosage: float, unit: str, frequency: str,
                    timing: str, times: list[str], start: date | None = None,
                    end: date | None = None, person: str = "") -> str:
    freq_cn = FREQUENCY_CN.get(Frequency(frequency), frequency)
    timing_cn = TIMING_CN.get(Timing(timing), timing)
    common = dict(
        person=person,
        medicine=medicine,
        dosage=_dosage_cn(dosage, unit),
        frequency=freq_cn,
        timing=timing_cn,
        times=_times_cn(times),
    )
    if end:
        return render(CREATE_OK_WITH_RANGE, start=start.isoformat() if start else "今天",
                      end=end.isoformat(), **common)
    return render(CREATE_OK, **common)


def describe_remind(medicine: str, dosage: float, unit: str, timing: str,
                    person: str = "", again: bool = False) -> str:
    """生成提醒播报。person 为空时自动切到不带称呼的模板，避免出现孤零零的逗号。"""
    timing_cn = TIMING_CN.get(Timing(timing), timing)
    if again:
        tmpl = REMIND_AGAIN if person else REMIND_AGAIN_NO_NAME
    else:
        tmpl = REMIND if person else REMIND_NO_NAME
    return render(tmpl, person=person, medicine=medicine,
                  dosage=_dosage_cn(dosage, unit), timing=timing_cn)
