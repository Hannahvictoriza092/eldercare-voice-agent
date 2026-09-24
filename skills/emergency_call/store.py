"""呼救事件的单进程 JSON 存储；可注入路径供联调和测试。"""

from __future__ import annotations

import json
from pathlib import Path

from common.domain import Incident, IncidentStatus

DEFAULT_PATH = Path("data/emergency_incidents.json")
ACTIVE = {IncidentStatus.OPEN, IncidentStatus.ACKED, IncidentStatus.EN_ROUTE,
          IncidentStatus.ARRIVED, IncidentStatus.FAILED}


class EmergencyStore:
    def __init__(self, path: Path | str | None = None, event_store=None):
        self.path = Path(path) if path is not None else DEFAULT_PATH
        # 共享事件流（可选注入）。save 时顺手 upsert，让健康反馈读到异常事件。
        self.event_store = event_store
        self._items: dict[str, Incident] = {}
        if self.path.exists():
            for raw in json.loads(self.path.read_text(encoding="utf-8")):
                incident = Incident.model_validate(raw)
                self._items[incident.id] = incident

    def save(self, incident: Incident) -> None:
        items = dict(self._items)
        items[incident.id] = incident
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(
            [item.model_dump(mode="json") for item in items.values()],
            ensure_ascii=False, indent=2,
        ), encoding="utf-8")
        temp.replace(self.path)
        self._items = items
        # 同步进共享事件流（幂等：同一 incident.id 状态推进会覆盖）
        if self.event_store is not None:
            self.event_store.upsert(incident)

    def get(self, incident_id: str) -> Incident | None:
        return self._items.get(incident_id)

    def latest(self, person_id: str, active_only: bool = False) -> Incident | None:
        matching = [item for item in self._items.values()
                    if item.person_id == person_id and (not active_only or item.status in ACTIVE)]
        return max(matching, key=lambda item: item.occurred_at) if matching else None

    def incidents(self, person_id: str, start, end) -> list[Incident]:
        """兼容健康反馈 EventStore 的事件读取签名。"""
        return [item for item in self._items.values()
                if item.person_id == person_id and start <= item.occurred_at.date() <= end]
