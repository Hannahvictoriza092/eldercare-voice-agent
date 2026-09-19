"""把机器格式转成老人听得懂的口语。

【为什么放在共享层】
三个 skill 都需要：
  用药提醒 -> 「早上 8 点」「今天」
  呼救     -> 「救护车 10 分钟前出发的」
  健康反馈 -> 「上周」「这个月」
各写一份必然出现「早上 8 点」和「8 点上午」这种不一致，所以统一放这里。

【硬性约定】
永远不要把 ISO 格式（2026-09-19、08:00:00、PT10M）直接念给老人听。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

# 星期中文名，索引对齐 date.weekday()（0=周一）
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def hour_cn(hour: int) -> str:
    """把 24 小时制的钟点说成口语。8 -> 早上 8，20 -> 晚上 8。"""
    if hour < 6:
        return f"凌晨 {hour}"
    if hour < 12:
        return f"早上 {hour}"
    if hour == 12:
        return "中午 12"
    if hour < 18:
        return f"下午 {hour - 12}"
    return f"晚上 {hour - 12}"


def time_cn(slot: str) -> str:
    """'08:00' -> '早上 8 点'；'20:30' -> '晚上 8 点 30 分'。"""
    h, m = slot.split(":")[:2]
    label = hour_cn(int(h))
    return f"{label} 点" if m == "00" else f"{label} 点 {int(m)} 分"


def times_cn(times: list[str]) -> str:
    """['08:00', '20:00'] -> '早上 8 点、晚上 8 点'。会自动排序。"""
    return "、".join(time_cn(t) for t in sorted(times))


def day_cn(day: date, today: date | None = None) -> str:
    """相对日期优先。今天是 9-19 时，9-19 -> '今天'，9-20 -> '明天'。

    绝对日期只说「9 月 20 日」，不念年份——对 80 岁老人来说「2026」是噪音。
    """
    today = today or date.today()
    delta = (day - today).days
    relative = {0: "今天", 1: "明天", 2: "后天", -1: "昨天", -2: "前天"}
    if delta in relative:
        return relative[delta]
    return f"{day.month} 月 {day.day} 日"


def datetime_cn(dt: datetime, now: datetime | None = None) -> str:
    """'今天早上 8 点 3 分' 这种完整说法。"""
    now = now or datetime.now()
    return f"{day_cn(dt.date(), now.date())}{time_cn(dt.strftime('%H:%M'))}"


def ago_cn(minutes: float) -> str:
    """'10 分钟前' / '2 小时前'。呼救报进度、健康反馈报事件时间都要用。"""
    if minutes < 1:
        return "刚刚"
    if minutes < 60:
        return f"{int(minutes)} 分钟前"
    if minutes < 60 * 24:
        return f"{int(minutes // 60)} 小时前"
    return f"{int(minutes // (60 * 24))} 天前"


def in_future_cn(minutes: float) -> str:
    """'还有 10 分钟' / '还有 2 小时'。呼救预计到达时间用。"""
    if minutes < 1:
        return "马上就到"
    if minutes < 60:
        return f"还有 {int(minutes)} 分钟"
    return f"还有 {int(minutes // 60)} 小时"


def week_range_cn(day: date | None = None) -> str:
    """本周一到周日的说法，健康反馈组做周报标题用。"""
    day = day or date.today()
    monday = day - timedelta(days=day.weekday())
    sunday = monday + timedelta(days=6)
    return f"{monday.month} 月 {monday.day} 日到 {sunday.month} 月 {sunday.day} 日"


def weekday_cn(index: int) -> str:
    """0 -> 周一。越界时返回原值，不抛异常（避免播报环节炸掉）。"""
    return WEEKDAY_CN[index] if 0 <= index < 7 else str(index)
