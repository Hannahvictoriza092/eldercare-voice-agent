"""健康和照顾反馈的存储层：个性化档案。

先落地成 JSON 文件，好处是零依赖、能直接 git diff、方便组内联调。
接口都是方法调用，之后要换成 SQLite / MySQL，只要保持这几个方法签名不变，
executor 一行都不用改。

【存什么】
个性化档案是长期积累的老人画像：每周的依从率、漏服、异常事件，
以及据此生成的趋势描述。每次生成周报时更新一次。

【不存什么】
原始服药记录（MedicationLog）和异常事件（Incident）不在这里——
那些属于共享事件流，由用药提醒/呼救产出，本 skill 只读不写。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path("data/health_archives.json")


@dataclass
class WeeklySnapshot:
    """某一周的画像快照。周报生成时落一条，供长期趋势分析。"""

    week_start: str                 # 周一起始日 YYYY-MM-DD
    adherence: float | None         # 兼容字段：已服记录占比，不是按时率/计划完成率
    planned: int = 0                # 兼容字段：已有服药记录数，不是应服次数
    taken: int = 0                  # 已服记录数（包括补服）
    missed: int = 0                 # 漏服次数
    missed_medicines: list[str] = field(default_factory=list)  # 漏服的药名
    incidents: int = 0              # 异常事件次数
    generated_at: str = ""          # 生成时间 ISO
    skipped: int = 0               # 主动跳过
    pending: int = 0               # 待确认

    def to_dict(self) -> dict[str, Any]:
        """保留旧字段，并提供口径明确的新字段。"""
        return {
            **asdict(self),
            "record_count": self.planned,
            "taken_ratio": self.adherence,
        }


@dataclass
class HealthArchive:
    """一位老人的个性化档案。"""

    person_id: str
    snapshots: list[WeeklySnapshot] = field(default_factory=list)  # 按周升序
    created_at: str = ""
    updated_at: str = ""

    def latest(self) -> WeeklySnapshot | None:
        return self.snapshots[-1] if self.snapshots else None

    def snapshot_for(self, week_start: str) -> WeeklySnapshot | None:
        for s in self.snapshots:
            if s.week_start == week_start:
                return s
        return None


class HealthArchiveStore:
    """个性化档案的读写。单进程使用，没做并发控制——接数据库时由数据库负责。"""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, HealthArchive] = {}
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
        self._items = {}
        for a in raw:
            # JSON 不会自动恢复嵌套 dataclass；旧档案新增字段使用默认值。
            snapshots = [WeeklySnapshot(**s) for s in a.get("snapshots", [])]
            snapshots.sort(key=lambda s: s.week_start)
            archive = HealthArchive(**{**a, "snapshots": snapshots})
            self._items[archive.person_id] = archive

    def _save(self) -> None:
        payload = [asdict(a) for a in self._items.values()]
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(self.path)

    # ---------------- 增删改查 ----------------
    def get(self, person_id: str) -> HealthArchive | None:
        self._load()
        return self._items.get(person_id)

    def all(self) -> list[HealthArchive]:
        self._load()
        return list(self._items.values())

    def get_or_create(self, person_id: str) -> HealthArchive:
        """取某位老人的档案，没有就建一个空的。"""
        archive = self._items.get(person_id)
        if archive is None:
            archive = HealthArchive(
                person_id=person_id,
                created_at=datetime.now().isoformat(timespec="seconds"),
            )
            self._items[person_id] = archive
        return archive

    def save_snapshot(self, person_id: str, snapshot: WeeklySnapshot) -> HealthArchive:
        """写入（或覆盖）某一周的画像快照，并更新时间戳。"""
        self._load()
        archive = self.get_or_create(person_id)
        if not snapshot.generated_at:
            snapshot.generated_at = datetime.now().isoformat(timespec="seconds")

        # 覆盖同周快照，避免重复积累
        for i, s in enumerate(archive.snapshots):
            if s.week_start == snapshot.week_start:
                archive.snapshots[i] = snapshot
                break
        else:
            archive.snapshots.append(snapshot)

        # 按周升序排，方便取「上一周」
        archive.snapshots.sort(key=lambda s: s.week_start)
        archive.updated_at = datetime.now().isoformat(timespec="seconds")
        self._save()
        return archive

    def delete(self, person_id: str) -> bool:
        self._load()
        if person_id in self._items:
            del self._items[person_id]
            self._save()
            return True
        return False
