"""可视化演示：两个上游写记录，health_report 实时读取并重载档案。

运行：python demo_pipeline.py
"""
from datetime import datetime
from tempfile import TemporaryDirectory
import json

from common import SkillContext
from common.domain import IncidentStatus
from skills.medication_reminder import MedicationReminderSkill
from skills.emergency_call import EmergencyCallSkill
from skills.health_report import HealthReportSkill

def ctx(day=21, hour=8):
    return SkillContext(speaker_id="elder_01", speaker_name="张奶奶",
                        now=datetime(2026, 9, day, hour))

def show(title, value):
    print(f"\n=== {title} ===")
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))

def main():
    import os
    original_dir = os.getcwd()
    with TemporaryDirectory(prefix="eldercare-pipeline-") as workdir:
        os.chdir(workdir)
        # 先初始化三个模块，专门验证后续写入对已存在读取者可见。
        health = HealthReportSkill()
        medication = MedicationReminderSkill()
        emergency = EmergencyCallSkill()
        print("临时数据目录：", workdir)

        created = medication.run("create", {
            "medicine_name": "测试药", "dosage": 1, "dosage_unit": "tablet",
            "frequency": "once_daily", "times": ["08:00"],
            "start_date": "2026-09-21",
        }, ctx())
        show("1. 用药提醒创建计划", created.data)
        taken = medication.run("confirm_taken", {}, ctx())
        show("2. 用药提醒确认已服", taken.data)
        missed = medication.due_reminders(ctx(22, 10).now)
        show("3. 调度器产生漏服记录", missed)

        sos = emergency.run("trigger", {"reason": "需要帮助"}, ctx(22))
        incident_id = sos.data["incident"]["id"]
        emergency.executor.update_status(incident_id, IncidentStatus.ACKED, ctx(22))
        emergency.executor.update_status(incident_id, IncidentStatus.EN_ROUTE, ctx(22))
        show("4. 呼救产生并推进事件", {"incident_id": incident_id, "status": "en_route"})

        report = health.run("generate_weekly", {
            "person_id": "elder_01", "week_start": "2026-09-21"
        }, ctx(22, 10))
        show("5. health_report 实时读取并生成周报", {
            "stats": report.data.get("stats"),
            "report_body": report.data.get("report_body"),
        })

        taken_later = medication.run("confirm_taken", {}, ctx(22, 12))
        updated = health.run("generate_weekly", {
            "person_id": "elder_01", "week_start": "2026-09-21"
        }, ctx(22, 12))
        show("6. 补服后同一记录被覆盖", updated.data.get("stats"))

        restarted = HealthReportSkill()
        archive = restarted.run("query_archive", {"person_id": "elder_01"}, ctx(22, 12))
        show("7. 重建 health_report 后重载档案", archive.data)
        print("\n闭环演示完成。")
    os.chdir(original_dir)

if __name__ == "__main__":
    main()
