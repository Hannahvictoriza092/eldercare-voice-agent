"""健康和照顾反馈 skill 的测试。

分三层，对应联调时会踩的三种坑：
  1. schema 测试 —— Qwen 填的参数对不对（含故意填错的负面用例）
  2. executor 测试 —— 周报统计算得对不对
  3. tool 导出测试 —— 导出的 schema Qwen 能不能用
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

import skills
from skills import SkillContext, get
from skills.health_report import (
    HealthReportExecutor,
    HealthReportSkill,
    InMemoryEventStore,
)
from skills.health_report.schema import (
    GenerateWeeklyParams,
    QueryArchiveParams,
    QuerySummaryParams,
    SendReportParams,
)

from common.domain import (
    Incident,
    IncidentStatus,
    IncidentType,
    MedicationLog,
    MedicationStatus,
    NotifyTarget,
)

# 固定时间，避免测试在半夜跑出不一样的结果
NOW = datetime(2026, 9, 21, 9, 0, 0)  # 2026-09-21 是周一
CTX = SkillContext(speaker_id="elder_01", speaker_name="张奶奶", now=NOW)


def datetime_ctx(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> SkillContext:
    """造一个指定「现在」的上下文。"""
    return SkillContext(speaker_id="elder_01", speaker_name="张奶奶",
                        now=datetime(y, m, d, hh, mm))


def make_log(day: date, medicine: str = "阿司匹林",
             status: MedicationStatus = MedicationStatus.TAKEN,
             slot: str = "08:00") -> MedicationLog:
    """造一条服药记录。"""
    return MedicationLog(
        id=f"log_{day.isoformat()}_{slot}",
        person_id="elder_01",
        medicine_name=medicine,
        dosage=1,
        dosage_unit="tablet",
        scheduled_at=datetime.combine(day, datetime.min.time()),
        taken_at=datetime.combine(day, datetime.min.time()) if status == MedicationStatus.TAKEN else None,
        status=status,
    )


def make_incident(day: date, type_: IncidentType = IncidentType.SOS) -> Incident:
    """造一条异常事件。"""
    return Incident(
        id=f"inc_{day.isoformat()}",
        person_id="elder_01",
        type=type_,
        occurred_at=datetime.combine(day, datetime.min.time()),
        status=IncidentStatus.RESOLVED,
    )


@pytest.fixture()
def skill(tmp_path) -> HealthReportSkill:
    """带空事件流 + 临时档案库的 skill。"""
    from skills.health_report import HealthArchiveStore

    store = InMemoryEventStore()
    archive = HealthArchiveStore(tmp_path / "archives.json")
    return HealthReportSkill(HealthReportExecutor(store, archive))


@pytest.fixture()
def skill_with_data(tmp_path) -> HealthReportSkill:
    """带本周数据的 skill：本周一(9-21) 计划 3 次，2 次按时、1 次漏服，1 起异常。"""
    from skills.health_report import HealthArchiveStore

    monday = date(2026, 9, 21)
    logs = [
        make_log(monday, "阿司匹林", MedicationStatus.TAKEN),
        make_log(monday, "二甲双胍", MedicationStatus.TAKEN),
        make_log(monday, "硝苯地平", MedicationStatus.MISSED),
    ]
    incidents = [make_incident(monday)]
    store = InMemoryEventStore(medication_logs=logs, incidents=incidents)
    archive = HealthArchiveStore(tmp_path / "archives.json")
    return HealthReportSkill(HealthReportExecutor(store, archive))


# ======================================================================
# 1. schema 层
# ======================================================================
class TestGenerateWeeklySchema:
    def test_正常参数通过(self):
        p = GenerateWeeklyParams(person_id="elder_01")
        assert p.person_id == "elder_01"
        assert p.week_start is None

    def test_缺person_id要报错(self):
        with pytest.raises(Exception):
            GenerateWeeklyParams()


class TestSendReportSchema:
    def test_正常参数通过(self):
        p = SendReportParams(person_id="elder_01", targets=[NotifyTarget.HOSPITAL])
        assert p.targets == [NotifyTarget.HOSPITAL]

    def test_缺接收方要报错(self):
        with pytest.raises(Exception):
            SendReportParams(person_id="elder_01")

    def test_不能发给紧急通道(self):
        with pytest.raises(Exception) as e:
            SendReportParams(person_id="elder_01", targets=[NotifyTarget.EMERGENCY])
        assert "EMERGENCY" in str(e.value)


class TestQueryArchiveSchema:
    def test_正常参数通过(self):
        p = QueryArchiveParams(person_id="elder_01")
        assert p.person_id == "elder_01"

    def test_结束日期不能早于开始(self):
        with pytest.raises(Exception) as e:
            QueryArchiveParams(
                person_id="elder_01",
                start_date="2026-09-20",
                end_date="2026-09-10",
            )
        assert "end_date" in str(e.value)


class TestQuerySummarySchema:
    def test_正常参数通过(self):
        p = QuerySummaryParams(person_id="elder_01")
        assert p.days is None

    def test_days越界要报错(self):
        with pytest.raises(Exception):
            QuerySummaryParams(person_id="elder_01", days=0)
        with pytest.raises(Exception):
            QuerySummaryParams(person_id="elder_01", days=91)


# ======================================================================
# 2. executor 层
# ======================================================================
class TestGenerateWeekly:
    def test_数据不足时给提示不抛错(self, skill):
        """新老人没有记录，不能崩，要给「数据不足」提示。"""
        r = skill.run("generate_weekly", {"person_id": "elder_01"}, CTX)
        assert r.ok
        assert r.data["insufficient"] is True
        assert "数据" in r.speech

    def test_周报统计正确(self, skill_with_data):
        """本周 3 次计划，2 次按时、1 次漏服，依从率 66.7%，1 起异常。"""
        r = skill_with_data.run("generate_weekly", {"person_id": "elder_01"}, CTX)
        assert r.ok
        stats = r.data["stats"]
        assert stats["planned"] == 3
        assert stats["taken"] == 2
        assert stats["missed"] == 1
        assert stats["adherence"] == 66.7
        assert stats["incidents"] == 1
        assert "硝苯地平" in stats["missed_medicines"]

    def test_周报正文是正式文案(self, skill_with_data):
        r = skill_with_data.run("generate_weekly", {"person_id": "elder_01"}, CTX)
        body = r.data["report_body"]
        assert "依从率 66.7%" in body
        assert "漏服 1 次" in body
        assert "硝苯地平" in body
        assert "异常事件" in body

    def test_生成周报会落档案(self, skill_with_data):
        skill_with_data.run("generate_weekly", {"person_id": "elder_01"}, CTX)
        archive = skill_with_data.executor.archive_store.get("elder_01")
        assert archive is not None
        assert len(archive.snapshots) == 1
        assert archive.snapshots[0].adherence == 66.7


class TestSendReport:
    def test_发送成功产出通知(self, skill_with_data):
        r = skill_with_data.run(
            "send_report",
            {"person_id": "elder_01", "targets": ["hospital"]},
            CTX,
        )
        assert r.ok
        assert "医生" in r.speech
        notif = r.notifications[0]
        assert notif.targets == ["hospital"]
        assert "健康周报" in notif.title
        assert "依从率" in notif.body

    def test_数据不足时不能发送(self, skill):
        r = skill.run(
            "send_report",
            {"person_id": "elder_01", "targets": ["hospital"]},
            CTX,
        )
        assert r.ok
        assert r.data["insufficient"] is True
        assert r.notifications == []


class TestQueryArchive:
    def test_没有档案时给提示(self, skill):
        r = skill.run("query_archive", {"person_id": "elder_01"}, CTX)
        assert r.ok
        assert "记录" in r.speech
        assert r.data["snapshots"] == []

    def test_有档案时返回快照(self, skill_with_data):
        skill_with_data.run("generate_weekly", {"person_id": "elder_01"}, CTX)
        r = skill_with_data.run("query_archive", {"person_id": "elder_01"}, CTX)
        assert r.ok
        assert len(r.data["snapshots"]) == 1
        assert r.data["snapshots"][0]["adherence"] == 66.7


class TestQuerySummary:
    def test_没有记录时给提示(self, skill):
        r = skill.run("query_summary", {"person_id": "elder_01"}, CTX)
        assert r.ok
        assert "记录" in r.speech

    def test_按时吃药时夸老人(self, skill_with_data):
        """本周 2 次按时、1 次漏服，会提示漏服。"""
        r = skill_with_data.run("query_summary", {"person_id": "elder_01"}, CTX)
        assert r.ok
        assert "1 次忘了吃药" in r.speech
        assert "硝苯地平" in r.speech

    def test_全按时时夸老人(self, tmp_path):
        from skills.health_report import HealthArchiveStore

        monday = date(2026, 9, 21)
        logs = [
            make_log(monday, "阿司匹林", MedicationStatus.TAKEN),
            make_log(monday, "二甲双胍", MedicationStatus.TAKEN),
        ]
        store = InMemoryEventStore(medication_logs=logs)
        archive = HealthArchiveStore(tmp_path / "archives.json")
        s = HealthReportSkill(HealthReportExecutor(store, archive))

        r = s.run("query_summary", {"person_id": "elder_01"}, CTX)
        assert r.ok
        assert "挺准时的" in r.speech
        assert "100.0%" in r.speech

    def test_有异常事件会顺带提醒(self, skill_with_data):
        r = skill_with_data.run("query_summary", {"person_id": "elder_01"}, CTX)
        assert "1 起异常情况" in r.speech


# ======================================================================
# 3. tool 导出
# ======================================================================
class TestToolExport:
    def test_导出4个工具(self):
        tools = HealthReportSkill().export_tools()
        names = [t["function"]["name"] for t in tools]
        assert "health_report_generate_weekly" in names
        assert "health_report_send_report" in names
        assert "health_report_query_archive" in names
        assert "health_report_query_summary" in names

    def test_每个字段都有description(self):
        """CI 会检查每个字段有没有 description，这里提前验证。"""
        tools = HealthReportSkill().export_tools()
        for t in tools:
            props = t["function"]["parameters"].get("properties", {})
            for field_name, field_schema in props.items():
                assert "description" in field_schema, (
                    f"{t['function']['name']}.{field_name} 缺 description"
                )


# ======================================================================
# 4. 注册
# ======================================================================
class TestRegistration:
    def test_health_report被自动发现(self):
        assert get("health_report") is not None

    def test_不在跳过列表(self):
        assert "health_report" not in skills.skipped_packages()