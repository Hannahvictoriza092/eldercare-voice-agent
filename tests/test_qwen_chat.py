"""用伪造云端响应验证真实 skill 调用，不消耗 API 额度。"""
from copy import deepcopy
from datetime import datetime
import json
from types import SimpleNamespace

import pytest

from qwen_chat import QwenChat


class ToolCall:
    def __init__(self, name, arguments, call_id="call_1"):
        self.id = call_id
        self.type = "function"
        self.function = SimpleNamespace(name=name, arguments=arguments)

    def model_dump(self, **kwargs):
        return {"id": self.id, "type": self.type,
                "function": vars(self.function)}


def response(*calls, content=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=content, tool_calls=list(calls)))])


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.requests.append(deepcopy(kwargs))
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


def make_chat(tmp_path, responses=()):
    client = FakeClient(responses)
    output = []
    chat = QwenChat(client, "fake-qwen", tmp_path,
                    emit=output.append, clock=lambda: datetime(2026, 9, 21, 8))
    return chat, client, output


def create_args():
    return json.dumps({"medicine_name": "测试药", "dosage": 1,
                       "dosage_unit": "tablet", "frequency": "once_daily",
                       "times": ["08:00"]})


def test_real_pipeline_and_tool_response_protocol(tmp_path):
    responses = [
        response(ToolCall("medication_reminder_create", create_args())),
        response(ToolCall("medication_reminder_confirm_taken", "{}")), response(content="完成"),
        response(ToolCall("emergency_call_trigger", "{}")), response(content="已经拨通120"),
        response(ToolCall("health_report_generate_weekly", "{}")), response(content="报告完成"),
    ]
    chat, client, output = make_chat(tmp_path, responses)
    chat.turn("每天八点提醒我吃一片测试药")
    assert chat.medication.executor.store.all() == []
    chat.turn("对")
    chat.turn("我吃过了")
    answer = chat.turn("我需要帮助")
    assert "已经拨通120" not in answer
    chat.turn("生成本周报告")
    snapshot = chat.health.executor.archive_store.get("elder_test_01").latest()
    assert (snapshot.taken, snapshot.incidents) == (1, 1)
    assert chat.pending is None
    assert any("[周报正文]\n" in line for line in output)
    # 首次工具执行后，第二次 API 请求必须包含 assistant 调用和匹配的 tool 结果。
    sent = client.requests[2]["messages"]
    assert sent[-2]["tool_calls"][0]["id"] == sent[-1]["tool_call_id"]
    assert sent[-1]["role"] == "tool"
    assert json.loads(sent[-1]["content"])["ok"]
    assert "2026-09-21T08:00:00" in sent[0]["content"]


def test_confirmation_before_write_and_decline(tmp_path):
    chat, _, _ = make_chat(tmp_path, [response(ToolCall("medication_reminder_create", create_args()))])

    assert "对吗" in chat.turn("设提醒")
    assert chat.medication.executor.store.all() == []
    assert "没有执行" in chat.turn("算了")
    assert chat.medication.executor.store.all() == []


def test_missing_fields_followup_then_next_turn(tmp_path):
    chat, client, _ = make_chat(tmp_path, [
        response(ToolCall("medication_reminder_create", '{"medicine_name":"测试药"}')),
        response(ToolCall("medication_reminder_create", create_args())),
    ])
    chat.turn("提醒我吃测试药")
    assert chat.medication.executor.store.all() == []
    tool = next(message for message in chat.messages if message["role"] == "tool")
    assert json.loads(tool["content"])["need_followup"]
    chat.turn("每天早上八点，一片")
    assert chat.medication.executor.store.all() == []
    chat.turn("是的")
    assert len(chat.medication.executor.store.all()) == 1
    assert sum(m["role"] == "user" for m in client.requests[-1]["messages"]) == 2


@pytest.mark.parametrize("name,args", [
    ("health_report_query_archive", '{"person_id":"someone_else"}'),
    ("medication_reminder_query", '{"target_person":"someone_else"}'),
    ("emergency_call_trigger", "not-json"),
    ("emergency_call_trigger", "[]"),
    ("emergency_call_trigger", '{"extra_admin":true}'),
    ("medication_reminder_update", "{}"),
    ("medication_reminder_cancel", "{}"),
    ("unknown_tool", "{}"),
])
def test_bad_requests_do_not_write(tmp_path, name, args):
    chat, _, _ = make_chat(tmp_path, [response(ToolCall(name, args))])
    chat.turn("测试请求")
    tool = next(message for message in chat.messages if message["role"] == "tool")
    assert not json.loads(tool["content"])["ok"]
    assert chat.health.executor.store.all() == []
    assert chat.medication.executor.store.all() == []


def test_model_confirmed_true_does_not_bypass_user(tmp_path):
    responses = [response(ToolCall("emergency_call_trigger", "{}")), response(content="完成"),
                 response(ToolCall("emergency_call_cancel", '{"confirmed":true}'))]
    chat, _, _ = make_chat(tmp_path, responses)
    chat.turn("我需要帮助")
    chat.turn("这次呼救是误报")
    assert chat.emergency.executor.store.latest("elder_test_01").status == "open"


def test_duplicate_tool_call_in_same_turn_not_reexecuted(tmp_path):
    chat, client, _ = make_chat(tmp_path, [
        response(ToolCall("emergency_call_trigger", "{}", "first"),
                 ToolCall("emergency_call_trigger", "{}", "second")),
        response(content="完成"),
    ])
    chat.turn("我需要帮助")
    assert len(chat.health.executor.store.all()) == 1
    results = [m for m in client.requests[-1]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in results] == ["first", "second"]


def test_api_error_after_write_keeps_result_without_replay_or_secret(tmp_path):
    chat, _, output = make_chat(tmp_path, [
        response(ToolCall("emergency_call_trigger", "{}")), RuntimeError("secret-key-test")])
    answer = chat.turn("我需要帮助")
    assert "请求失败" in answer
    assert "secret-key-test" not in "\n".join(output)
    assert len(chat.health.executor.store.all()) == 1
    assert chat.messages[-1]["role"] == "tool"


def test_chat_clear_and_round_limit(tmp_path):
    chat, client, _ = make_chat(tmp_path, [response(content="您好")])
    assert chat.turn("你好") == "您好"
    assert len(client.requests) == 1
    chat.clear()
    assert len(chat.messages) == 1
    chat.client = FakeClient([response(ToolCall("emergency_call_trigger", "{}"))] * 6)
    assert "上限" in chat.turn("我需要帮助")
    assert len(chat.health.executor.store.all()) == 1


def test_correction_replaces_draft_and_requires_fresh_yes(tmp_path):
    chat, client, _ = make_chat(tmp_path, [
        response(ToolCall("medication_reminder_create", create_args())),
        response(ToolCall("medication_reminder_create", '{"times":["09:00"]}')),
    ])
    chat.turn("每天八点吃一片测试药")
    chat.turn("不对，改成九点")
    assert chat.medication.executor.store.all() == []
    assert chat.pending.arguments["times"] == ["09:00"]
    assert "未保存草稿" in client.requests[-1]["messages"][0]["content"]
    chat.turn("对")
    assert chat.medication.executor.store.all()[0].times == ["09:00"]
    assert len(client.requests) == 2
    chat.turn("对")
    assert len(chat.medication.executor.store.all()) == 1


@pytest.mark.parametrize("text", ["对，不过改成九点", "对，剂量不对", "不是", "查一下周报"])
def test_non_standalone_yes_never_executes_old_draft(tmp_path, text):
    chat, _, _ = make_chat(tmp_path, [
        response(ToolCall("medication_reminder_create", create_args())),
        response(content="请说具体一些"),
    ])
    chat.turn("设提醒")
    chat.turn(text)
    chat.turn("对")
    assert chat.medication.executor.store.all() == []


@pytest.mark.parametrize("action", ["clear", "expire", "cancel"])
def test_pending_invalidation(tmp_path, action):
    chat, _, _ = make_chat(tmp_path, [response(ToolCall("medication_reminder_create", create_args()))])
    chat.turn("设提醒")
    if action == "clear":
        chat.clear()
    elif action == "expire":
        chat.clock = lambda: datetime(2026, 9, 21, 8, 11)
    else:
        chat.turn("算了")
    chat.turn("对")
    assert chat.medication.executor.store.all() == []
    assert chat.pending is None


def test_correction_network_failure_cannot_approve_old_parameters(tmp_path):
    chat, _, _ = make_chat(tmp_path, [
        response(ToolCall("medication_reminder_create", create_args())), RuntimeError("offline")])
    chat.turn("设提醒")
    chat.turn("改成九点")
    chat.turn("对")
    assert chat.medication.executor.store.all() == []


def test_rescue_interrupts_pending_without_cloud_and_clears_authorization(tmp_path):
    chat, client, _ = make_chat(tmp_path, [response(ToolCall("medication_reminder_create", create_args()))])
    chat.turn("设提醒")
    chat.turn("救命，我摔倒了")
    assert len(client.requests) == 1
    assert chat.emergency.executor.store.latest("elder_test_01").status == "open"
    chat.turn("对")
    assert chat.medication.executor.store.all() == []


def test_cloud_rescue_has_priority_over_earlier_confirmation(tmp_path):
    chat, _, _ = make_chat(tmp_path, [response(
        ToolCall("medication_reminder_create", create_args(), "med"),
        ToolCall("emergency_call_trigger", "{}", "help"))])
    chat.turn("提醒我吃药，等等我摔倒了需要帮助")
    assert chat.emergency.executor.store.latest("elder_test_01").status == "open"
    assert chat.medication.executor.store.all() == []
    assert chat.pending is None


def test_cancellation_confirmation_is_bound_to_original_incident(tmp_path):
    from common import SkillContext
    chat, _, _ = make_chat(tmp_path, [response(ToolCall("emergency_call_cancel", "{}"))])
    chat.turn("救命")
    original = chat.emergency.executor.store.latest("elder_test_01").id
    chat.turn("刚才是误报，取消呼救")
    # 模拟确认期间另一来源新增事件；不能取消后来这一起。
    chat.emergency.run("trigger", {}, SkillContext(
        speaker_id="elder_test_01", now=datetime(2026, 9, 21, 8, 1)))
    latest = chat.emergency.executor.store.latest("elder_test_01").id
    assert latest != original
    chat.turn("对")
    assert chat.emergency.executor.store.get(original).status == "cancelled"
    assert chat.emergency.executor.store.get(latest).status == "open"


def test_ambiguous_medication_feedback_does_not_mark_all_taken(tmp_path):
    second = json.loads(create_args())
    second["medicine_name"] = "另一种测试药"
    chat, _, _ = make_chat(tmp_path, [
        response(ToolCall("medication_reminder_create", create_args())),
        response(ToolCall("medication_reminder_create", json.dumps(second))),
        response(ToolCall("medication_reminder_confirm_taken", "{}")),
    ])
    chat.turn("设第一种提醒")
    chat.turn("对")
    chat.turn("设第二种提醒")
    chat.turn("对")
    assert "哪种药" in chat.turn("我吃过了")
    assert all(not item.taken_log for item in chat.medication.executor.store.all())


def test_debug_output_is_opt_in(tmp_path):
    chat, _, output = make_chat(tmp_path, [response(ToolCall("medication_reminder_create", create_args()))])
    chat.turn("设提醒")
    chat.turn("对")
    assert all("[参数]" not in line and "[确认执行结果]" not in line for line in output)
    chat.debug = True
    chat.turn("救命")
    assert any("[呼救结果]" in line for line in output)


def test_text_only_confirmation_is_repaired_before_display_and_good_saves(tmp_path):
    fake_confirmation = "好的，帮您确认一下：测试药，每次1片，每天08:00。确认无误的话我就帮您设上？"
    chat, client, output = make_chat(tmp_path, [
        response(content=fake_confirmation),
        response(ToolCall("medication_reminder_create", create_args())),
    ])
    answer = chat.turn("每天早上八点提醒我吃一片测试药。")
    assert "对吗" in answer
    assert chat.pending is not None
    assert chat.medication.executor.store.all() == []
    assert not any(fake_confirmation in line for line in output)
    assert len(client.requests) == 2
    assert all(t["function"]["name"] != "medication_reminder_confirm_taken"
               for t in client.requests[1]["tools"])
    chat.turn("好的")
    saved = chat.medication.executor.store.all()
    assert len(saved) == 1
    assert saved[0].medicine_name == "测试药" and saved[0].times == ["08:00"]
    assert len(client.requests) == 2
    chat.turn("好的")
    assert len(chat.medication.executor.store.all()) == 1


def test_repeated_text_confirmation_is_bounded_and_never_shown_as_pending(tmp_path):
    chat, client, _ = make_chat(tmp_path, [response(content="确认后就帮您设上？")] * 2)
    assert "没有建立待确认" in chat.turn("设提醒")
    assert len(client.requests) == 2
    assert chat.pending is None
    chat.turn("好的")
    assert chat.medication.executor.store.all() == []


def test_confirmation_repair_cannot_execute_unapproved_side_effect(tmp_path):
    chat, _, _ = make_chat(tmp_path, [
        response(content="确认后帮您设上？"),
        response(ToolCall("emergency_call_trigger", "{}")),
    ])
    chat.turn("设提醒")
    assert chat.health.executor.store.all() == []
    assert chat.pending is None


def test_confirmation_repair_still_validates_missing_parameters(tmp_path):
    chat, _, _ = make_chat(tmp_path, [
        response(content="要设提醒，对吗？"),
        response(ToolCall("medication_reminder_create", '{"medicine_name":"测试药"}')),
    ])
    chat.turn("提醒我吃测试药")
    assert chat.pending is None
    assert chat.medication.executor.store.all() == []
    result = json.loads(chat.messages[-2]["content"])
    assert result["need_followup"]


def test_cancel_tool_disclosed_and_stops_reminder_after_confirmation(tmp_path):
    chat, client, _ = make_chat(tmp_path, [
        response(ToolCall("medication_reminder_create", create_args())),
        response(ToolCall("medication_reminder_cancel", '{"medicine_name":"测试药","keep_history":false}')),
    ])
    assert "medication_reminder_cancel" in {t["function"]["name"] for t in chat.tools}
    chat.turn("每天八点提醒我吃一片测试药")
    chat.turn("好的")
    reminder = chat.medication.executor.store.all()[0]
    chat.turn("取消测试药的提醒")
    assert chat.pending.name == "medication_reminder_cancel"
    assert chat.pending.arguments["reminder_id"] == reminder.id
    assert chat.pending.arguments["keep_history"] is True
    assert chat.medication.executor.store.get(reminder.id).active
    chat.turn("好的")
    assert not chat.medication.executor.store.get(reminder.id).active
    assert len(chat.medication.executor.store.all()) == 1
    assert len(client.requests) == 2


def test_update_time_only_after_confirmation(tmp_path):
    chat, _, _ = make_chat(tmp_path, [
        response(ToolCall("medication_reminder_create", create_args())),
        response(ToolCall("medication_reminder_update",
                          '{"medicine_name":"测试药","new_times":["09:00"]}')),
    ])
    assert "medication_reminder_update" in {t["function"]["name"] for t in chat.tools}
    chat.turn("设八点提醒")
    chat.turn("好的")
    chat.turn("把测试药的提醒改成九点")
    assert chat.pending.name == "medication_reminder_update"
    assert chat.medication.executor.store.all()[0].times == ["08:00"]
    chat.turn("好的")
    assert chat.medication.executor.store.all()[0].times == ["09:00"]


def test_stringified_time_array_from_qwen_is_validated_and_confirmed(tmp_path):
    chat, _, _ = make_chat(tmp_path, [
        response(ToolCall("medication_reminder_create", create_args())),
        response(ToolCall("medication_reminder_update",
                          json.dumps({"medicine_name": "测试药", "new_times": '["09:00"]'}))),
    ])
    chat.turn("设八点提醒")
    chat.turn("好的")
    answer = chat.turn("测试药时间改到九点")
    assert "9 点" in answer and "对吗" in answer
    assert chat.pending.arguments["new_times"] == ["09:00"]
    assert chat.medication.executor.store.all()[0].times == ["08:00"]
    chat.turn("好的")
    assert chat.medication.executor.store.all()[0].times == ["09:00"]


@pytest.mark.parametrize("bad", ['["25:00"]', '["09:00",', '{"time":"09:00"}'])
def test_bad_stringified_time_array_never_updates(tmp_path, bad):
    chat, _, _ = make_chat(tmp_path, [
        response(ToolCall("medication_reminder_create", create_args())),
        response(ToolCall("medication_reminder_update",
                          json.dumps({"medicine_name": "测试药", "new_times": bad}))),
    ])
    chat.turn("设八点提醒")
    chat.turn("好的")
    chat.turn("测试药时间改到九点")
    assert chat.pending is None
    assert chat.medication.executor.store.all()[0].times == ["08:00"]


@pytest.mark.parametrize("utterance", [
    "测试药吃了吗", "我还没吃测试药", "我没有吃过测试药", "我准备吃测试药", "好的",
])
def test_no_taken_record_without_explicit_completed_self_report(tmp_path, utterance):
    chat, _, _ = make_chat(tmp_path, [
        response(ToolCall("medication_reminder_create", create_args())),
        response(ToolCall("medication_reminder_confirm_taken", '{"medicine_name":"测试药"}')),
    ])
    chat.turn("设提醒")
    chat.turn("好的")
    chat.turn(utterance)
    assert chat.medication.executor.store.all()[0].taken_log == []


def test_explicit_taken_report_records_once(tmp_path):
    chat, _, _ = make_chat(tmp_path, [
        response(ToolCall("medication_reminder_create", create_args())),
        response(ToolCall("medication_reminder_confirm_taken", '{"medicine_name":"测试药"}')),
        response(ToolCall("medication_reminder_confirm_taken", '{"medicine_name":"测试药"}')),
    ])
    chat.turn("设提醒")
    chat.turn("好的")
    chat.turn("我已经吃过测试药了")
    assert len(chat.medication.executor.store.all()[0].taken_log) == 1
    chat.turn("我已经吃过测试药了")
    assert len(chat.medication.executor.store.all()[0].taken_log) == 1


def test_ambiguous_cancel_does_not_stop_any_reminder(tmp_path):
    other = json.loads(create_args())
    other["times"] = ["10:00"]
    chat, _, _ = make_chat(tmp_path, [
        response(ToolCall("medication_reminder_create", create_args())),
        response(ToolCall("medication_reminder_create", json.dumps(other))),
        response(ToolCall("medication_reminder_cancel", '{"medicine_name":"测试药"}')),
    ])
    chat.turn("设八点提醒")
    chat.turn("好的")
    chat.turn("设十点提醒")
    chat.turn("好的")
    chat.turn("取消测试药")
    assert chat.pending is None
    assert all(r.active for r in chat.medication.executor.store.all())
