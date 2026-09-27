"""自动周报：python weekly_scheduler.py；单次检查与补跑加 --once。"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
import time

from common import EventStore, SkillContext
from common.domain import MedicationLog
from skills.health_report import HealthArchiveStore, HealthReportExecutor, HealthReportSkill

BEIJING = timezone(timedelta(hours=8))
DEFAULT_DATA = Path(__file__).resolve().parent / "data"
logger = logging.getLogger(__name__)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


class WeeklyScheduler:
    """单实例串行调度；周结束后的周一北京时间 08:00 起可归档。

    自动从事件流发现老人/周；补跑历史遗漏，内容更新则重新生成。
    不发送通知，不推断尚未记录的服药行为。
    """

    def __init__(self, data_dir: Path = DEFAULT_DATA):
        self.data_dir = Path(data_dir).resolve()
        self.events = EventStore(self.data_dir / "events.jsonl")
        self.state_path = self.data_dir / "weekly_scheduler.json"

    def run_pending(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(BEIJING)
        if now.tzinfo is None:
            now = now.replace(tzinfo=BEIJING)
        now = now.astimezone(BEIJING)
        state = (json.loads(self.state_path.read_text(encoding="utf-8"))
                 if self.state_path.exists() else {})
        groups: dict[tuple[str, str], list[dict]] = {}
        for event in self.events.all():
            day = (event.scheduled_at if isinstance(event, MedicationLog)
                   else event.occurred_at).date()
            monday = day - timedelta(days=day.weekday())
            due = datetime.combine(monday + timedelta(days=7),
                                   datetime.min.time(), tzinfo=BEIJING) + timedelta(hours=8)
            if due > now:
                continue
            groups.setdefault((event.person_id, monday.isoformat()), []).append(
                event.model_dump(mode="json"))

        results = []
        fingerprints = {}
        # 按周补跑，让上周快照先建立，供下周对比。
        for person, week in sorted(groups, key=lambda key: (key[1], key[0])):
            key = json.dumps([person, week], ensure_ascii=False)
            records = sorted(groups[(person, week)], key=lambda record: record["id"])
            prior_week = (datetime.fromisoformat(week).date() - timedelta(days=7)).isoformat()
            fingerprint = hashlib.sha256(json.dumps(
                [records, fingerprints.get((person, prior_week))],
                sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            fingerprints[(person, week)] = fingerprint
            previous = state.get(key, {})
            report_path = self.data_dir / "weekly_reports" / (
                hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")
            entry = {"person_id": person, "week_start": week,
                     "fingerprint": fingerprint, "attempted_at": now.isoformat()}
            try:
                archives = HealthArchiveStore(self.data_dir / "health_archives.json")
                archive = archives.get(person)
                if (previous.get("status") == "done"
                        and previous.get("fingerprint") == fingerprint
                        and report_path.exists()
                        and archive is not None and archive.snapshot_for(week) is not None):
                    continue
                skill = HealthReportSkill(HealthReportExecutor(self.events, archives))
                result = skill.run("generate_weekly", {
                    "person_id": person, "week_start": week,
                }, SkillContext(speaker_id=person, speaker_name=person,
                                now=now.replace(tzinfo=None)))
                if not result.ok or result.data.get("insufficient"):
                    raise RuntimeError(result.error or result.speech)
                write_json(report_path, {**result.data, "generated_at": now.isoformat()})
                entry.update(status="done", report_file=str(report_path))
                logger.info("已生成并归档：%s，周起始日 %s", person, week)
            except Exception as exc:
                entry.update(status="failed", error=str(exc))
                logger.exception("周报失败，下次扫描重试：%s %s", person, week)
            state[key] = entry
            write_json(self.state_path, state)
            results.append(entry)
        return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="检查到期任务并退出")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    scheduler = WeeklyScheduler(args.data_dir)
    logger.info("周报调度启动：北京时间每周一 08:00 起归档，数据目录 %s", scheduler.data_dir)
    if args.once:
        results = scheduler.run_pending()
        print(json.dumps(results, ensure_ascii=False, indent=2))
        if any(result["status"] == "failed" for result in results):
            raise SystemExit(1)
        return
    try:
        while True:
            try:
                scheduler.run_pending()
            except Exception:
                logger.exception("本轮扫描失败，一分钟后重试")
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("调度已停止")


if __name__ == "__main__":
    main()
