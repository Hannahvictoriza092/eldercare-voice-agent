"""用药提醒 skill 的测试。

分三层，对应联调时会踩的三种坑：
  1. schema 测试 —— Qwen 填的参数对不对（含故意填错的负面用例）
  2. executor 测试 —— 业务逻辑对不对
  3. tool 导出测试 —— 导出的 schema Qwen 能不能用
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

import skills
from skills import SkillContext, get
from skills.medication_reminder import MedicationReminderSkill, ReminderStore
from skills.medication_reminder.schema import (
    CancelReminderParams,
    ConfirmTakenParams,
    CreateReminderParams,
    DosageUnit,
    Frequency,
    QueryScheduleParams,
    Timing,
    UpdateReminderParams,
)

# 固定时间，避免测试在半夜跑出不一样的结果
NOW = datetime(2026, 9, 19, 8, 0, 0)
CTX = SkillContext(speaker_id="elder_01", speaker_name="张奶奶", now=NOW)


def datetime_ctx(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> SkillContext:
    """造一个指定「现在」的上下文。"""
    return SkillContext(speaker_id="elder_01", speaker_name="张奶奶",
                        now=datetime(y, m, d, hh, mm))


@pytest.fixture()
def skill(tmp_path) -> MedicationReminderSkill:
    store = ReminderStore(tmp_path / "reminders.json")
    return MedicationReminderSkill(store)


def create_sample(skill: MedicationReminderSkill, **overrides):
    """建一条标准的阿司匹林提醒：每天早八点一片。"""
    raw = {
        "medicine_name": "阿司匹林",
        "dosage": 1,
        "dosage_unit": "tablet",
        "frequency": "once_daily",
        "times": ["08:00"],
        "timing": "after_meal",
    }
    raw.update(overrides)
    return skill.run("create", raw, CTX)


# ======================================================================
# 1. schema 层
# ======================================================================
class TestCreateSchema:
    def test_正常参数通过(self):
        p = CreateReminderParams(
            medicine_name="阿司匹林",
            dosage=1,
            dosage_unit=DosageUnit.tablet,
            frequency=Frequency.once_daily,
            times=["08:00"],
        )
        assert p.times == ["08:00"]

    def test_时间格式不对要报错(self):
        with pytest.raises(Exception) as e:
            CreateReminderParams(
                medicine_name="阿司匹林", dosage=1, dosage_unit="tablet",
                frequency="once_daily", times=["8点"],
            )
        assert "HH:mm" in str(e.value)

    def test_一天三次只给两个时间点要报错(self):
        """这是最容易出现的填参错误，程序必须拦住。"""
        with pytest.raises(Exception) as e:
            CreateReminderParams(
                medicine_name="二甲双胍", dosage=2, dosage_unit="capsule",
                frequency="three_times_daily", times=["08:00", "20:00"],
            )
        assert "3 个" in str(e.value)

    def test_剂量不能为负(self):
        with pytest.raises(Exception):
            CreateReminderParams(
                medicine_name="阿司匹林", dosage=-1, dosage_unit="tablet",
                frequency="once_daily", times=["08:00"],
            )

    def test_每日两次两个时间点自动排序(self):
        p = CreateReminderParams(
            medicine_name="二甲双胍", dosage=1, dosage_unit="tablet",
            frequency="twice_daily", times=["20:00", "08:00"],
        )
        assert p.times == ["08:00", "20:00"]

    def test_weekly_必须给星期(self):
        with pytest.raises(Exception) as e:
            CreateReminderParams(
                medicine_name="阿仑膦酸钠", dosage=1, dosage_unit="tablet",
                frequency="weekly", times=["08:00"],
            )
        assert "weekdays" in str(e.value)

    def test_非weekly_不该给星期(self):
        with pytest.raises(Exception):
            CreateReminderParams(
                medicine_name="阿司匹林", dosage=1, dosage_unit="tablet",
                frequency="once_daily", times=["08:00"], weekdays=[0],
            )

    def test_结束日期不能早于开始日期(self):
        with pytest.raises(Exception) as e:
            CreateReminderParams(
                medicine_name="阿莫西林", dosage=1, dosage_unit="capsule",
                frequency="twice_daily", times=["08:00", "20:00"],
                start_date="2026-09-20", end_date="2026-09-10",
            )
        assert "end_date" in str(e.value)

    def test_重复时间点要报错(self):
        with pytest.raises(Exception):
            CreateReminderParams(
                medicine_name="阿司匹林", dosage=1, dosage_unit="tablet",
                frequency="twice_daily", times=["08:00", "08:00"],
            )

    def test_按需服用不该有固定时间(self):
        with pytest.raises(Exception):
            CreateReminderParams(
                medicine_name="硝酸甘油", dosage=1, dosage_unit="tablet",
                frequency="as_needed", times=["08:00"],
            )


class TestOtherSchemas:
    def test_修改必须能定位到提醒(self):
        with pytest.raises(Exception) as e:
            UpdateReminderParams(new_times=["09:00"])
        assert "medicine_name" in str(e.value) or "reminder_id" in str(e.value)

    def test_修改必须给出要改什么(self):
        with pytest.raises(Exception):
            UpdateReminderParams(medicine_name="阿司匹林")

    def test_取消必须能定位到提醒(self):
        with pytest.raises(Exception):
            CancelReminderParams(reason="医生说停药")

    def test_查询允许全空(self):
        p = QueryScheduleParams()
        assert p.medicine_name is None and p.date is None


# ======================================================================
# 2. executor 层
# ======================================================================
class TestCreate:
    def test_创建成功并能查到(self, skill):
        r = create_sample(skill)
        assert r.ok
        assert "阿司匹林" in r.speech
        assert "早上 8 点" in r.speech
        assert r.data["require_confirm_back"] is True

    def test_重复创建会提示而不是堆两条(self, skill):
        create_sample(skill)
        r = create_sample(skill)
        assert r.ok
        assert r.data["duplicated"] is True
        assert len(skill.executor.store.all()) == 1

    def test_半片要念成半片(self, skill):
        r = create_sample(skill, dosage=0.5)
        assert "半片" in r.speech

    def test_有疗程的话术带日期(self, skill):
        r = create_sample(skill, end_date="2026-09-30")
        assert "2026-09-30" in r.speech


class TestQuery:
    def test_没有药时说放心(self, skill):
        r = skill.run("query", {}, CTX)
        assert r.ok
        assert "没有什么要吃的药" in r.speech

    def test_有未服药时列出来(self, skill):
        create_sample(skill)
        r = skill.run("query", {}, CTX)
        assert r.ok
        assert "阿司匹林" in r.speech
        assert len(r.data["pending"]) == 1

    def test_服药后提示全部吃完(self, skill):
        create_sample(skill)
        skill.run("confirm_taken", {}, CTX)
        r = skill.run("query", {}, CTX)
        assert "都吃完啦" in r.speech

    def test_只看未服用(self, skill):
        create_sample(skill, frequency="twice_daily", times=["08:00", "20:00"])
        EIGHT = SkillContext(speaker_id="elder_01", speaker_name="张奶奶",
                             now=datetime(2026, 9, 19, 8, 5))
        skill.run("confirm_taken", {}, EIGHT)
        r = skill.run("query", {"un_taken_only": True}, CTX)
        assert len(r.data["plan"]) == 1
        assert r.data["plan"][0]["slot"] == "20:00"


class TestConfirmTaken:
    def test_确认服药写进日志(self, skill):
        r = create_sample(skill)
        rid = r.data["reminder_id"]
        res = skill.run("confirm_taken", {}, CTX)
        assert res.ok
        assert res.data["slot"] == "08:00"
        assert skill.executor.store.get(rid).taken_log[0]["slot"] == "08:00"

    def test_重复确认不重复记录(self, skill):
        create_sample(skill)
        skill.run("confirm_taken", {}, CTX)
        res = skill.run("confirm_taken", {}, CTX)
        assert res.ok
        assert res.data["matched"] is False

    def test_药名对不上时提示加提醒(self, skill):
        res = skill.run("confirm_taken", {"medicine_name": "感冒灵"}, CTX)
        assert res.data["matched"] is False
        assert "感冒灵" in res.speech

    def test_早上吃的能匹配到早上那次(self, skill):
        create_sample(skill, frequency="twice_daily", times=["08:00", "20:00"])
        MORNING = SkillContext(speaker_id="elder_01", speaker_name="张奶奶",
                               now=datetime(2026, 9, 19, 9, 30))
        res = skill.run("confirm_taken", {"taken_at": "2026-09-19T09:00:00"}, MORNING)
        assert res.data["slot"] == "08:00"

    def test_剩药时会补一句(self, skill):
        create_sample(skill, frequency="twice_daily", times=["08:00", "20:00"])
        res = skill.run("confirm_taken", {}, CTX)
        assert "还有 1 次药" in res.speech


class TestUpdate:
    def test_改时间(self, skill):
        create_sample(skill, frequency="twice_daily", times=["08:00", "20:00"])
        r = skill.run("update", {"medicine_name": "阿司匹林", "new_times": ["08:00", "21:00"]}, CTX)
        assert r.ok
        assert "晚上 9 点" in r.speech

    def test_改剂量(self, skill):
        create_sample(skill)
        r = skill.run("update", {"medicine_name": "阿司匹林", "new_dosage": 0.5}, CTX)
        assert r.ok
        assert "半片" in r.speech

    def test_找不到药时追问(self, skill):
        r = skill.run("update", {"medicine_name": "感冒灵", "new_dosage": 1}, CTX)
        assert r.need_followup

    def test_改频次但时间点不够时追问(self, skill):
        """从每日一次改成每日三次，只有 1 个时间点，必须追问而不是默默改掉。"""
        create_sample(skill)
        r = skill.run("update", {"medicine_name": "阿司匹林", "new_frequency": "three_times_daily"}, CTX)
        assert r.need_followup
        assert r.data["need_times"] is True

    def test_同名多条时让老人选(self, skill):
        create_sample(skill, times=["08:00"], frequency="once_daily")
        create_sample(skill, times=["20:00"], frequency="once_daily")
        r = skill.run("update", {"medicine_name": "阿司匹林", "new_dosage": 2}, CTX)
        assert r.need_followup
        assert len(r.data["candidates"]) == 2


class TestCancel:
    def test_取消后不再出现在计划里(self, skill):
        create_sample(skill)
        r = skill.run("cancel", {"medicine_name": "阿司匹林", "reason": "医生让停"}, CTX)
        assert r.ok
        assert r.data["notify_family"] is True
        assert skill.run("query", {}, CTX).data["plan"] == []

    def test_默认保留历史记录(self, skill):
        create_sample(skill)
        skill.run("confirm_taken", {}, CTX)
        skill.run("cancel", {"medicine_name": "阿司匹林"}, CTX)
        assert len(skill.executor.store.all()) == 1

    def test_明确要删才硬删除(self, skill):
        create_sample(skill)
        skill.run("cancel", {"medicine_name": "阿司匹林", "keep_history": False}, CTX)
        assert skill.executor.store.all() == []

    def test_取消失败时追问(self, skill):
        r = skill.run("cancel", {"medicine_name": "不存在的药"}, CTX)
        assert r.need_followup


# ======================================================================
# 3. 调度接口
# ======================================================================
class TestDueReminders:
    def test_到点能取出来(self, skill):
        create_sample(skill)
        due = skill.due_reminders(NOW)
        assert len(due) == 1
        assert "该吃阿司匹林啦" in due[0]["speech"]

    def test_吃过之后不再提醒(self, skill):
        create_sample(skill)
        skill.run("confirm_taken", {}, CTX)
        due = [d for d in skill.due_reminders(NOW) if not d.get("escalate")]
        assert due == []

    def test_隔日服药前天不生效(self, skill):
        create_sample(skill, frequency="every_other_day", times=["08:00"],
                      start_date="2026-09-19")
        tomorrow = NOW + timedelta(days=1)
        due = [d for d in skill.due_reminders(tomorrow) if not d.get("escalate")]
        assert due == []

    def test_漏服一小时以上会升级通知(self, skill):
        create_sample(skill)
        late = datetime(2026, 9, 19, 10, 0)
        escalations = [d for d in skill.due_reminders(late) if d.get("escalate")]
        assert escalations and escalations[0]["overdue_minutes"] == 120

    def test_没到阈值不算漏服(self, skill):
        """50 分钟不算漏服，边界要卡在 60。"""
        create_sample(skill)
        soon = datetime(2026, 9, 19, 8, 50)
        assert [d for d in skill.due_reminders(soon) if d.get("escalate")] == []

    def test_漏服会落库(self, skill):
        """★ 核心：漏服必须写进事件流，否则健康和照顾反馈统计不到。"""
        create_sample(skill)
        rid = skill.executor.store.query(person="elder_01")[0].id
        skill.due_reminders(datetime(2026, 9, 19, 10, 0))

        log = skill.executor.store.get(rid).taken_log
        assert len(log) == 1
        assert log[0]["status"] == "missed"
        assert log[0]["slot"] == "08:00"
        assert log[0]["overdue_minutes"] == 120
        assert log[0]["source"] == "system"

    def test_漏服不重复落库(self, skill):
        """调度器每分钟跑一次，不能每分钟写一条。"""
        create_sample(skill)
        rid = skill.executor.store.query(person="elder_01")[0].id
        for minute in (0, 1, 2, 3):
            skill.due_reminders(datetime(2026, 9, 19, 10, minute))

        assert len(skill.executor.store.get(rid).taken_log) == 1

    def test_只有首次判定才标记newly_missed(self, skill):
        """调度器靠这个字段决定要不要通知家属，不能每轮都通知。"""
        create_sample(skill)
        first = [d for d in skill.due_reminders(datetime(2026, 9, 19, 10, 0))
                 if d.get("escalate")]
        second = [d for d in skill.due_reminders(datetime(2026, 9, 19, 10, 5))
                  if d.get("escalate")]
        assert first[0]["newly_missed"] is True
        assert second[0]["newly_missed"] is False

    def test_漏服后仍会继续提醒(self, skill):
        """漏服不该被当成「已处理」，老人后来吃了也得能补上。

        这是 taken_slots 只认 taken 的原因：如果漏服也算「已服用」，
        老人这一顿就永远不会再被提醒了。
        """
        create_sample(skill, frequency="twice_daily", times=["08:00", "20:00"])
        skill.due_reminders(datetime(2026, 9, 19, 10, 0))

        # 早上那次已判漏服，晚上那次仍应正常提醒
        evening = [d for d in skill.due_reminders(datetime(2026, 9, 19, 20, 0))
                   if not d.get("escalate")]
        assert len(evening) == 1 and evening[0]["slot"] == "20:00"

    def test_漏服后补报以老人说的为准(self, skill):
        """老人被通知后说「我吃了」，记录应该改成 taken，而不是两条并存。"""
        create_sample(skill)
        rid = skill.executor.store.query(person="elder_01")[0].id
        skill.due_reminders(datetime(2026, 9, 19, 10, 0))
        skill.run("confirm_taken", {}, datetime_ctx(2026, 9, 19, 10, 30))

        log = skill.executor.store.get(rid).taken_log
        assert len(log) == 1
        assert log[0]["status"] == "taken"

    def test_漏服记录出现在历史里(self, skill):
        create_sample(skill)
        skill.due_reminders(datetime(2026, 9, 19, 10, 0))
        history = skill.run("query", {"include_history": True}, CTX).data["history"]
        assert history and history[0]["status"] == "missed"

    def test_升级通知是发给子女的不是念给老人的(self, skill):
        """REMIND_ESCALATE 里是「麻烦您提醒一下」，念给老人听不通。"""
        create_sample(skill)
        escalations = [d for d in skill.due_reminders(datetime(2026, 9, 19, 10, 0))
                       if d.get("escalate")]
        assert "speech" not in escalations[0]
        assert "麻烦您" in escalations[0]["notify_text"]


# ======================================================================
# 3.5 服药记录的存储层
# ======================================================================
class TestTakenLogStore:
    """taken_log 的读写规则。这层是健康和照顾反馈的数据来源，要稳。"""

    @pytest.fixture()
    def store(self, tmp_path):
        from skills.medication_reminder.store import Reminder, ReminderStore

        s = ReminderStore(tmp_path / "reminders.json")
        s.add(Reminder(
            id="med_1", person="elder_01", medicine_name="阿司匹林",
            dosage=1, dosage_unit="tablet", frequency="once_daily",
            times=["08:00"], start_date="2026-09-19",
        ))
        return s

    def test_旧数据没有status字段时当作已服用(self, store):
        """兼容升级前的文件：老记录只有 taken_at，不能被误判成漏服。"""
        r = store.get("med_1")
        r.taken_log.append(
            {"date": "2026-09-19", "slot": "08:00",
             "taken_at": "2026-09-19T08:03:00", "source": "voice"}
        )
        store.update(r)

        assert store.get("med_1").taken_slots(date(2026, 9, 19)) == {"08:00"}
        assert store.get("med_1").missed_slots(date(2026, 9, 19)) == set()

    def test_漏服不算已服用(self, store):
        store.log_missed("med_1", date(2026, 9, 19), "08:00", overdue_minutes=90)
        r = store.get("med_1")
        assert r.taken_slots(date(2026, 9, 19)) == set()
        assert r.missed_slots(date(2026, 9, 19)) == {"08:00"}

    def test_logged_slots包含漏服(self, store):
        """调度器靠它判断「是否已判定过」，所以漏服也要算进去。"""
        store.log_missed("med_1", date(2026, 9, 19), "08:00")
        assert store.get("med_1").logged_slots(date(2026, 9, 19)) == {"08:00"}

    def test_补报覆盖漏服(self, store):
        store.log_missed("med_1", date(2026, 9, 19), "08:00")
        store.log_taken("med_1", date(2026, 9, 19), "08:00",
                        taken_at=datetime(2026, 9, 19, 10, 30))
        log = store.get("med_1").taken_log
        assert len(log) == 1
        assert log[0]["status"] == "taken"

    def test_已服用不会被漏服覆盖(self, store):
        """吃过就是吃过：调度器算错了也不能把 taken 改回 missed。"""
        store.log_taken("med_1", date(2026, 9, 19), "08:00")
        store.log_missed("med_1", date(2026, 9, 19), "08:00", overdue_minutes=120)
        log = store.get("med_1").taken_log
        assert len(log) == 1
        assert log[0]["status"] == "taken"

    def test_重复记服用不追加(self, store):
        store.log_taken("med_1", date(2026, 9, 19), "08:00")
        store.log_taken("med_1", date(2026, 9, 19), "08:00")
        assert len(store.get("med_1").taken_log) == 1

    def test_记不存在的提醒返回False(self, store):
        assert store.log_taken("不存在", date(2026, 9, 19), "08:00") is False

    def test_跨天不互相影响(self, store):
        store.log_missed("med_1", date(2026, 9, 19), "08:00")
        assert store.get("med_1").missed_slots(date(2026, 9, 20)) == set()

    def test_落盘后能重新读出来(self, tmp_path):
        from skills.medication_reminder.store import Reminder, ReminderStore

        path = tmp_path / "reminders.json"
        s1 = ReminderStore(path)
        s1.add(Reminder(
            id="med_1", person="elder_01", medicine_name="阿司匹林",
            dosage=1, dosage_unit="tablet", frequency="once_daily",
            times=["08:00"], start_date="2026-09-19",
        ))
        s1.log_missed("med_1", date(2026, 9, 19), "08:00", overdue_minutes=90)

        s2 = ReminderStore(path)
        assert s2.get("med_1").missed_slots(date(2026, 9, 19)) == {"08:00"}


# ======================================================================
# 4. 注册表 / tool 导出
# ======================================================================
class TestRegistry:
    def test_用药提醒已注册(self):
        s = get("medication_reminder")
        assert s is not None
        assert s.display_name == "用药提醒"

    def test_导出五个工具(self):
        tools = skills.export_qwen_tools(["medication_reminder"])
        names = [t["function"]["name"] for t in tools]
        assert names == [
            "medication_reminder_create",
            "medication_reminder_query",
            "medication_reminder_update",
            "medication_reminder_cancel",
            "medication_reminder_confirm_taken",
        ]

    def test_每个工具的schema合法(self):
        for t in skills.export_qwen_tools(["medication_reminder"]):
            fn = t["function"]
            assert fn["description"], f"{fn['name']} 缺少 description"
            params = fn["parameters"]
            assert params["type"] == "object"
            assert "properties" in params
            # 每个属性都要有 description，Qwen 靠这个理解字段
            for field_name, spec in params["properties"].items():
                assert spec.get("description"), f"{fn['name']}.{field_name} 缺少 description"

    def test_create的必填项稳定(self):
        tool = next(
            t for t in skills.export_qwen_tools(["medication_reminder"])
            if t["function"]["name"] == "medication_reminder_create"
        )
        required = set(tool["function"]["parameters"]["required"])
        assert required == {
            "medicine_name", "dosage", "dosage_unit", "frequency", "times"
        }

    def test_反查工具名(self):
        found = skills.find_by_tool_name("medication_reminder_query")
        assert found is not None
        skill_obj, action = found
        assert skill_obj.name == "medication_reminder" and action == "query"

    def test_未知action返回友好提示(self, skill):
        r = skill.run("不存在的action", {}, CTX)
        assert not r.ok
        assert "没听明白" in r.speech
