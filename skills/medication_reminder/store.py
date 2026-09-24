"""用药提醒的存储层。

先落地成 JSON 文件，好处是零依赖、能直接 git diff、方便组内联调。
接口都是方法调用，之后要换成 SQLite / MySQL，只要保持这几个方法签名不变，
executor 一行都不用改。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path("data/reminders.json")

# 服药记录的状态。对齐 common/domain.py 的 MedicationStatus，
# 这样健康和照顾反馈那边统计依从率时，口径和这里是一致的。
STATUS_TAKEN = "taken"        # 已服用
STATUS_MISSED = "missed"      # 到点没吃（系统判定，超过阈值）
STATUS_SKIPPED = "skipped"    # 老人主动说跳过


def _status_of(log: dict[str, Any]) -> str:
    """取一条记录的 status。

    老数据里没有 status 字段（那时只记「吃了」），一律当作 taken，
    这样升级后读旧文件不会把历史服药记录当成漏服。
    """
    return log.get("status") or STATUS_TAKEN


@dataclass
class Reminder:
    """一条用药提醒。字段和 CreateReminderParams 一一对应。"""

    id: str
    person: str
    medicine_name: str
    dosage: float
    dosage_unit: str
    frequency: str
    times: list[str]
    timing: str = "any"
    weekdays: list[int] = field(default_factory=list)
    start_date: str = ""                 # YYYY-MM-DD
    end_date: str | None = None          # None 表示长期
    note: str | None = None
    active: bool = True                  # False 表示已停用（保留历史）
    created_at: str = ""                 # ISO 时间戳
    cancelled_at: str | None = None
    cancel_reason: str | None = None
    # 服药记录：每次服药落一条，含「没吃」的情况。
    # ★ 为什么不只记「吃了」：健康和照顾反馈要统计「本周漏服 3 次」，
    #   如果漏服是实时算出来的、不落库，那边就读不到历史，只能自己重算一遍。
    # 单条结构：
    # {"date": "2026-09-19", "slot": "08:00", "status": "taken",
    #  "at": "2026-09-19T08:03:00", "source": "voice", "overdue_minutes": None}
    # 兼容旧数据：没有 status 字段的记录一律当作 taken（见 _status_of）。
    taken_log: list[dict[str, Any]] = field(default_factory=list)

    # ---- 便利方法 ----
    def start(self) -> date:
        return date.fromisoformat(self.start_date) if self.start_date else date.today()

    def end(self) -> date | None:
        return date.fromisoformat(self.end_date) if self.end_date else None

    def is_effective_on(self, day: date) -> bool:
        """这条提醒在某一天是否生效。要考虑起止日期、隔日、每周几。"""
        if not self.active:
            return False
        start = self.start()
        if day < start:
            return False
        end = self.end()
        if end and day > end:
            return False

        if self.frequency == "every_other_day":
            return (day - start).days % 2 == 0
        if self.frequency == "weekly":
            return day.weekday() in (self.weekdays or [])
        return True

    def taken_slots(self, day: date) -> set[str]:
        """某天已经确认服用的时间点集合。

        只有 status=taken 才算「已服用」；漏服/跳过不在这里，
        否则漏服之后就会被当成「吃过了」，再也不提醒。
        """
        d = day.isoformat()
        return {
            log["slot"]
            for log in self.taken_log
            if log.get("date") == d and _status_of(log) == STATUS_TAKEN
        }

    def logged_slots(self, day: date) -> set[str]:
        """某天已经有记录的时间点（不论吃了、漏了还是跳过）。

        调度器用这个来判断「这次是否已经判定过漏服」，避免每分钟重复写。
        """
        d = day.isoformat()
        return {log["slot"] for log in self.taken_log if log.get("date") == d}

    def missed_slots(self, day: date) -> set[str]:
        """某天判定为漏服的时间点。健康和照顾反馈统计漏服次数用。"""
        d = day.isoformat()
        return {
            log["slot"]
            for log in self.taken_log
            if log.get("date") == d and _status_of(log) == STATUS_MISSED
        }


class ReminderStore:
    """提醒的读写。单进程使用，没做并发控制——接数据库时由数据库负责。"""

    def __init__(self, path: Path | str | None = None, event_store=None):
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, Reminder] = {}
        # 共享事件流（可选注入）。写了服药记录后，顺手往这里 upsert 一条 MedicationLog，
        # 让健康和照顾反馈能读到。不注入（None）时行为不变，方便旧测试。
        self.event_store = event_store
        self._load()

    # ---------------- 文件 IO ----------------
    def _load(self) -> None:
        if not self.path.exists():
            self._items = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # 文件坏了不要让整个系统起不来，备份一份继续跑
            self.path.rename(self.path.with_suffix(".corrupt.json"))
            self._items = {}
            return
        self._items = {r["id"]: Reminder(**r) for r in raw}

    def _save(self) -> None:
        payload = [asdict(r) for r in self._items.values()]
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---------------- 增删改查 ----------------
    def new_id(self) -> str:
        return f"med_{uuid.uuid4().hex[:8]}"

    def add(self, reminder: Reminder) -> Reminder:
        if not reminder.id:
            reminder.id = self.new_id()
        if not reminder.created_at:
            reminder.created_at = datetime.now().isoformat(timespec="seconds")
        self._items[reminder.id] = reminder
        self._save()
        return reminder

    def get(self, reminder_id: str) -> Reminder | None:
        return self._items.get(reminder_id)

    def all(self) -> list[Reminder]:
        return list(self._items.values())

    def query(
        self,
        person: str | None = None,
        medicine_name: str | None = None,
        active: bool | None = True,
    ) -> list[Reminder]:
        """按人和药名筛选。药名做包含匹配，因为老人常说「降压药」而不是全名。"""
        result = []
        for r in self._items.values():
            if person and r.person != person:
                continue
            if active is not None and r.active != active:
                continue
            if medicine_name and medicine_name not in r.medicine_name:
                continue
            result.append(r)
        return result

    def update(self, reminder: Reminder) -> Reminder:
        self._items[reminder.id] = reminder
        self._save()
        return reminder

    def deactivate(self, reminder_id: str, reason: str | None = None) -> Reminder | None:
        r = self.get(reminder_id)
        if r is None:
            return None
        r.active = False
        r.cancelled_at = datetime.now().isoformat(timespec="seconds")
        r.cancel_reason = reason
        return self.update(r)

    def hard_delete(self, reminder_id: str) -> bool:
        if reminder_id in self._items:
            del self._items[reminder_id]
            self._save()
            return True
        return False

    # ---------------- 服药记录 ----------------
    def _append_log(self, reminder_id: str, day: date, slot: str, status: str,
                    at: datetime | None = None, source: str = "voice",
                    overdue_minutes: int | None = None) -> bool:
        """往某条提醒里追加一条记录。同一时间点已经记过就不重复写。

        返回 True 表示这次真的写进去了（False = 已有记录，跳过）。
        调用方靠这个返回值判断「是不是刚判定漏服」，避免每分钟重复通知。

        唯一会「改写已有记录」的情况：原来记的是漏服/跳过，
        现在老人补报「我吃了」——以老人的说法为准，把那条改成 taken。
        反过来（已记 taken 又判漏服）不会覆盖：吃过就是吃过。
        """
        r = self.get(reminder_id)
        if r is None:
            return False
        d = day.isoformat()

        for log in r.taken_log:
            if log["date"] != d or log["slot"] != slot:
                continue
            if _status_of(log) == status:
                return False
            if _status_of(log) in (STATUS_MISSED, STATUS_SKIPPED) and status == STATUS_TAKEN:
                log["status"] = status
                log["at"] = (at or datetime.now()).isoformat(timespec="seconds")
                log["source"] = source
                self.update(r)
                self._sync_event_stream(r, day, slot)
                return True
            return False

        r.taken_log.append(
            {
                "date": d,
                "slot": slot,
                "status": status,
                "at": (at or datetime.now()).isoformat(timespec="seconds"),
                "source": source,
                "overdue_minutes": overdue_minutes,
            }
        )
        self.update(r)
        self._sync_event_stream(r, day, slot)
        return True

    def _sync_event_stream(self, r: "Reminder", day: date, slot: str) -> None:
        """把最新的这条服药记录同步进共享事件流。

        用稳定 id = f"{reminder_id}:{date}:{slot}"，这样漏服->补报已服时
        是 upsert 覆盖同一条，健康反馈不会把「漏服」「已服」算成两条。
        """
        if self.event_store is None:
            return
        # 找到这条时间点最新的记录（可能是刚 append 的，也可能是「补报已服」改写后的）
        d = day.isoformat()
        latest = None
        for log in r.taken_log:
            if log.get("date") == d and log.get("slot") == slot:
                latest = log
        if latest is None:
            return

        from common.domain import MedicationLog, MedicationStatus

        status_map = {
            STATUS_TAKEN: MedicationStatus.TAKEN,
            STATUS_MISSED: MedicationStatus.MISSED,
            STATUS_SKIPPED: MedicationStatus.SKIPPED,
        }
        at = latest.get("at")
        taken_at = datetime.fromisoformat(at) if at else None
        scheduled = datetime.combine(day, datetime.min.time())
        # slot 是 "HH:MM"，把时分填进 scheduled_at，让健康反馈能按时间排序
        hh, mm = slot.split(":")
        scheduled = scheduled.replace(hour=int(hh), minute=int(mm))

        log = MedicationLog(
            id=f"{r.id}:{day.isoformat()}:{slot}",
            person_id=r.person,
            reminder_id=r.id,
            medicine_name=r.medicine_name,
            dosage=r.dosage,
            dosage_unit=r.dosage_unit,
            scheduled_at=scheduled,
            taken_at=taken_at,
            status=status_map[latest.get("status", STATUS_TAKEN)],
            source=latest.get("source", "voice"),
        )
        self.event_store.upsert(log)

    def log_taken(self, reminder_id: str, day: date, slot: str,
                  taken_at: datetime | None = None, source: str = "voice") -> bool:
        """记一笔服药。同一天同一时间点只记一次，重复上报不报错。

        如果这个时间点之前被判过漏服，这里会把那条记录改成「已服用」——
        老人事后补一句「我吃了」，应该以他说的为准。
        """
        return self._append_log(reminder_id, day, slot, STATUS_TAKEN,
                                at=taken_at, source=source)

    def log_missed(self, reminder_id: str, day: date, slot: str,
                   overdue_minutes: int | None = None,
                   at: datetime | None = None) -> bool:
        """记一笔漏服。

        ★ 谁调用：后台调度器在「超过阈值还没确认」时调用。
        为什么必须落库：漏服如果只是实时算出来的，健康和照顾反馈统计
        「本周漏服 3 次」时就无据可查，也没法区分「老人当时是不是故意不吃」。

        返回 True 表示这是【刚判定】的漏服，调用方可以据此发通知；
        False 表示之前已经记过（或老人已经吃过），不要重复通知。
        """
        return self._append_log(reminder_id, day, slot, STATUS_MISSED,
                                at=at, source="system",
                                overdue_minutes=overdue_minutes)

    def log_skipped(self, reminder_id: str, day: date, slot: str) -> bool:
        """记一笔「老人主动说这次不吃」。和漏服分开统计，性质不一样。"""
        return self._append_log(reminder_id, day, slot, STATUS_SKIPPED,
                                source="voice")
