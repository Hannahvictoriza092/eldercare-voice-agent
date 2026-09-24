"""共享事件流：MedicationLog 和 Incident 的统一落地存储与读取。

======================================================================
★ 这个文件是三个人一起用的，改动前在群里说一声。
======================================================================

【为什么要有这一层】
三个 skill 有依赖：用药提醒产出 MedicationLog，呼救产出 Incident，
健康和照顾反馈要消费两者的数据生成周报。如果健康和照顾反馈去 import
另外两个 skill 的私有 store，那边一改存储结构这边就崩——这是耦合。

所以这里提供一个【文件级】的共享事件流，三个 skill 通过它读写：
  写：用药提醒往这里 append MedicationLog；呼救往这里 append Incident
  读：健康和照顾反馈用 EventStore 接口的 medication_logs()/incidents() 读

【和队友写的 InMemoryEventStore 的关系】
健康反馈的 executor.py 里定义了一个 EventStore 抽象 + InMemoryEventStore 假实现，
那个【接口签名】和这里保持一致（medication_logs / incidents），所以健康反馈
以后只要把 InMemoryEventStore 换成这里的 JsonEventStore，业务逻辑一行不用改。

【存储格式】
JSON 文件，每个事件一行（JSONL），追加写，天然适合事件流。
之后要换 SQLite / MySQL，只要保持 add()/medication_logs()/incidents() 签名不变。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .domain import Incident, MedicationLog

DEFAULT_PATH = Path("data/events.jsonl")


class EventStore:
    """共享事件流的读写。单进程、追加写，无并发控制——接数据库时由数据库负责。"""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: list[MedicationLog | Incident] = []
        self._load()

    # ---------------- 文件 IO ----------------
    def _load(self) -> None:
        if not self.path.exists():
            self._items = []
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                # 某一行坏了不要拖垮整个事件流，跳过继续读
                continue
            self._items.append(_deserialize(raw))

    def _append_line(self, event: MedicationLog | Incident) -> None:
        payload = event.model_dump(mode="json")
        payload["_type"] = type(event).__name__
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    # ---------------- 写 ----------------
    def add(self, event: MedicationLog | Incident) -> None:
        """追加一条事件（服药记录或异常事件）。"""
        self._items.append(event)
        self._append_line(event)

    # ---------------- 读 ----------------
    def all(self) -> list[MedicationLog | Incident]:
        return list(self._items)

    def medication_logs(
        self, person_id: str, start: date, end: date
    ) -> list[MedicationLog]:
        """取某位老人 [start, end] 区间内的服药记录（含漏服/跳过）。"""
        return [
            e for e in self._items
            if isinstance(e, MedicationLog)
            and e.person_id == person_id
            and start <= e.scheduled_at.date() <= end
        ]

    def incidents(
        self, person_id: str, start: date, end: date
    ) -> list[Incident]:
        """取某位老人 [start, end] 区间内的异常事件。"""
        return [
            e for e in self._items
            if isinstance(e, Incident)
            and e.person_id == person_id
            and start <= e.occurred_at.date() <= end
        ]


def _deserialize(raw: dict[str, Any]) -> MedicationLog | Incident:
    """按 _type 标记还原成正确的实体。"""
    kind = raw.pop("_type", None)
    if kind == "Incident":
        return Incident.model_validate(raw)
    # 默认当作 MedicationLog（兼容没有 _type 的旧数据）
    return MedicationLog.model_validate(raw)