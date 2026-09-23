"""呼救关键路径：立即创建、真实进度、本人隔离和确认后结束。"""

from datetime import datetime, timedelta

import pytest

from common.base import SkillContext
from common.domain import IncidentStatus
from skills.emergency_call import EmergencyCallExecutor, EmergencyCallSkill, EmergencyStore


@pytest.fixture
def setup_skill(tmp_path):
    store = EmergencyStore(tmp_path / "incidents.json")
    executor = EmergencyCallExecutor(store)
    skill = EmergencyCallSkill(executor)
    ctx = SkillContext(speaker_id="elder_01", speaker_name="张奶奶",
                       now=datetime(2026, 9, 23, 10, 0))
    return skill, executor, store, ctx


def test_紧急呼救不等待补充信息且持久化(setup_skill):
    skill, _, store, ctx = setup_skill
    result = skill.run("trigger", {}, ctx)
    assert result.ok and not result.need_followup
    assert "120" in result.speech and "已联系" not in result.speech
    incident_id = result.data["incident"]["id"]
    assert store.get(incident_id).status == IncidentStatus.OPEN
    assert result.data["notifications"][0]["urgency"] == "critical"
    assert result.data["notifications"][0]["delivered"] is False
    assert EmergencyStore(store.path).get(incident_id) is not None


def test_进度仅由可信状态更新而非发出通知决定(setup_skill):
    skill, executor, _, ctx = setup_skill
    incident_id = skill.run("trigger", {"reason": "摔倒"}, ctx).data["incident"]["id"]
    before = skill.run("check_progress", {}, ctx)
    assert "尚未收到" in before.speech
    executor.update_status(incident_id, IncidentStatus.ACKED,
                           ctx.model_copy(update={"now": ctx.now + timedelta(minutes=2)}))
    after = skill.run("check_progress", {}, ctx)
    assert "已确认收到" in after.speech
    with pytest.raises(ValueError):
        executor.update_status(incident_id, IncidentStatus.OPEN, ctx)


def test_取消和报平安都要求确认并产生后续通知(setup_skill):
    skill, _, store, ctx = setup_skill
    first_id = skill.run("trigger", {}, ctx).data["incident"]["id"]
    pending = skill.run("cancel", {}, ctx)
    assert pending.need_followup and store.get(first_id).status == IncidentStatus.OPEN
    cancelled = skill.run("cancel", {"confirmed": True, "reason": "按错了"}, ctx)
    assert cancelled.ok and store.get(first_id).status == IncidentStatus.CANCELLED
    assert cancelled.data["notifications"][0]["related_incident_id"] == first_id
    second_id = skill.run("trigger", {}, ctx).data["incident"]["id"]
    safe = skill.run("confirm_safe", {"confirmed": True}, ctx)
    assert safe.ok and store.get(second_id).status == IncidentStatus.RESOLVED


def test_不能查询或修改其他老人的呼救(setup_skill):
    skill, _, store, ctx = setup_skill
    incident_id = skill.run("trigger", {}, ctx).data["incident"]["id"]
    other = ctx.model_copy(update={"speaker_id": "elder_02"})
    assert "没有找到" in skill.run("check_progress", {"incident_id": incident_id}, other).speech
    skill.run("cancel", {"incident_id": incident_id, "confirmed": True}, other)
    assert store.get(incident_id).status == IncidentStatus.OPEN


def test_所有工具字段都有说明(setup_skill):
    skill, _, _, _ = setup_skill
    tools = skill.export_tools()
    assert {tool["function"]["name"] for tool in tools} == {
        "emergency_call_trigger", "emergency_call_check_progress",
        "emergency_call_cancel", "emergency_call_confirm_safe",
    }
    for tool in tools:
        assert all(prop.get("description") for prop in
                   tool["function"]["parameters"]["properties"].values())
