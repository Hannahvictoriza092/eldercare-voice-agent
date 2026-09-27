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
    "  {medication}\n"
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
TREND_ADHERENCE_UP = "已有记录中的已服占比较上周上升 {delta} 个百分点（{prev}% → {cur}%）。"
TREND_ADHERENCE_DOWN = "已有记录中的已服占比较上周下降 {delta} 个百分点（{prev}% → {cur}%）。"
TREND_ADHERENCE_SAME = "已有记录中的已服占比与上周持平（{cur}%）。"
TREND_MISSED_UP = "漏服次数较上周增加 {delta} 次，需关注。"
TREND_MISSED_DOWN = "漏服次数较上周减少 {delta} 次。"
TREND_MISSED_SAME = "漏服次数与上周持平。"
TREND_INCIDENT_UP = "异常事件较上周增加 {delta} 起。"
TREND_INCIDENT_DOWN = "异常事件较上周减少 {delta} 起。"
TREND_INCIDENT_SAME = "异常事件与上周持平。"
TREND_NO_PREV = "上周数据不足，暂无对比。"
TREND_MEDICATION_INSUFFICIENT = "本周或上周缺少服药记录，暂不比较服药情况。"


# ----------------------------------------------------------------------
# 给老人听的话（口语化）
# ----------------------------------------------------------------------
# 快速问答：本周吃药按时吗
SUMMARY_RECORDS = "{person}，最近 {days} 天的情况是：{medication}"
SUMMARY_ADHERENCE_GOOD = "{person}，最近 {days} 天记录已服 {taken} 次，已有记录中的已服占比 {adherence}%。"
SUMMARY_ADHERENCE_MISSED = (
    "{person}，最近 {days} 天记录漏服 {missed} 次，"
    "主要是{missed_medicines}。下回到点我多提醒您几次，您也留意着点。"
)
SUMMARY_ADHERENCE_NO_DATA = (
    "{person}，最近 {days} 天我这边没查到您的服药记录，"
    "暂时无法判断服药情况。"
)

# 快速问答：这周有没有出什么事
SUMMARY_INCIDENT_NONE = "{person}，最近 {days} 天暂无异常事件记录。"
SUMMARY_INCIDENT_SOME = (
    "{person}，最近 {days} 天有 {incidents} 起异常情况，"
    "已经保存在记录中了。"
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
    "{person}，这周暂无可汇总的服药或异常事件记录，数据不足。"
    "暂时无法判断这周的情况。"
)

# 周报发送成功
SEND_OK = "{person}，报告已整理好，待发送给{targets}，目前还没有送达确认。"
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
    parts = [f"这周（{week_range}）暂无服药记录" if adherence is None
             else f"这周（{week_range}）已有服药记录中的已服占比是 {adherence}%（包括补服）"]
    if missed:
        parts.append(f"记录漏服 {missed} 次")
    if incidents:
        parts.append(f"有 {incidents} 起异常情况")
    return "，".join(parts) + "。"


def describe_medication(stats: dict) -> str:
    """只描述已落库记录；不把记录覆盖率当成真实服药依从性。"""
    if stats["record_count"] == 0:
        return "暂无服药记录，无法判断服药情况。"
    medicines = "、".join(stats["missed_medicines"]) or "无"
    return (
        f"服药记录共 {stats['record_count']} 次，已服 {stats['taken']} 次（包括补服），"
        f"漏服 {stats['missed']} 次，涉及：{medicines}；"
        f"主动跳过 {stats['skipped']} 次，待确认 {stats['pending']} 次。"
        f"已有记录中的已服占比 {stats['taken_ratio']}%。"
        "记录不一定覆盖全部应服次数，该占比不代表按时率或计划完成率。"
    )


def describe_targets_cn(targets: list[str]) -> str:
    """把 NotifyTarget 枚举值翻译成中文接收方，用于念给老人听。"""
    mapping = {
        "family": "家里人",
        "hospital": "医生",
        "community": "社区",
    }
    names = [mapping.get(t, t) for t in targets]
    return "、".join(names)
