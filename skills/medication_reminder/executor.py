"""用药提醒 skill 的执行逻辑。

输入一定是已经校验过的 Pydantic 参数，输出一定是 SkillResult。
所有「念给老人听的话」都从 messages.py 拿，不在这里硬编码字符串。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from common.base import SkillContext, SkillResult

from . import messages as msg
from .schema import (
    CancelReminderParams,
    ConfirmTakenParams,
    CreateReminderParams,
    QueryScheduleParams,
    UpdateReminderParams,
)
from .store import Reminder, ReminderStore

SKILL_NAME = "medication_reminder"
# 老人说「早上八点」时，允许前后多久内算「就是这一次」
SLOT_TOLERANCE_MIN = 90


def _slot_to_time(slot: str) -> time:
    h, m = slot.split(":")
    return time(int(h), int(m))


class MedicationExecutor:
    def __init__(self, store: ReminderStore | None = None):
        self.store = store or ReminderStore()

    # ==================================================================
    # 内部工具
    # ==================================================================
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

    def _plan_of_day(self, day: date, person: str,
                     medicine_name: str | None = None) -> list[dict[str, Any]]:
        """算出某人某天应该吃的所有「时间点」，并标注每条是否已服用。

        这是查询、确认服药、调度提醒三处共用的核心逻辑，所以抽出来。
        """
        plan: list[dict[str, Any]] = []
        for r in self.store.query(person=person, medicine_name=medicine_name, active=True):
            if not r.is_effective_on(day):
                continue
            taken = r.taken_slots(day)
            for slot in sorted(r.times):
                plan.append(
                    {
                        "reminder_id": r.id,
                        "medicine_name": r.medicine_name,
                        "dosage": r.dosage,
                        "dosage_unit": r.dosage_unit,
                        "timing": r.timing,
                        "slot": slot,
                        "taken": slot in taken,
                    }
                )
        plan.sort(key=lambda x: x["slot"])
        return plan

    def _slot_text(self, plan: list[dict[str, Any]]) -> str:
        """把待服计划说成一句人话：早上 8 点吃阿司匹林 1 片、晚上 8 点吃二甲双胍 2 粒。"""
        parts = []
        for item in plan:
            from .messages import _times_cn

            parts.append(
                f"{_times_cn([item['slot']])}吃{item['medicine_name']}"
                f"{msg._dosage_cn(item['dosage'], item['dosage_unit'])}"
            )
        return "、".join(parts)

    def _resolve(self, person: str, reminder_id: str | None,
                 medicine_name: str | None) -> list[Reminder]:
        """定位要操作的提醒。优先 ID，其次药名模糊匹配。"""
        if reminder_id:
            r = self.store.get(reminder_id)
            return [r] if r and r.person == person and r.active else []
        return self.store.query(person=person, medicine_name=medicine_name, active=True)

    # ==================================================================
    # 1. create —— 新增提醒
    # ==================================================================
    def create(self, p: CreateReminderParams, ctx: SkillContext) -> SkillResult:
        person = ctx.person(p.target_person)

        # 同一个人、同一种药、同样的时间点，重复设置就直接合并提示，避免越堆越多
        for r in self.store.query(person=person, medicine_name=p.medicine_name, active=True):
            if sorted(r.times) == sorted(p.times) and r.frequency == p.frequency.value:
                return self._ok(
                    "create",
                    f"{ctx.speaker_name}，{p.medicine_name}的提醒之前已经设置过了，"
                    f"时间是{msg._times_cn(r.times)}，我就不重复加啦。"
                    f"要是想改时间，跟我说一声就行。",
                    reminder_id=r.id,
                    duplicated=True,
                )

        reminder = Reminder(
            id=self.store.new_id(),
            person=person,
            medicine_name=p.medicine_name,
            dosage=p.dosage,
            dosage_unit=p.dosage_unit.value,
            frequency=p.frequency.value,
            times=list(p.times),
            timing=p.timing.value,
            weekdays=list(p.weekdays or []),
            start_date=(p.start_date or ctx.now.date()).isoformat(),
            end_date=p.end_date.isoformat() if p.end_date else None,
            note=p.note,
        )
        self.store.add(reminder)

        speech = msg.describe_create(
            medicine=reminder.medicine_name,
            dosage=reminder.dosage,
            unit=reminder.dosage_unit,
            frequency=reminder.frequency,
            timing=reminder.timing,
            times=reminder.times,
            start=p.start_date and date.fromisoformat(reminder.start_date),
            end=p.end_date,
            person=ctx.speaker_name,
        )
        return self._ok(
            "create",
            speech,
            reminder_id=reminder.id,
            medicine_name=reminder.medicine_name,
            times=reminder.times,
            # 高风险动作，交由 Agent 层决定要不要让老人复述确认
            require_confirm_back=True,
        )

    # ==================================================================
    # 2. query —— 查询用药计划 / 服药记录
    # ==================================================================
    def query(self, p: QueryScheduleParams, ctx: SkillContext) -> SkillResult:
        person = ctx.person(p.target_person)
        day = p.date or ctx.now.date()
        day_text = msg._day_text(day, ctx.now.date())  # 念给老人听要口语化

        all_plan = self._plan_of_day(day, person, p.medicine_name)
        done = [i for i in all_plan if i["taken"]]
        todo = [i for i in all_plan if not i["taken"]]
        # un_taken_only 只影响返回给上层的明细，不影响播报内容
        plan = todo if p.un_taken_only else all_plan

        if not all_plan:
            speech = msg.render(msg.QUERY_NO_PLAN, person=ctx.speaker_name, day=day_text)
        elif not todo:
            speech = msg.render(
                msg.QUERY_ALL_DONE, person=ctx.speaker_name,
                day=day_text, total=len(done),
            )
        else:
            speech = msg.render(
                msg.QUERY_PENDING, person=ctx.speaker_name, day=day_text,
                pending=len(todo), plan=self._slot_text(todo),
            )

        return self._ok(
            "query",
            speech,
            date=day.isoformat(),
            plan=plan,
            pending=todo,
            done=done,
            history=self._history(person, p.medicine_name) if p.include_history else [],
        )

    def _history(self, person: str, medicine_name: str | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in self.store.query(person=person, medicine_name=medicine_name, active=None):
            for log in r.taken_log:
                out.append({"medicine_name": r.medicine_name, **log})
        out.sort(key=lambda x: (x["date"], x["slot"]), reverse=True)
        return out[:30]

    # ==================================================================
    # 3. update —— 修改提醒
    # ==================================================================
    def update(self, p: UpdateReminderParams, ctx: SkillContext) -> SkillResult:
        person = ctx.person(p.target_person)
        matched = self._resolve(person, p.reminder_id, p.medicine_name)

        if not matched:
            return self._followup(
                "update",
                f"{ctx.speaker_name}，我没找到{p.medicine_name or '这个药'}的提醒，"
                f"您是想新加一个吗？",
                medicine_name=p.medicine_name,
            )

        if len(matched) > 1 and not p.reminder_id:
            detail = "，".join(f"{r.medicine_name}（{msg._times_cn(r.times)}）" for r in matched)
            return self._followup(
                "update",
                msg.render(msg.UPDATE_NEED_PICK, person=ctx.speaker_name,
                           medicine=p.medicine_name, detail=detail),
                candidates=[{"reminder_id": r.id, "medicine_name": r.medicine_name,
                             "times": r.times} for r in matched],
            )

        r = matched[0]
        changes: list[str] = []

        if p.new_dosage is not None:
            r.dosage = p.new_dosage
            changes.append(f"每次 {msg._dosage_cn(p.new_dosage, p.new_dosage_unit or r.dosage_unit)}")
        if p.new_dosage_unit is not None:
            r.dosage_unit = p.new_dosage_unit.value
        if p.new_frequency is not None:
            r.frequency = p.new_frequency.value
            changes.append(msg.FREQUENCY_CN.get(p.new_frequency, p.new_frequency.value))
        if p.new_timing is not None:
            r.timing = p.new_timing.value
            changes.append(msg.TIMING_CN.get(p.new_timing, p.new_timing.value))
        if p.new_times is not None:
            r.times = sorted(p.new_times)
            changes.append(f"提醒时间改成 {msg._times_cn(r.times)}")
        if p.new_end_date is not None:
            r.end_date = p.new_end_date.isoformat()
            changes.append(f"吃到 {r.end_date} 为止")

        # 改完复查一致性：比如从每日两次改成每日三次，但时间点还是 2 个
        if r.frequency in ("once_daily", "twice_daily", "three_times_daily",
                           "every_other_day", "weekly"):
            from .schema import FREQUENCY_TIME_COUNT, Frequency

            expected = FREQUENCY_TIME_COUNT[Frequency(r.frequency)]
            if len(r.times) != expected:
                return self._followup(
                    "update",
                    f"{ctx.speaker_name}，{r.medicine_name}改成"
                    f"{msg.FREQUENCY_CN[Frequency(r.frequency)]}之后，"
                    f"需要 {expected} 个提醒时间，现在只有 {len(r.times)} 个。"
                    f"您想定在哪几个点呢？",
                    reminder_id=r.id,
                    need_times=True,
                )

        self.store.update(r)
        speech = msg.render(
            msg.UPDATE_OK,
            person=ctx.speaker_name,
            medicine=r.medicine_name,
            changes="，".join(changes) or "已更新",
            times=msg._times_cn(r.times),
        )
        return self._ok("update", speech, reminder_id=r.id, changes=changes)

    # ==================================================================
    # 4. cancel —— 取消提醒
    # ==================================================================
    def cancel(self, p: CancelReminderParams, ctx: SkillContext) -> SkillResult:
        person = ctx.person(p.target_person)
        matched = self._resolve(person, p.reminder_id, p.medicine_name)

        if not matched:
            return self._followup(
                "cancel",
                f"{ctx.speaker_name}，我这儿没有{p.medicine_name or '这个药'}的提醒记录。",
                medicine_name=p.medicine_name,
            )

        if len(matched) > 1 and not p.reminder_id:
            detail = "，".join(r.medicine_name for r in matched)
            return self._followup(
                "cancel",
                f"{ctx.speaker_name}，我查到{detail}这几条，您说的是哪一个呀？",
                candidates=[{"reminder_id": r.id, "medicine_name": r.medicine_name} for r in matched],
            )

        r = matched[0]

        if p.keep_history:
            self.store.deactivate(r.id, p.reason)
        else:
            self.store.hard_delete(r.id)

        hint = msg.CANCEL_OK_REASON_HINT if p.reason else msg.CANCEL_OK_NO_HINT
        speech = msg.render(
            msg.CANCEL_OK, person=ctx.speaker_name, medicine=r.medicine_name, reason_hint=hint
        )
        return self._ok(
            "cancel",
            speech,
            reminder_id=r.id,
            medicine_name=r.medicine_name,
            reason=p.reason,
            # 告知家属：停药是重要事件
            notify_family=True,
        )

    # ==================================================================
    # 5. confirm_taken —— 老人说自己吃过了
    # ==================================================================
    def confirm_taken(self, p: ConfirmTakenParams, ctx: SkillContext) -> SkillResult:
        person = ctx.person(p.target_person)
        when = p.taken_at or ctx.now
        day = when.date()

        pending = [i for i in self._plan_of_day(day, person, p.medicine_name) if not i["taken"]]

        if not pending:
            # 分两种情况：药名对不上 vs 该吃的都吃了
            known = self.store.query(person=person, medicine_name=p.medicine_name, active=True)
            if p.medicine_name and not known:
                return self._ok(
                    "confirm_taken",
                    msg.render(msg.TAKEN_NOT_FOUND, person=ctx.speaker_name,
                               medicine=p.medicine_name),
                    matched=False,
                )
            return self._ok(
                "confirm_taken",
                msg.render(msg.TAKEN_NOTHING_PENDING, person=ctx.speaker_name),
                matched=False,
            )

        # 老人说「早上吃的」就匹配最接近的时间点，不说就取最近的一个待服
        now_minutes = when.hour * 60 + when.minute
        pending.sort(key=lambda i: abs(_time_to_min(i["slot"]) - now_minutes))

        # 同一时间点可能有好几种药，一起记上，避免漏记
        target_slot = pending[0]["slot"]
        same_slot = [i for i in pending if i["slot"] == target_slot]

        for item in same_slot:
            self.store.log_taken(item["reminder_id"], day, item["slot"],
                                 taken_at=when, source="voice")

        names = "、".join(i["medicine_name"] for i in same_slot)
        speech = msg.render(
            msg.TAKEN_OK,
            person=ctx.speaker_name,
            medicine=names,
            time=msg._times_cn([target_slot]),
        )
        remaining = [i for i in self._plan_of_day(day, person) if not i["taken"]]
        if remaining:
            speech += f"今天还有 {len(remaining)} 次药，到点我再提醒您。"

        return self._ok(
            "confirm_taken",
            speech,
            date=day.isoformat(),
            slot=target_slot,
            medicines=[i["medicine_name"] for i in same_slot],
            remaining=remaining,
        )

    # ==================================================================
    # 调度器接口（不属于 Qwen 的 action，由后台定时任务调用）
    # ==================================================================
    def get_due_reminders(self, now: datetime | None = None,
                          tolerance_min: int = 5) -> list[dict[str, Any]]:
        """取出「现在该提醒」的记录列表。

        给定时调度器用：每分钟跑一次，拿到结果就播报，播完在 speaking 表里标记，
        避免同一时间点反复播。这里只负责算，不负责播和去重。
        """
        now = now or datetime.now()
        now_minutes = now.hour * 60 + now.minute
        due: list[dict[str, Any]] = []

        for r in self.store.all():
            if not r.is_effective_on(now.date()):
                continue
            taken = r.taken_slots(now.date())
            for slot in r.times:
                if slot in taken:
                    continue
                if abs(_time_to_min(slot) - now_minutes) <= tolerance_min:
                    due.append(
                        {
                            "reminder_id": r.id,
                            "person": r.person,
                            "medicine_name": r.medicine_name,
                            "dosage": r.dosage,
                            "dosage_unit": r.dosage_unit,
                            "timing": r.timing,
                            "slot": slot,
                            "speech": msg.describe_remind(
                                r.medicine_name, r.dosage, r.dosage_unit, r.timing
                            ),
                        }
                    )

        # 超时未服用的：提醒过 N 次还没确认，可以升级通知子女
        for r in self.store.all():
            if not r.is_effective_on(now.date()):
                continue
            taken = r.taken_slots(now.date())
            for slot in r.times:
                if slot in taken:
                    continue
                overdue = now_minutes - _time_to_min(slot)
                if overdue > 60:
                    due.append(
                        {
                            "reminder_id": r.id,
                            "person": r.person,
                            "slot": slot,
                            "overdue_minutes": overdue,
                            "escalate": True,
                        }
                    )
        return due


def _time_to_min(slot: str) -> int:
    h, m = slot.split(":")
    return int(h) * 60 + int(m)
