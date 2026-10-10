"""演示运行时：把三个 skill 装进一个隔离环境，并暴露 handle()。

【为什么隔离】
- 仓库默认的事件流落在 data/events.jsonl，跑演示会污染它；这里把演示数据
  全部收进 data/web_demo/，一键即可重置。
- 三个 skill 都接到【同一个】共享 EventStore 上。这样「健康反馈读用药/呼救
  产出的数据」这条跨模块链路在演示里是真实生效的，不是假数据。

【一条话的完整链路】
    老人口语 ──(模拟 Qwen)──> tool_call ──(注册表)──> skill+action
        ──(Pydantic 校验)──> 通过 ? 执行 : 追问 ──> SkillResult ──> 回话

handle() 返回一个「轨迹」dict，UI 拿它渲染每一步，方便观众看到内部发生了什么。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import skills
from common import EventStore
from common.base import SkillContext
from common.domain import Incident, MedicationLog
from skills.emergency_call import EmergencyCallExecutor, EmergencyCallSkill, EmergencyStore
from skills.health_report import HealthArchiveStore, HealthReportExecutor, HealthReportSkill
from skills.medication_reminder import MedicationReminderSkill, ReminderStore

from .sim_qwen import parse as sim_qwen_parse

# 演示数据独立存放，避免污染仓库里的 data/events.jsonl
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "web_demo"

SKILL_NAMES = ("medication_reminder", "emergency_call", "health_report")

# 演示角色
SPEAKER_ID = "elder_01"
SPEAKER_NAME = "张奶奶"


class DemoRuntime:
    """一次演示会话的运行时。所有状态都在内存 + data/web_demo/ 里。"""

    def __init__(self, data_dir: Path | str = DEFAULT_DATA_DIR):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.reset()

    # ------------------------------------------------------------------
    # 重置：清空演示数据并重建三个 skill
    # ------------------------------------------------------------------
    def reset(self) -> None:
        for f in self.data_dir.glob("*"):
            if f.is_file():
                f.unlink()

        # 三个 skill 共享同一个事件流 —— 跨模块数据链路的关键
        self.event_store = EventStore(self.data_dir / "events.jsonl")

        for name in SKILL_NAMES:
            skills.unregister(name)

        self.medication = MedicationReminderSkill(
            ReminderStore(self.data_dir / "reminders.json", event_store=self.event_store),
            self.event_store,
        )
        self.emergency = EmergencyCallSkill(
            EmergencyCallExecutor(
                EmergencyStore(self.data_dir / "emergency.json", event_store=self.event_store),
                self.event_store,
            )
        )
        self.health = HealthReportSkill(
            HealthReportExecutor(
                store=self.event_store,
                archive_store=HealthArchiveStore(self.data_dir / "archive.json"),
            )
        )

        for skill in (self.medication, self.emergency, self.health):
            skills.register(skill)

    # ------------------------------------------------------------------
    # 渠道
    # ------------------------------------------------------------------
    def handle(self, utterance: str, now: datetime | None = None) -> dict[str, Any]:
        """处理一句话，返回可渲染的轨迹 dict。"""
        now = now or datetime.now()
        ctx = SkillContext(speaker_id=SPEAKER_ID, speaker_name=SPEAKER_NAME, now=now)

        decision = sim_qwen_parse(utterance, speaker_id=SPEAKER_ID)

        trace: dict[str, Any] = {
            "utterance": utterance,
            "qwen": {
                "tool_name": decision.tool_name,
                "arguments": decision.arguments,
                "reason": decision.reason,
                "hit": decision.hit,
            },
            "registry": None,
            "result": None,
            "speech": "",
            "stage": "",          # 用于 UI 上色：chitchat / followup / ok / error / unknown_tool
        }

        # 闲聊：不调工具
        if decision.tool_name is None:
            trace["stage"] = "chitchat"
            trace["speech"] = decision.reply
            return trace

        # 查注册表
        found = skills.find_by_tool_name(decision.tool_name)
        if found is None:
            trace["stage"] = "unknown_tool"
            trace["speech"] = "抱歉，我暂时没听明白您要做哪件事。"
            return trace

        skill, action = found
        trace["registry"] = {
            "skill": skill.name,
            "display_name": skill.display_name,
            "action": action,
            "risk_level": skill.risk_level.value,
        }

        # 执行（run 内部会先做 Pydantic 校验，失败转追问）
        result = skill.run(action, decision.arguments, ctx)
        trace["result"] = _result_to_dict(result)

        if result.need_followup:
            trace["stage"] = "followup"
            trace["speech"] = result.followup_question or result.speech
        elif result.ok:
            trace["stage"] = "ok"
            trace["speech"] = result.speech
        else:
            trace["stage"] = "error"
            trace["speech"] = result.speech

        return trace

    # ------------------------------------------------------------------
    # 事件流快照（给 UI 的表格用）
    # ------------------------------------------------------------------
    def events_snapshot(self) -> list[list[str]]:
        rows: list[list[str]] = []
        for event in self.event_store.all():
            if isinstance(event, MedicationLog):
                rows.append([
                    "服药记录",
                    event.medicine_name,
                    f"{event.dosage:g}{_unit_cn(event.dosage_unit)}",
                    _status_cn(event.status.value),
                    event.scheduled_at.strftime("%m-%d %H:%M"),
                    event.source,
                ])
            elif isinstance(event, Incident):
                rows.append([
                    "异常事件",
                    _incident_type_cn(event.type.value),
                    event.location or "位置未提供",
                    _status_cn(event.status.value),
                    event.occurred_at.strftime("%m-%d %H:%M"),
                    event.severity,
                ])
        rows.sort(key=lambda r: r[4], reverse=True)
        return rows

    # ------------------------------------------------------------------
    # 定时调度演示：某个时刻该提醒谁吃药
    # ------------------------------------------------------------------
    def due_reminders(self, at: datetime) -> list[dict[str, Any]]:
        return self.medication.due_reminders(at)

    def notifications_snapshot(self) -> list[dict[str, Any]]:
        """把目前事件流里能体现的通知需求列出来（演示出站层的输入）。"""
        out: list[dict[str, Any]] = []
        for event in self.event_store.all():
            if isinstance(event, Incident):
                out.append({
                    "来源": "呼救",
                    "对象": f"{_incident_type_cn(event.type.value)} / {event.id}",
                    "状态": _status_cn(event.status.value),
                    "说明": f"严重度 {event.severity}，已通知 {event.notified_targets or '（待出站层发送）'}",
                })
        return out


# ======================================================================
# 小工具
# ======================================================================
_UNIT_CN = {
    "tablet": "片", "capsule": "粒", "bag": "袋", "ml": "ml", "mg": "mg",
    "g": "g", "drop": "滴", "puff": "喷", "suppository": "粒", "patch": "贴", "unit": "支",
}
_STATUS_CN = {
    "taken": "已服用", "missed": "漏服", "skipped": "跳过", "pending": "待服用",
    "open": "已发起", "acked": "已接单", "en_route": "在途", "arrived": "已到达",
    "resolved": "已解决", "cancelled": "已取消", "failed": "联系失败",
}
_INCIDENT_CN = {
    "sos": "主动呼救", "fall_detected": "跌倒检测",
    "medication_missed": "漏服", "health_abnormal": "健康异常",
}


def _unit_cn(unit: str) -> str:
    return _UNIT_CN.get(unit, unit)


def _status_cn(status: str) -> str:
    return _STATUS_CN.get(status, status)


def _incident_type_cn(t: str) -> str:
    return _INCIDENT_CN.get(t, t)


def _result_to_dict(result) -> dict[str, Any]:
    """把 SkillResult 转成 UI 好渲染的 dict。"""
    return {
        "ok": result.ok,
        "skill": result.skill,
        "action": result.action,
        "need_followup": result.need_followup,
        "followup_question": result.followup_question,
        "speech": result.speech,
        "error": result.error,
        "confirm_level": getattr(result.confirm_level, "value", str(result.confirm_level)),
        "data": _jsonable(result.data),
        "notifications": [_jsonable(n.model_dump(mode="json")) for n in result.notifications],
    }


def _jsonable(obj: Any) -> Any:
    """把 datetime / Enum 之类转成可 JSON 序列化的形式。"""
    return json.loads(json.dumps(obj, ensure_ascii=False, default=str))
