"""健康和照顾反馈 skill 的执行逻辑。

输入一定是已经校验过的 Pydantic 参数，输出一定是 SkillResult。
所有「念给老人听的话」都从 messages.py 拿，不在这里硬编码字符串。

【数据源设计】
本 skill 是「下游」，消费用药提醒产出的 MedicationLog 和呼救产出的 Incident。
按约定不 import 其他 skill 的私有模块，而是通过一个抽象的 EventStore 接口读取。

    EventStore（共享事件流）
        ├── medication_logs(person_id, start, end) -> list[MedicationLog]
        └── incidents(person_id, start, end)       -> list[Incident]

共享事件流的具体存储还没定稿，所以这里先给一个 InMemoryEventStore 假实现，
方便测试和联调。等共享事件流定了，只要实现同一个接口，executor 一行都不用改。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Any

from common.base import SkillContext, SkillResult
from common.domain import (
    Incident,
    MedicationLog,
    MedicationStatus,
    Notification,
    NotifyTarget,
    Urgency,
)

from . import messages as msg
from .schema import (
    GenerateWeeklyParams,
    QueryArchiveParams,
    QuerySummaryParams,
    SendReportParams,
)
from .store import HealthArchiveStore, WeeklySnapshot

SKILL_NAME = "health_report"


# ======================================================================
# 数据源接口（共享事件流）
# ======================================================================
class EventStore(ABC):
    """共享事件流的读取接口。

    用药提醒产出 MedicationLog，呼救产出 Incident。
    本 skill 只读不写。共享事件流定了之后，实现这个接口即可接入。
    """

    @abstractmethod
    def medication_logs(
        self, person_id: str, start: date, end: date
    ) -> list[MedicationLog]:
        """取某位老人 [start, end] 区间内的服药记录（含漏服/跳过）。"""

    @abstractmethod
    def incidents(self, person_id: str, start: date, end: date) -> list[Incident]:
        """取某位老人 [start, end] 区间内的异常事件。"""


class InMemoryEventStore(EventStore):
    """内存版事件流，给测试和联调用。数据由外部注入。"""

    def __init__(
        self,
        medication_logs: list[MedicationLog] | None = None,
        incidents: list[Incident] | None = None,
    ):
        self._logs = medication_logs or []
        self._incidents = incidents or []

    def medication_logs(
        self, person_id: str, start: date, end: date
    ) -> list[MedicationLog]:
        return [
            log
            for log in self._logs
            if log.person_id == person_id
            and start <= log.scheduled_at.date() <= end
        ]

    def incidents(self, person_id: str, start: date, end: date) -> list[Incident]:
        return [
            inc
            for inc in self._incidents
            if inc.person_id == person_id
            and start <= inc.occurred_at.date() <= end
        ]


# ======================================================================
# 周报统计
# ======================================================================
class WeeklyStats:
    """某一周的统计结果。"""

    def __init__(self, week_start: date):
        self.week_start = week_start
        self.planned = 0            # 计划服药次数
        self.taken = 0              # 按时完成次数
        self.missed = 0             # 漏服次数
        self.missed_medicines: list[str] = []  # 漏服的药名（去重）
        self.incidents = 0          # 异常事件次数

    @property
    def adherence(self) -> float | None:
        """依从率百分比。没有计划服药时返回 None（数据不足）。"""
        if self.planned == 0:
            return None
        return round(self.taken / self.planned * 100, 1)

    def to_dict(self) -> dict:
        """转成可序列化的 dict（adherence 是 property，__dict__ 里没有，要显式带上）。"""
        return {
            "week_start": self.week_start.isoformat(),
            "planned": self.planned,
            "taken": self.taken,
            "missed": self.missed,
            "missed_medicines": list(self.missed_medicines),
            "incidents": self.incidents,
            "adherence": self.adherence,
        }


def _week_range(week_start: date) -> tuple[date, date]:
    """给定周一，返回 [周一, 周日] 区间。"""
    return week_start, week_start + timedelta(days=6)


def _collect_stats(
    store: EventStore, person_id: str, week_start: date
) -> WeeklyStats:
    """从事件流统计某一周的服药和异常情况。"""
    start, end = _week_range(week_start)
    stats = WeeklyStats(week_start)

    for log in store.medication_logs(person_id, start, end):
        stats.planned += 1
        if log.status == MedicationStatus.TAKEN:
            stats.taken += 1
        elif log.status == MedicationStatus.MISSED:
            stats.missed += 1
            if log.medicine_name not in stats.missed_medicines:
                stats.missed_medicines.append(log.medicine_name)

    stats.incidents = len(store.incidents(person_id, start, end))
    return stats


def _trend_text(cur: WeeklyStats, prev: WeeklyStats | None) -> str:
    """生成「与上周对比」的正式文案。"""
    if prev is None or prev.planned == 0:
        return msg.TREND_NO_PREV

    parts: list[str] = []

    # 依从率对比
    if cur.adherence is not None and prev.adherence is not None:
        delta = round(cur.adherence - prev.adherence, 1)
        if delta > 0:
            parts.append(
                msg.render(
                    msg.TREND_ADHERENCE_UP,
                    delta=delta,
                    prev=prev.adherence,
                    cur=cur.adherence,
                )
            )
        elif delta < 0:
            parts.append(
                msg.render(
                    msg.TREND_ADHERENCE_DOWN,
                    delta=abs(delta),
                    prev=prev.adherence,
                    cur=cur.adherence,
                )
            )
        else:
            parts.append(msg.render(msg.TREND_ADHERENCE_SAME, cur=cur.adherence))

    # 漏服对比
    if cur.missed > prev.missed:
        parts.append(msg.render(msg.TREND_MISSED_UP, delta=cur.missed - prev.missed))
    elif cur.missed < prev.missed:
        parts.append(msg.render(msg.TREND_MISSED_DOWN, delta=prev.missed - cur.missed))
    else:
        parts.append(msg.TREND_MISSED_SAME)

    # 异常事件对比
    if cur.incidents > prev.incidents:
        parts.append(
            msg.render(msg.TREND_INCIDENT_UP, delta=cur.incidents - prev.incidents)
        )
    elif cur.incidents < prev.incidents:
        parts.append(
            msg.render(msg.TREND_INCIDENT_DOWN, delta=prev.incidents - cur.incidents)
        )
    else:
        parts.append(msg.TREND_INCIDENT_SAME)

    return " ".join(parts)


# ======================================================================
# 执行器
# ======================================================================
class HealthReportExecutor:
    def __init__(
        self,
        store: EventStore | None = None,
        archive_store: HealthArchiveStore | None = None,
    ):
        self.store = store or InMemoryEventStore()
        self.archive_store = archive_store or HealthArchiveStore()

    # ---------------- 内部工具 ----------------
    def _ok(self, action: str, speech: str, **data: Any) -> SkillResult:
        return SkillResult(ok=True, skill=SKILL_NAME, action=action, speech=speech, data=data)

    def _followup(self, action: str, question: str, **data: Any) -> SkillResult:
        return SkillResult(
            ok=False,
            skill=SKILL_NAME,
            action=action,
            speech=question,
            need_followup=True,
            followup_question=question,
            data=data,
        )

    def _resolve_week(self, week_start: date | None, ctx: SkillContext) -> date:
        """没给周起始日时，默认本周一。"""
        if week_start is not None:
            return week_start
        today = ctx.now.date()
        return today - timedelta(days=today.weekday())

    def _person(self, person_id: str, ctx: SkillContext) -> str:
        """person_id 是必填字段，但兜底用当前说话人。"""
        return person_id or ctx.speaker_id

    # ---------------- 1. generate_weekly ----------------
    def generate_weekly(self, p: GenerateWeeklyParams, ctx: SkillContext) -> SkillResult:
        person = self._person(p.person_id, ctx)
        week_start = self._resolve_week(p.week_start, ctx)
        start, end = _week_range(week_start)
        week_range = msg._week_range(week_start)

        stats = _collect_stats(self.store, person, week_start)

        # 数据不足：没有计划服药，给「数据不足」提示，不抛错
        if stats.planned == 0:
            speech = msg.render(
                msg.WEEKLY_GENERATED_INSUFFICIENT, person=ctx.speaker_name
            )
            return self._ok(
                "generate_weekly",
                speech,
                person_id=person,
                week_start=week_start.isoformat(),
                insufficient=True,
                stats=stats.to_dict(),
            )

        # 生成正式周报正文（给医生/子女看）
        body = msg.render(
            msg.WEEKLY_BODY,
            name=ctx.speaker_name,
            week_range=week_range,
            planned=stats.planned,
            taken=stats.taken,
            adherence=stats.adherence,
            missed=stats.missed,
            missed_medicines="、".join(stats.missed_medicines) or "无",
            incidents=stats.incidents,
            trend=_trend_text(stats, self._prev_snapshot(person, week_start)),
        )

        # 给老人听的一句话摘要
        brief = msg.describe_weekly_brief(
            stats.adherence, stats.missed, stats.incidents, week_range
        )
        speech = msg.render(
            msg.WEEKLY_GENERATED, person=ctx.speaker_name, brief=brief
        )

        # 顺手把这一周的画像快照落进个性化档案
        self._save_snapshot(person, stats)

        return self._ok(
            "generate_weekly",
            speech,
            person_id=person,
            week_start=week_start.isoformat(),
            report_body=body,
            stats=stats.to_dict(),
        )

    # ---------------- 2. send_report ----------------
    def send_report(self, p: SendReportParams, ctx: SkillContext) -> SkillResult:
        person = self._person(p.person_id, ctx)
        week_start = self._resolve_week(p.week_start, ctx)
        week_range = msg._week_range(week_start)

        stats = _collect_stats(self.store, person, week_start)

        if stats.planned == 0:
            speech = msg.render(
                msg.WEEKLY_GENERATED_INSUFFICIENT, person=ctx.speaker_name
            )
            return self._ok(
                "send_report",
                speech,
                person_id=person,
                week_start=week_start.isoformat(),
                insufficient=True,
            )

        body = msg.render(
            msg.WEEKLY_BODY,
            name=ctx.speaker_name,
            week_range=week_range,
            planned=stats.planned,
            taken=stats.taken,
            adherence=stats.adherence,
            missed=stats.missed,
            missed_medicines="、".join(stats.missed_medicines) or "无",
            incidents=stats.incidents,
            trend=_trend_text(stats, self._prev_snapshot(person, week_start)),
        )

        # 产出 Notification 对象（只产出，不负责发送）
        notification = Notification(
            id=f"hr_{uuid4_hex()}",
            person_id=person,
            targets=p.targets,
            urgency=Urgency.NORMAL,
            title=msg.render(msg.WEEKLY_TITLE, name=ctx.speaker_name, week_range=week_range),
            body=body,
            created_at=ctx.now,
        )

        self._save_snapshot(person, stats)

        speech = msg.render(
            msg.SEND_OK,
            person=ctx.speaker_name,
            targets=msg.describe_targets_cn([t.value for t in p.targets]),
        )
        return self._ok(
            "send_report",
            speech,
            person_id=person,
            week_start=week_start.isoformat(),
            notification=notification.model_dump(),
        )

    # ---------------- 3. query_archive ----------------
    def query_archive(self, p: QueryArchiveParams, ctx: SkillContext) -> SkillResult:
        person = self._person(p.person_id, ctx)
        archive = self.archive_store.get(person)

        if archive is None or not archive.snapshots:
            speech = msg.render(msg.ARCHIVE_NO_DATA, person=ctx.speaker_name)
            return self._ok(
                "query_archive",
                speech,
                person_id=person,
                snapshots=[],
            )

        # 按时间范围过滤
        snapshots = archive.snapshots
        if p.start_date:
            snapshots = [s for s in snapshots if s.week_start >= p.start_date.isoformat()]
        if p.end_date:
            snapshots = [s for s in snapshots if s.week_start <= p.end_date.isoformat()]

        if not snapshots:
            speech = msg.render(msg.ARCHIVE_NO_DATA, person=ctx.speaker_name)
            return self._ok(
                "query_archive",
                speech,
                person_id=person,
                snapshots=[],
            )

        # 生成给老人听的长期趋势摘要
        summary = self._archive_summary_cn(snapshots)
        trend = self._archive_trend_cn(snapshots)
        speech = msg.render(
            msg.ARCHIVE_OK, person=ctx.speaker_name, summary=summary, trend=trend
        )

        return self._ok(
            "query_archive",
            speech,
            person_id=person,
            snapshots=[s.__dict__ for s in snapshots],
        )

    # ---------------- 4. query_summary ----------------
    def query_summary(self, p: QuerySummaryParams, ctx: SkillContext) -> SkillResult:
        person = self._person(p.person_id, ctx)
        days = p.days or 7
        end = ctx.now.date()
        start = end - timedelta(days=days - 1)

        logs = self.store.medication_logs(person, start, end)
        incidents = self.store.incidents(person, start, end)

        # 没有服药记录
        if not logs:
            speech = msg.render(
                msg.SUMMARY_ADHERENCE_NO_DATA,
                person=ctx.speaker_name,
                days=days,
            )
            return self._ok(
                "query_summary",
                speech,
                person_id=person,
                days=days,
                planned=0,
                taken=0,
                missed=0,
                incidents=len(incidents),
            )

        planned = len(logs)
        taken = sum(1 for log in logs if log.status == MedicationStatus.TAKEN)
        missed = sum(1 for log in logs if log.status == MedicationStatus.MISSED)
        missed_medicines = sorted(
            {log.medicine_name for log in logs if log.status == MedicationStatus.MISSED}
        )
        adherence = round(taken / planned * 100, 1) if planned else None

        # 老人问「吃药按时吗」优先答依从性；有异常事件也顺带提一句
        if missed:
            speech = msg.render(
                msg.SUMMARY_ADHERENCE_MISSED,
                person=ctx.speaker_name,
                days=days,
                missed=missed,
                missed_medicines="、".join(missed_medicines) or "几种药",
            )
        else:
            speech = msg.render(
                msg.SUMMARY_ADHERENCE_GOOD,
                person=ctx.speaker_name,
                days=days,
                taken=taken,
                adherence=adherence,
            )

        if incidents:
            speech += msg.render(
                msg.SUMMARY_INCIDENT_SOME,
                person=ctx.speaker_name,
                days=days,
                incidents=len(incidents),
            )

        return self._ok(
            "query_summary",
            speech,
            person_id=person,
            days=days,
            planned=planned,
            taken=taken,
            missed=missed,
            missed_medicines=missed_medicines,
            adherence=adherence,
            incidents=len(incidents),
        )

    # ---------------- 档案辅助 ----------------
    def _prev_snapshot(self, person: str, week_start: date) -> WeeklySnapshot | None:
        """取上一周的画像快照（用于趋势对比）。"""
        archive = self.archive_store.get(person)
        if archive is None:
            return None
        prev_week = (week_start - timedelta(days=7)).isoformat()
        return archive.snapshot_for(prev_week)

    def _save_snapshot(self, person: str, stats: WeeklyStats) -> None:
        """把某一周的统计落进个性化档案。"""
        snapshot = WeeklySnapshot(
            week_start=stats.week_start.isoformat(),
            adherence=stats.adherence,
            planned=stats.planned,
            taken=stats.taken,
            missed=stats.missed,
            missed_medicines=list(stats.missed_medicines),
            incidents=stats.incidents,
        )
        self.archive_store.save_snapshot(person, snapshot)

    def _archive_summary_cn(self, snapshots: list[WeeklySnapshot]) -> str:
        """把多周快照压成一句给老人听的摘要。"""
        latest = snapshots[-1]
        if latest.adherence is None:
            return "数据还在积累中"
        parts = [f"最近 {len(snapshots)} 周服药依从率在 {latest.adherence}% 左右"]
        if latest.missed:
            parts.append(f"有 {latest.missed} 次漏服")
        if latest.incidents:
            parts.append(f"有 {latest.incidents} 起异常情况")
        return "，".join(parts)

    def _archive_trend_cn(self, snapshots: list[WeeklySnapshot]) -> str:
        """多周快照的长期趋势（给老人听，口语化）。"""
        if len(snapshots) < 2:
            return "记录还不多，趋势还不明显"
        first = snapshots[0]
        last = snapshots[-1]
        if first.adherence is None or last.adherence is None:
            return "趋势还不明显"
        if last.adherence > first.adherence:
            return "依从率在慢慢变好"
        if last.adherence < first.adherence:
            return "依从率有点下滑，得多留意"
        return "依从率一直挺稳定"


def uuid4_hex() -> str:
    """生成通知 ID 用的短随机串。"""
    import uuid

    return uuid.uuid4().hex[:8]