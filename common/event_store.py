"""共享事件流：MedicationLog 和 Incident 的统一落地存储与读取。

======================================================================
★ 这个文件是三个人一起用的，改动前在群里说一声。
======================================================================

【为什么要有这一层】
三个 skill 有依赖：用药提醒产出 MedicationLog，呼救产出 Incident，
健康和照顾反馈要消费两者的数据生成周报。如果健康和照顾反馈去 import
另外两个 skill 的私有 store，那边一改存储结构这边就崩——这是耦合。

所以这里提供一个【文件级】的共享事件流：
  写：用药提醒 upsert MedicationLog；呼救 upsert Incident
  读：健康和照顾反馈用 medication_logs()/incidents() 读（和队友写的
      InMemoryEventStore 接口签名一致，换过来一行不用改）

【幂等与覆盖（重要）】
MedicationLog 和 Incident 的状态都会变化：
  - 服药记录：漏服(missed) -> 老人补报已服(taken)，同一「时间点」应是同一条
  - 呼救事件：OPEN -> ACKED -> ... -> RESOLVED，状态推进不是新事件
如果纯 append，健康反馈会把「漏服」「已服」当两条、把呼救的每个状态当一起，
统计就虚增了。

所以约定：**同一个 id 只保留最后一条**（后者覆盖前者）。
写方用稳定 id：
  - 服药记录 id = f"{reminder_id}:{date}:{slot}"（一个时间点一条）
  - 呼救事件 id = incident.id（本来就唯一）

磁盘用 JSONL 追加写（天然适合事件流、不怕进程崩），加载时按 id 去重，
最后一个覆盖前面所有同一 id 的记录。

【存储格式】
JSON 文件，每个事件一行（JSONL）。之后要换 SQLite / MySQL，
只要保持 upsert()/medication_logs()/incidents() 签名不变。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .domain import Incident, MedicationLog

DEFAULT_PATH = Path("data/events.jsonl")


class EventStore:
    """共享事件流的读写。单进程、JSONL 追加写，按 id 幂等覆盖。"""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 内存里就是「id -> 最新事件」的映射；磁盘是追加的 JSONL 历史。
        self._items: dict[str, MedicationLog | Incident] = {}
        self._load()

    # ---------------- 文件 IO ----------------
    def _load(self) -> None:
        if not self.path.exists():
            self._items = {}
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
            event = _deserialize(raw)
            # 同一 id 后者覆盖前者（加载顺序即写入顺序）
            self._items[event.id] = event

    def _append_line(self, event: MedicationLog | Incident) -> None:
        payload = event.model_dump(mode="json")
        payload["_type"] = type(event).__name__
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    # ---------------- 写 ----------------
    def upsert(self, event: MedicationLog | Incident) -> None:
        """写入或覆盖一条事件。同一 id 只保留最后一条，保证幂等。

        服药记录和呼救事件都调用它：
          - MedicationLog：状态 missed->taken 就是同一个 id 覆盖
          - Incident：状态推进会覆盖原记录，健康反馈只数到最终态
        """
        self._items[event.id] = event
        self._append_line(event)

    def add(self, event: MedicationLog | Incident) -> None:
        """别名，兼容早期调用。语义同 upsert。"""
        self.upsert(event)

    # ---------------- 读 ----------------
    def all(self) -> list[MedicationLog | Incident]:
        return list(self._items.values())

    def medication_logs(
        self, person_id: str, start: date, end: date
    ) -> list[MedicationLog]:
        """取某位老人 [start, end] 区间内的服药记录（含漏服/跳过）。"""
        return [
            e for e in self._items.values()
            if isinstance(e, MedicationLog)
            and e.person_id == person_id
            and start <= e.scheduled_at.date() <= end
        ]

    def incidents(
        self, person_id: str, start: date, end: date
    ) -> list[Incident]:
        """取某位老人 [start, end] 区间内的异常事件。"""
        return [
            e for e in self._items.values()
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