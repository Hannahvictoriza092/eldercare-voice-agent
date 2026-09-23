"""呼救业务逻辑。只生成 Notification，实际发送由上层出站服务负责。"""

from __future__ import annotations

from uuid import uuid4

from common.base import SkillContext, SkillResult
from common.domain import (
    Incident, IncidentStatus, IncidentType, Notification, NotifyTarget,
    StatusChange, Urgency,
)

from . import messages as msg
from .schema import CancelParams, CheckProgressParams, ConfirmSafeParams, TriggerParams
from .store import ACTIVE, EmergencyStore

SKILL_NAME = "emergency_call"
TARGETS = [NotifyTarget.FAMILY, NotifyTarget.COMMUNITY, NotifyTarget.EMERGENCY]
PROGRESS = {
    IncidentStatus.OPEN: msg.PENDING,
    IncidentStatus.ACKED: msg.ACKED,
    IncidentStatus.EN_ROUTE: msg.EN_ROUTE,
    IncidentStatus.ARRIVED: msg.ARRIVED,
    IncidentStatus.RESOLVED: msg.RESOLVED,
    IncidentStatus.CANCELLED: msg.CANCELLED,
    IncidentStatus.FAILED: msg.FAILED,
}


class EmergencyCallExecutor:
    def __init__(self, store: EmergencyStore | None = None):
        self.store = store if store is not None else EmergencyStore()

    def _result(self, action: str, speech: str, **data) -> SkillResult:
        return SkillResult(ok=True, skill=SKILL_NAME, action=action, speech=speech, data=data)

    def _notification(self, incident: Incident, ctx: SkillContext, title: str,
                      body: str, targets: list[NotifyTarget] | None = None) -> Notification:
        return Notification(
            id=f"notify_{uuid4().hex}", person_id=incident.person_id,
            targets=targets if targets is not None else TARGETS,
            urgency=Urgency.CRITICAL, title=title, body=body,
            created_at=ctx.now, related_incident_id=incident.id,
        )

    def _find(self, incident_id: str | None, person_id: str,
              active_only: bool = False) -> Incident | None:
        incident = self.store.get(incident_id) if incident_id else self.store.latest(person_id, active_only)
        if incident is None or incident.person_id != person_id or incident.type != IncidentType.SOS:
            return None
        return incident

    def trigger(self, params: TriggerParams, ctx: SkillContext) -> SkillResult:
        person_id = ctx.person()
        incident = Incident(
            id=f"sos_{uuid4().hex}", person_id=person_id, type=IncidentType.SOS,
            severity="critical", occurred_at=ctx.now, location=params.location,
            status_history=[StatusChange(status=IncidentStatus.OPEN, at=ctx.now)],
            detail={"reason": params.reason or "未说明", "current_condition": params.current_condition},
        )
        try:
            self.store.save(incident)
        except Exception as exc:
            return SkillResult(ok=False, skill=SKILL_NAME, action="trigger",
                               speech=msg.STORE_ERROR, error=f"{type(exc).__name__}: {exc}")
        body = f"{ctx.speaker_name}发起紧急呼救。原因：{params.reason or '未说明'}。"
        body += f"位置：{params.location or '未知，请联系本人核实'}。"
        if params.current_condition:
            body += f"当前状态：{params.current_condition}。"
        notification = self._notification(incident, ctx, "紧急呼救", body)
        return self._result("trigger", msg.TRIGGERED,
                            incident=incident.model_dump(mode="json"),
                            notifications=[notification.model_dump(mode="json")],
                            notification_pending=True)

    def check_progress(self, params: CheckProgressParams, ctx: SkillContext) -> SkillResult:
        incident = self._find(params.incident_id, ctx.person())
        if incident is None:
            return self._result("check_progress", msg.NO_INCIDENT)
        speech = PROGRESS[incident.status]
        latest = incident.status_history[-1] if incident.status_history else None
        if incident.status == IncidentStatus.EN_ROUTE and latest and latest.eta_minutes is not None:
            from common.timefmt import in_future_cn
            speech += f"预计{in_future_cn(latest.eta_minutes)}。"
        return self._result("check_progress", speech,
                            incident=incident.model_dump(mode="json"))

    def cancel(self, params: CancelParams, ctx: SkillContext) -> SkillResult:
        incident = self._find(params.incident_id, ctx.person(), active_only=True)
        if incident is None:
            return self._result("cancel", msg.NO_INCIDENT)
        if incident.status not in ACTIVE:
            return self._result("cancel", msg.ALREADY_CLOSED)
        if not params.confirmed:
            return SkillResult(ok=False, skill=SKILL_NAME, action="cancel",
                               speech=msg.NEED_CANCEL_CONFIRM, need_followup=True,
                               followup_question=msg.NEED_CANCEL_CONFIRM,
                               data={"incident_id": incident.id})
        incident = incident.model_copy(deep=True)
        incident.status = IncidentStatus.CANCELLED
        incident.resolved_at = ctx.now
        incident.status_history.append(StatusChange(status=IncidentStatus.CANCELLED, at=ctx.now,
                                                    note=params.reason or "老人确认取消"))
        self.store.save(incident)
        notification = self._notification(incident, ctx, "呼救取消",
                                          f"{ctx.speaker_name}确认取消呼救：{params.reason or '未说明原因'}。",
                                          [NotifyTarget.FAMILY, NotifyTarget.COMMUNITY])
        return self._result("cancel", msg.CANCEL_OK,
                            incident=incident.model_dump(mode="json"),
                            notifications=[notification.model_dump(mode="json")],
                            notification_pending=True)

    def confirm_safe(self, params: ConfirmSafeParams, ctx: SkillContext) -> SkillResult:
        incident = self._find(params.incident_id, ctx.person(), active_only=True)
        if incident is None:
            return self._result("confirm_safe", msg.NO_INCIDENT)
        if incident.status not in ACTIVE:
            return self._result("confirm_safe", msg.ALREADY_CLOSED)
        if not params.confirmed:
            return SkillResult(ok=False, skill=SKILL_NAME, action="confirm_safe",
                               speech=msg.NEED_SAFE_CONFIRM, need_followup=True,
                               followup_question=msg.NEED_SAFE_CONFIRM,
                               data={"incident_id": incident.id})
        incident = incident.model_copy(deep=True)
        incident.status = IncidentStatus.RESOLVED
        incident.resolved_at = ctx.now
        incident.status_history.append(StatusChange(status=IncidentStatus.RESOLVED, at=ctx.now,
                                                    note="老人确认安全"))
        self.store.save(incident)
        notification = self._notification(incident, ctx, "老人已报平安",
                                          f"{ctx.speaker_name}已确认安全，原呼救结束。",
                                          [NotifyTarget.FAMILY, NotifyTarget.COMMUNITY])
        return self._result("confirm_safe", msg.SAFE_OK,
                            incident=incident.model_dump(mode="json"),
                            notifications=[notification.model_dump(mode="json")],
                            notification_pending=True)

    def update_status(self, incident_id: str, status: IncidentStatus,
                      ctx: SkillContext, note: str = "", eta_minutes: int | None = None) -> Incident:
        """供可信的救助出站层写入真实进度；不暴露为语音工具。"""
        incident = self.store.get(incident_id)
        if incident is None:
            raise ValueError("呼救事件不存在")
        if incident.status in {IncidentStatus.CANCELLED, IncidentStatus.RESOLVED}:
            raise ValueError("已结束的呼救不能再更新")
        allowed = {
            IncidentStatus.OPEN: {IncidentStatus.ACKED, IncidentStatus.FAILED},
            IncidentStatus.FAILED: {IncidentStatus.ACKED},
            IncidentStatus.ACKED: {IncidentStatus.EN_ROUTE, IncidentStatus.ARRIVED, IncidentStatus.FAILED},
            IncidentStatus.EN_ROUTE: {IncidentStatus.ARRIVED, IncidentStatus.FAILED},
            IncidentStatus.ARRIVED: {IncidentStatus.RESOLVED},
        }
        if status not in allowed.get(incident.status, set()):
            raise ValueError("无效的呼救状态变更")
        updated = incident.model_copy(deep=True)
        updated.status = status
        updated.status_history.append(StatusChange(status=status, at=ctx.now, note=note,
                                                   eta_minutes=eta_minutes))
        if status == IncidentStatus.RESOLVED:
            updated.resolved_at = ctx.now
        self.store.save(updated)
        return updated
