"""健康和照顾反馈的文案模板。

为什么要单独一个文件：
1. 周报是【正式文案】，发给医院/子女，语气和用药提醒、呼救完全不同
2. 给老人听的话（query_summary）要口语化，和正式周报分开
3. 之后接 TTS / 出站通知时，这里就是文案的唯一来源

【一条重要约定】
  给老人听的话  -> 走 SkillResult.speech（口语化）
  发给医院/子女 -> 走 Notification.body（正式文案）
  两者不一样，别混用。
"""

from __future__ import annotations

from common import timefmt

# 时间/日期的口语化复用共享层
_day_text = timefmt.day_cn
_week_range = timefmt.week_range_cn


def render(template: str, **kw) -> str:
    """统一渲染入口。缺变量时不要炸在播报环节。"""
    try:
        return template.format(**kw)
    except KeyError:
        return template


# ----------------------------------------------------------------------
# 周报正文（正式文案，发给医院/子女）
# ----------------------------------------------------------------------
# 周报标题：给医生/子女看的，用「姓名 + 周范围」。
WEEKLY_TITLE = "{name} 健康周报（{week_range}）"

# 周报正文模板。所有数字由 executor 算好传进来，这里只负责排版。
WEEKLY_BODY = (
    "{name}本周健康情况汇总（{week_range}）：\n"
    "一、服药情况\n"
    "  计划服药 {planned} 次，按时完成 {taken} 次，依从率 {adherence}%。\n"
    "  漏服 {missed} 次，涉及：{missed_medicines}。\n"
    "二、异常事件\n"
    "  本周共 {incidents} 起（呼救/跌倒/健康异常）。\n"
    "三、与上周对比\n"
    "  {trend}\n"
    "以上数据供参考，不作为诊断依据。"
)

# 数据不足时的周报正文（不抛错，给「数据不足」提示）
WEEKLY_BODY_INSUFFICIENT = (
    "{name}本周健康数据不足（{week_range}），暂无法生成完整周报。"
    "建议继续观察，下周再汇总。"
)

# 趋势描述模板
TREND_ADHERENCE_UP = "服药依从率较上周上升 {delta} 个百分点（{prev}% → {cur}%）。"
TREND_ADHERENCE_DOWN = "服药依从率较上周下降 {delta} 个百分点（{prev}% → {cur}%）。"
TREND_ADHERENCE_SAME = "服药依从率与上周持平（{cur}%）。"
TREND_MISSED_UP = "漏服次数较上周增加 {delta} 次，需关注。"
TREND_MISSED_DOWN = "漏服次数较上周减少 {delta} 次。"
TREND_MISSED_SAME = "漏服次数与上周持平。"
TREND_INCIDENT_UP = "异常事件较上周增加 {delta} 起。"
TREND_INCIDENT_DOWN = "异常事件较上周减少 {delta} 起。"
TREND_INCIDENT_SAME = "异常事件与上周持平。"
TREND_NO_PREV = "上周数据不足，暂无对比。"


# ----------------------------------------------------------------------
# 给老人听的话（口语化）
# ----------------------------------------------------------------------
# 快速问答：本周吃药按时吗
SUMMARY_ADHERENCE_GOOD = (
    "{person}，最近 {days} 天您吃药挺准时的，{taken} 次都按时吃了，"
    "依从率 {adherence}%，继续保持哈。"
)
SUMMARY_ADHERENCE_MISSED = (
    "{person}，最近 {days} 天您有 {missed} 次忘了吃药，"
    "主要是{missed_medicines}。下回到点我多提醒您几次，您也留意着点。"
)
SUMMARY_ADHERENCE_NO_DATA = (
    "{person}，最近 {days} 天我这边没查到您的服药记录，"
    "是不是还没开始用药呀？"
)

# 快速问答：这周有没有出什么事
SUMMARY_INCIDENT_NONE = "{person}，最近 {days} 天没出什么异常情况，您可以放心。"
SUMMARY_INCIDENT_SOME = (
    "{person}，最近 {days} 天有 {incidents} 起异常情况，"
    "我已经记下来了，也会跟您家里人同步。"
)

# 快速问答：查档案
ARCHIVE_OK = (
    "{person}，这是您最近的情况：{summary}。"
    "长期来看{trend}。"
)
ARCHIVE_NO_DATA = "{person}，我这边还没有足够的记录来给您做长期分析，再积累一段时间哈。"

# 周报生成成功（预览，不发送）
WEEKLY_GENERATED = (
    "{person}，这周的报告我帮您整理好了：{brief}。"
    "要发给医生或家里人吗？跟我说一声就行。"
)
WEEKLY_GENERATED_INSUFFICIENT = (
    "{person}，这周的数据还不太够，暂时生成不了完整报告。"
    "等记录多一些我再帮您整理。"
)

# 周报发送成功
SEND_OK = "{person}，已经把这周的报告发给{targets}了。"
SEND_OK_NO_TARGET = "{person}，报告已经整理好了，您想发给谁呢？医生、家里人还是社区？"


# ----------------------------------------------------------------------
# 错误 / 追问
# ----------------------------------------------------------------------
ASK_PERSON = "请问是给哪位老人做健康反馈呀？"
ASK_TARGET = "您想把报告发给谁呢？医生、家里人还是社区？"
ASK_WEEK = "您说的是哪一周的情况呀？这周还是上周？"


def describe_weekly_brief(
    adherence: float | None,
    missed: int,
    incidents: int,
    week_range: str,
) -> str:
    """给老人听的周报一句话摘要（口语化，不念数字细节）。"""
    if adherence is None:
        return f"这周（{week_range}）数据还不太够，暂时整理不了完整报告。"
    parts = [f"这周（{week_range}）您吃药依从率是 {adherence}%"]
    if missed:
        parts.append(f"有 {missed} 次忘了吃")
    if incidents:
        parts.append(f"有 {incidents} 起异常情况")
    return "，".join(parts) + "。"


def describe_targets_cn(targets: list[str]) -> str:
    """把 NotifyTarget 枚举值翻译成中文接收方，用于念给老人听。"""
    mapping = {
        "family": "家里人",
        "hospital": "医生",
        "community": "社区",
    }
    names = [mapping.get(t, t) for t in targets]
    return "、".join(names)