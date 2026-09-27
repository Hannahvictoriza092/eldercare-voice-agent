from datetime import datetime, timezone
from pathlib import Path
import json

from common import EventStore, SkillContext
from common.domain import Incident, IncidentType, MedicationLog, MedicationStatus
from skills.health_report import HealthArchiveStore, HealthReportExecutor, HealthReportSkill
from weekly_scheduler import WeeklyScheduler
import weekly_scheduler


def add_log(path, day=21, person="elder_01"):
    log = MedicationLog(
        id=f"{person}-{day}", person_id=person, medicine_name="测试药",
        dosage=1, dosage_unit="tablet", scheduled_at=datetime(2026, 9, day, 8),
        status=MedicationStatus.MISSED,
    )
    EventStore(path / "events.jsonl").upsert(log)
    return log


def test_due_time_auto_archive_and_live_reader(tmp_path):
    add_log(tmp_path)
    reader = HealthReportSkill(HealthReportExecutor(
        EventStore(tmp_path / "events.jsonl"),
        HealthArchiveStore(tmp_path / "health_archives.json")))
    scheduler = WeeklyScheduler(tmp_path)
    assert scheduler.run_pending(datetime(2026, 9, 28, 7, 59)) == []
    assert not (tmp_path / "health_archives.json").exists()
    runs = scheduler.run_pending(datetime(2026, 9, 28, tzinfo=timezone.utc))
    assert len(runs) == 1 and runs[0]["status"] == "done"
    result = reader.run("query_archive", {"person_id": "elder_01"}, SkillContext())
    assert result.ok and len(result.data["snapshots"]) == 1
    report = json.loads(Path(runs[0]["report_file"]).read_text(encoding="utf-8"))
    assert report["stats"]["missed"] == 1
    assert WeeklyScheduler(tmp_path).run_pending(datetime(2026, 9, 28, 9)) == []


def test_catchup_people_incident_only_and_current_week_excluded(tmp_path):
    add_log(tmp_path, 14)
    add_log(tmp_path, 21)
    add_log(tmp_path, 28)
    EventStore(tmp_path / "events.jsonl").upsert(Incident(
        id="sos", person_id="elder_02", type=IncidentType.SOS,
        occurred_at=datetime(2026, 9, 21)))
    runs = WeeklyScheduler(tmp_path).run_pending(datetime(2026, 9, 29))
    assert len(runs) == 3
    archives = HealthArchiveStore(tmp_path / "health_archives.json")
    assert len(archives.get("elder_01").snapshots) == 2
    assert archives.get("elder_02").latest().incidents == 1
    assert WeeklyScheduler(tmp_path).run_pending(datetime(2026, 9, 29)) == []


def test_late_update_regenerates_without_duplicate_snapshots(tmp_path):
    log = add_log(tmp_path, 14)
    add_log(tmp_path, 21)
    scheduler = WeeklyScheduler(tmp_path)
    scheduler.run_pending(datetime(2026, 9, 28, 9))
    log.status = MedicationStatus.TAKEN
    log.taken_at = datetime(2026, 9, 14, 12)
    scheduler.events.upsert(log)
    runs = scheduler.run_pending(datetime(2026, 9, 28, 10))
    assert len(runs) == 2
    archives = HealthArchiveStore(tmp_path / "health_archives.json")
    assert len(archives.get("elder_01").snapshots) == 2
    assert archives.get("elder_01").snapshots[0].taken == 1


def test_failure_is_persisted_and_retried_without_blocking_other_person(tmp_path, monkeypatch):
    add_log(tmp_path, person="elder_01")
    add_log(tmp_path, person="elder_02")
    real_write = weekly_scheduler.write_json

    def fail_report(path, data):
        if path.parent.name == "weekly_reports" and data["person_id"] == "elder_01":
            raise OSError("模拟报告写入失败")
        real_write(path, data)

    monkeypatch.setattr(weekly_scheduler, "write_json", fail_report)
    runs = WeeklyScheduler(tmp_path).run_pending(datetime(2026, 9, 28, 9))
    assert [run["status"] for run in runs] == ["failed", "done"]
    monkeypatch.setattr(weekly_scheduler, "write_json", real_write)
    retried = WeeklyScheduler(tmp_path).run_pending(datetime(2026, 9, 28, 10))
    assert len(retried) == 1 and retried[0]["status"] == "done"
    assert len(HealthArchiveStore(tmp_path / "health_archives.json").get("elder_01").snapshots) == 1


def test_empty_store_does_not_create_empty_archive(tmp_path):
    assert WeeklyScheduler(tmp_path).run_pending(datetime(2026, 9, 28, 9)) == []
    assert not (tmp_path / "health_archives.json").exists()
