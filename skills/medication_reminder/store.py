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
    taken_log: list[dict[str, Any]] = field(default_factory=list)
    # taken_log 的单条结构：
    # {"date": "2026-09-19", "slot": "08:00", "taken_at": "2026-09-19T08:03:00", "source": "voice"}

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
        """某天已经确认服用的时间点集合。"""
        d = day.isoformat()
        return {log["slot"] for log in self.taken_log if log.get("date") == d}


class ReminderStore:
    """提醒的读写。单进程使用，没做并发控制——接数据库时由数据库负责。"""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, Reminder] = {}
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

    def log_taken(self, reminder_id: str, day: date, slot: str,
                  taken_at: datetime | None = None, source: str = "voice") -> bool:
        """记一笔服药。同一天同一时间点只记一次，重复上报不报错。"""
        r = self.get(reminder_id)
        if r is None:
            return False
        d = day.isoformat()
        if any(log["date"] == d and log["slot"] == slot for log in r.taken_log):
            return True
        r.taken_log.append(
            {
                "date": d,
                "slot": slot,
                "taken_at": (taken_at or datetime.now()).isoformat(timespec="seconds"),
                "source": source,
            }
        )
        self.update(r)
        return True
