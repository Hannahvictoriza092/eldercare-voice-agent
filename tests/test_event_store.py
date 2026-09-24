"""共享事件流 EventStore 的测试。

事件流是共享层，三个 skill 都依赖它：
  用药提醒/呼救写，健康反馈读。这层要稳。
"""

from __future__ import annotations

from datetime import date, datetime

from common import EventStore
from common.domain import (
    Incident,
    IncidentStatus,
    IncidentType,
    MedicationLog,
    MedicationStatus,
)


def make_log(day: date, person="elder_01", status=MedicationStatus.TAKEN) -> MedicationLog:
    return MedicationLog(
        id=f"log_{day.isoformat()}_{status.value}",
        person_id=person,
        medicine_name="阿司匹林",
        dosage=1,
        dosage_unit="tablet",
        scheduled_at=datetime.combine(day, datetime.min.time()),
        taken_at=datetime.combine(day, datetime.min.time()) if status == MedicationStatus.TAKEN else None,
        status=status,
    )


def make_incident(day: date, person="elder_01") -> Incident:
    return Incident(
        id=f"inc_{day.isoformat()}",
        person_id=person,
        type=IncidentType.SOS,
        occurred_at=datetime.combine(day, datetime.min.time()),
        status=IncidentStatus.RESOLVED,
    )


class TestEventStore:
    def test_写入后能读回且类型正确(self, tmp_path):
        store = EventStore(tmp_path / "events.jsonl")
        store.add(make_log(date(2026, 9, 20)))
        store.add(make_incident(date(2026, 9, 21)))

        # 重新从磁盘加载，验证反序列化按 _type 还原正确类型
        reloaded = EventStore(tmp_path / "events.jsonl")
        types = sorted(type(e).__name__ for e in reloaded.all())
        assert types == ["Incident", "MedicationLog"]

    def test_按人员和日期区间过滤(self, tmp_path):
        store = EventStore(tmp_path / "events.jsonl")
        store.add(make_log(date(2026, 9, 20), person="elder_01"))
        store.add(make_log(date(2026, 9, 25), person="elder_02"))
        store.add(make_incident(date(2026, 9, 20), person="elder_01"))

        logs = store.medication_logs("elder_01", date(2026, 9, 19), date(2026, 9, 21))
        assert len(logs) == 1 and logs[0].person_id == "elder_01"

        incidents = store.incidents("elder_01", date(2026, 9, 19), date(2026, 9, 21))
        assert len(incidents) == 1

    def test_漏服状态能读出来(self, tmp_path):
        """健康反馈靠 status=MISSED 统计漏服，事件流必须保留状态。"""
        store = EventStore(tmp_path / "events.jsonl")
        store.add(make_log(date(2026, 9, 20), status=MedicationStatus.MISSED))

        logs = store.medication_logs("elder_01", date(2026, 9, 20), date(2026, 9, 20))
        assert logs[0].status == MedicationStatus.MISSED

    def test_坏行不拖垮整个事件流(self, tmp_path):
        """某一行 JSON 坏了，其余事件仍要能读出来。"""
        path = tmp_path / "events.jsonl"
        path.write_text("这不是合法 JSON\n", encoding="utf-8")
        store = EventStore(path)
        store.add(make_log(date(2026, 9, 20)))
        reloaded = EventStore(path)
        assert len(reloaded.all()) == 1

    def test_同一id幂等覆盖(self, tmp_path):
        """漏服->补报已服应是同一条记录覆盖，不产生重复。"""
        store = EventStore(tmp_path / "events.jsonl")

        missed = make_log(date(2026, 9, 20), status=MedicationStatus.MISSED)
        missed.id = "log_fixed"
        store.add(missed)

        taken = make_log(date(2026, 9, 20), status=MedicationStatus.TAKEN)
        taken.id = "log_fixed"
        store.add(taken)

        logs = store.medication_logs("elder_01", date(2026, 9, 20), date(2026, 9, 20))
        assert len(logs) == 1
        assert logs[0].status == MedicationStatus.TAKEN

    def test_幂等覆盖跨进程生效(self, tmp_path):
        """关闭重开后，同一 id 仍只保留最后一条（磁盘 JSONL 加载时去重）。"""
        path = tmp_path / "events.jsonl"
        store = EventStore(path)
        for status in (MedicationStatus.MISSED, MedicationStatus.TAKEN):
            log = make_log(date(2026, 9, 20), status=status)
            log.id = "log_fixed"
            store.add(log)

        reloaded = EventStore(path)
        logs = reloaded.medication_logs("elder_01", date(2026, 9, 20), date(2026, 9, 20))
        assert len(logs) == 1
        assert logs[0].status == MedicationStatus.TAKEN