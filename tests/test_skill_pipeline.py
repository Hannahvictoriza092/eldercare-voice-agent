"""验收：真实上游操作 -> 独立事件库实例实时读取 -> 周报与重载档案。

所有业务数据落在 tmp_path，不读写开发者的 data/。
"""
from datetime import date, datetime
import json

import pytest

from common import EventStore, SkillContext
from common.domain import IncidentStatus, MedicationLog, MedicationStatus
from skills.medication_reminder import MedicationReminderSkill
from skills.emergency_call import EmergencyCallSkill
from skills.health_report import HealthReportSkill, HealthArchiveStore
from skills.health_report.store import WeeklySnapshot


def context(day=21, hour=8, person="elder_01"):
    return SkillContext(speaker_id=person, speaker_name="测试老人",
                        now=datetime(2026, 9, day, hour))


def successful(skill, action, params, ctx):
    result = skill.run(action, params, ctx)
    assert result.ok, result.error or result.speech
    return result


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # 默认构造路径：各执行器有独立缓存，必须在上游写入前先创建报告模块。
    health = HealthReportSkill()
    med = MedicationReminderSkill()
    emergency = EmergencyCallSkill()
    return med, emergency, health


def create_medication(med, ctx):
    return successful(med, "create", {
        "medicine_name": "测试药", "dosage": 1, "dosage_unit": "tablet",
        "frequency": "once_daily", "times": ["08:00"],
        "start_date": ctx.now.date().isoformat(),
    }, ctx)


def weekly(health, ctx, week="2026-09-21"):
    return successful(health, "generate_weekly", {
        "person_id": ctx.speaker_id, "week_start": week,
    }, ctx)


def test_full_pipeline_updates_reload_and_weekly_trend(pipeline):
    med, emergency, health = pipeline
    create_medication(med, context())
    successful(med, "confirm_taken", {}, context())
    due = med.due_reminders(context(day=22, hour=10).now)
    assert any(row.get("newly_missed") for row in due)
    # 重复轮询不增加记录，也不重复生成新的漏服通知。
    assert not any(row.get("newly_missed") for row in
                   med.due_reminders(context(day=22, hour=10).now))
    event = successful(emergency, "trigger", {"reason": "需要帮助"}, context(day=22))
    incident_id = event.data["incident"]["id"]
    emergency.executor.update_status(incident_id, IncidentStatus.ACKED, context(day=22))
    emergency.executor.update_status(incident_id, IncidentStatus.EN_ROUTE, context(day=22))

    before = weekly(health, context(day=22, hour=10))
    stats = before.data["stats"]
    assert (stats["record_count"], stats["taken"], stats["missed"], stats["incidents"]) == (2, 1, 1, 1)
    assert stats["taken_ratio"] == 50.0
    reader = health.executor.store
    logs = reader.medication_logs("elder_01", date(2026, 9, 21), date(2026, 9, 27))
    missed = next(log for log in logs if log.status == MedicationStatus.MISSED)
    assert missed.taken_at is None
    incidents = reader.incidents("elder_01", date(2026, 9, 21), date(2026, 9, 27))
    assert len(incidents) == 1 and incidents[0].status == IncidentStatus.EN_ROUTE
    assert len(incidents[0].status_history) == 3

    # 同一实例立即看见漏服 -> 补服，不把一次服药计算成两条。
    successful(med, "confirm_taken", {}, context(day=22, hour=12))
    after = weekly(health, context(day=22, hour=12))
    assert after.data["stats"]["record_count"] == 2
    assert after.data["stats"]["taken"] == 2
    assert after.data["stats"]["missed"] == 0
    assert "按时完成" not in after.data["report_body"]
    updated = reader.medication_logs("elder_01", date(2026, 9, 21), date(2026, 9, 27))
    assert next(log for log in updated if log.id == missed.id).taken_at.hour == 12
    summary = successful(health, "query_summary", {"person_id": "elder_01"}, context(day=22, hour=12))
    assert (summary.data["taken"], summary.data["missed"], summary.data["incidents"]) == (2, 0, 1)

    # 重建所有模块模拟重启，数据与同周快照均不丢失。
    med, emergency, health = MedicationReminderSkill(), EmergencyCallSkill(), HealthReportSkill()
    assert weekly(health, context(day=22, hour=12)).data["stats"] == after.data["stats"]
    archive = successful(health, "query_archive", {"person_id": "elder_01"}, context(day=22))
    assert len(archive.data["snapshots"]) == 1
    assert archive.data["snapshots"][0]["record_count"] == 2
    assert archive.data["snapshots"][0]["taken"] == 2
    # 下一周真实上游继续写，报告从重载档案取上一周数据作比较。
    med.due_reminders(context(day=28, hour=10).now)
    next_week = weekly(health, context(day=28, hour=10), "2026-09-28")
    assert "下降 100.0 个百分点" in next_week.data["report_body"]
    assert len(health.executor.archive_store.get("elder_01").snapshots) == 2
    again = HealthReportSkill()
    assert successful(again, "query_archive", {"person_id": "elder_01"}, context(day=28)).data["snapshots"] == successful(health, "query_archive", {"person_id": "elder_01"}, context(day=28)).data["snapshots"]


def test_incident_only_generates_sends_and_reloads(pipeline):
    _, emergency, health = pipeline
    successful(emergency, "trigger", {}, context())
    result = weekly(health, context())
    assert "insufficient" not in result.data
    assert result.data["stats"]["taken_ratio"] is None
    assert "暂无服药记录" in result.data["report_body"]
    assert "本周共 1 起" in result.data["report_body"]
    assert "1 起异常情况" in result.speech
    summary = successful(health, "query_summary", {"person_id": "elder_01"}, context())
    assert "1 起异常情况" in summary.speech
    sent = successful(health, "send_report", {"person_id": "elder_01", "targets": ["family"]}, context())
    assert len(sent.notifications) == 1 and sent.data["notification_pending"]
    assert "待发送" in sent.speech and not sent.notifications[0].delivered
    restarted = HealthReportSkill()
    archive = successful(restarted, "query_archive", {"person_id": "elder_01"}, context())
    assert len(archive.data["snapshots"]) == 1
    assert "None" not in archive.speech
    assert "1 起异常情况" in archive.speech
    successful(emergency, "trigger", {}, context(day=28))
    following = weekly(restarted, context(day=28), "2026-09-28")
    assert "异常事件与上周持平" in following.data["report_body"]
    assert "暂不比较服药情况" in following.data["report_body"]


def test_no_records_does_not_claim_health_or_create_archive(pipeline):
    _, _, health = pipeline
    assert weekly(health, context()).data["insufficient"]
    sent = successful(health, "send_report", {"person_id": "elder_01", "targets": ["family"]}, context())
    assert sent.data["insufficient"] and not sent.notifications
    assert health.executor.archive_store.get("elder_01") is None
    summary = successful(health, "query_summary", {"person_id": "elder_01"}, context())
    assert "无法判断" in summary.speech
    assert "放心" not in summary.speech


def test_person_and_week_isolation_with_medication_only(pipeline):
    med, emergency, health = pipeline
    create_medication(med, context())
    successful(med, "confirm_taken", {}, context())
    successful(emergency, "trigger", {}, context(person="elder_02"))
    successful(emergency, "trigger", {}, context(day=14))
    first = weekly(health, context()).data["stats"]
    second = weekly(health, context(person="elder_02")).data["stats"]
    assert (first["record_count"], first["incidents"]) == (1, 0)
    assert (second["record_count"], second["incidents"]) == (0, 1)
    restarted = HealthReportSkill()
    assert restarted.executor.archive_store.get("elder_01").snapshots[0].taken == 1
    assert restarted.executor.archive_store.get("elder_02").snapshots[0].taken == 0


def test_skipped_pending_counts_and_archive_reload(pipeline):
    med, _, health = pipeline
    create_medication(med, context())
    reminder = med.executor.store.all()[0]
    med.executor.store.log_skipped(reminder.id, date(2026, 9, 21), "08:00")
    EventStore().upsert(MedicationLog(
        id="pending-test", person_id="elder_01", medicine_name="测试药",
        dosage=1, dosage_unit="tablet", scheduled_at=datetime(2026, 9, 22, 8),
        status=MedicationStatus.PENDING,
    ))
    result = weekly(health, context(day=22))
    stats = result.data["stats"]
    assert (stats["record_count"], stats["skipped"], stats["pending"], stats["taken"]) == (2, 1, 1, 0)
    assert "主动跳过 1 次" in result.data["report_body"]
    snapshot = HealthReportSkill().executor.archive_store.get("elder_01").snapshots[0]
    assert (snapshot.skipped, snapshot.pending) == (1, 1)


def test_legacy_archive_restores_typed_snapshots_and_replaces_same_week(tmp_path):
    path = tmp_path / "archive.json"
    path.write_text(json.dumps([{
        "person_id": "elder_01", "snapshots": [{
            "week_start": "2026-09-21", "adherence": 50.0, "planned": 2,
            "taken": 1, "missed": 1,
        }],
    }]), encoding="utf-8")
    store = HealthArchiveStore(path)
    snapshot = store.get("elder_01").snapshot_for("2026-09-21")
    assert isinstance(snapshot, WeeklySnapshot)
    assert snapshot.skipped == snapshot.pending == 0
    store.save_snapshot("elder_01", WeeklySnapshot("2026-09-21", 100.0, planned=2, taken=2))
    restored = HealthArchiveStore(path).get("elder_01")
    assert len(restored.snapshots) == 1 and restored.latest().taken == 2
