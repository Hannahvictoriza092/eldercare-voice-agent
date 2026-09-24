"""跨 skill 共享的数据实体。

======================================================================
★ 这个文件是三个人一起用的，改动前在群里说一声比较稳。
======================================================================

【为什么要有这一层】
三个 skill 不是平行的，是有依赖的：

    用药提醒 ──产出──┐
                     ├──> 服药记录 / 漏服事件 ──> 健康反馈（消费）
    呼救     ──产出──┘        呼救事件        ──> 健康反馈（消费）
                     └──────────────────────────> 通知子女/医院

健康和照顾反馈要「每周记录老人行为」，数据源就是另外两个 skill 产出的东西。
如果各自定义自己的数据结构，健康和照顾反馈最后肯定读不到数据，
或者得 import 其他 skill 的私有 store 来硬读——那是耦合，改一处坏三处。

所以：实体字段名定下来之后，要改的话先在群里说一声。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ======================================================================
# 一、老人身份
# ======================================================================
class Contact(BaseModel):
    """紧急联系人。呼救要用，健康和照顾反馈发周报也要用。"""

    name: str
    phone: str
    relation: str = "家属"          # 儿子 / 女儿 / 社区医生
    is_primary: bool = False        # 首要联系人，呼救时第一个打给他


class Person(BaseModel):
    """一位老人。

    ★ 定稿：ID 用稳定的字符串标识（如 elder_01），不用姓名当 ID——
    重名、改名都会出问题。三个 skill 的记录统一用 person_id 引到这儿。
    """

    person_id: str
    name: str                                   # 话术里的称呼，如「张奶奶」
    birth_year: int | None = None
    gender: Literal["male", "female", "unknown"] = "unknown"

    # --- 健康信息：健康和照顾反馈这边维护 ---
    conditions: list[str] = Field(default_factory=list)      # 基础病
    allergies: list[str] = Field(default_factory=list)       # 过敏史

    # --- 联络信息：呼救这边维护 ---
    emergency_contacts: list[Contact] = Field(default_factory=list)

    # --- 设备绑定：Agent 层填进来 ---
    device_id: str | None = None
    voiceprint_id: str | None = None      # 声纹 ID，没做声纹就留空

    # 呼救要报位置；留空时从设备实时取。
    address: str | None = None

    # 家属/监护人（给用药提醒、呼救通知用）。
    guardian_id: str | None = None


# ======================================================================
# 二、服药记录（用药提醒产出，健康反馈消费）
# ======================================================================
class MedicationStatus(str, Enum):
    TAKEN = "taken"          # 已服用
    MISSED = "missed"        # 到点没吃（系统判定）
    SKIPPED = "skipped"      # 老人主动说跳过
    PENDING = "pending"      # 还没到点


class MedicationLog(BaseModel):
    """一次服药的完整记录。

    ★ 关键设计：每一「次」都落库一条，不靠实时计算。

    为什么要这样：如果漏服是实时算出来的（现在时间 - 计划时间 > 60 分钟），
    那么健康和照顾反馈想统计「上周漏服 3 次」时就没法从数据里读出来，
    只能自己重新算一遍，而且「老人当时是不是生病了、故意不吃」这类信息会丢。

    ✅ 已完成：用药提醒的 executor.get_due_reminders() 在超过 60 分钟
    （MISSED_AFTER_MIN）时会往 store 的 taken_log 里落一条 status=missed 的记录，
    并带 overdue_minutes。老人事后补报「我吃了」会把那条改成 taken。
    ⚠️ 待办：taken_log 目前是 Reminder 的嵌套字段，还没有独立的共享事件流存储，
    健康和照顾反馈要读的话仍需先和用药提醒这边定好读取方式。
    """

    id: str
    person_id: str
    reminder_id: str | None = None      # 关联的提醒配置，按需服用可能为空

    medicine_name: str
    dosage: float
    dosage_unit: str

    scheduled_at: datetime              # 原定服用时间
    taken_at: datetime | None = None    # 实际服用时间
    status: MedicationStatus = MedicationStatus.PENDING

    # 语音上报 / 子女代报 / 设备上报
    source: Literal["voice", "family", "device", "system"] = "voice"
    note: str | None = None


# ======================================================================
# 三、异常事件（呼救 + 用药提醒都产出，健康反馈消费）
# ======================================================================
class IncidentType(str, Enum):
    SOS = "sos"                                   # 老人主动呼救
    FALL_DETECTED = "fall_detected"               # 跌倒检测
    MEDICATION_MISSED = "medication_missed"       # 漏服（用药提醒产出）
    HEALTH_ABNORMAL = "health_abnormal"           # 健康指标异常


class IncidentStatus(str, Enum):
    """事件状态机。

    ★ 呼救这边注意：「救助来了吗」这个功能查的就是这个状态 + status_history，
    不需要自己另外造一套进度表。状态推进时往 status_history 追加一条即可。
    """

    OPEN = "open"                 # 已发起，还没人响应
    ACKED = "acked"               # 已接单（社区/家属确认收到）
    EN_ROUTE = "en_route"         # 在途（救护车已出发）
    ARRIVED = "arrived"           # 已到达现场
    RESOLVED = "resolved"         # 已解决
    CANCELLED = "cancelled"       # 误报/老人自己取消
    FAILED = "failed"             # 联系不上任何人


class StatusChange(BaseModel):
    """状态变更的一步，用于给老人播报进度。"""

    status: IncidentStatus
    at: datetime
    note: str = ""                        # 「社区王医生已接单」
    eta_minutes: int | None = None        # 预计还有多久到，给「还有 10 分钟」用


class Incident(BaseModel):
    id: str
    person_id: str
    type: IncidentType
    severity: Literal["low", "medium", "high", "critical"] = "high"

    occurred_at: datetime
    status: IncidentStatus = IncidentStatus.OPEN
    status_history: list[StatusChange] = Field(default_factory=list)

    resolved_at: datetime | None = None
    location: str | None = None           # 事发地点

    # 实际已通知过的对象。由呼救 skill 在生成通知时维护，
    # 具体顺序（家属/社区/120）由出站层的发送策略决定。
    notified_targets: list[str] = Field(default_factory=list)

    detail: dict[str, Any] = Field(default_factory=dict)

    def progress_cn(self) -> str:
        """把状态翻译成能念给老人听的一句话。

        TODO-呼救: 这段是打样的，按实际流程改写就好，语气要让人安心。
        """
        latest = self.status_history[-1] if self.status_history else None
        mapping = {
            IncidentStatus.OPEN: "您的呼救已经发出去了，正在联系救助的人",
            IncidentStatus.ACKED: "救助的人已经收到消息了",
            IncidentStatus.EN_ROUTE: "救助的人已经在来的路上了",
            IncidentStatus.ARRIVED: "救助的人已经到您那儿了",
            IncidentStatus.RESOLVED: "这件事已经处理好了",
            IncidentStatus.CANCELLED: "这次呼救已经取消了",
            IncidentStatus.FAILED: "我暂时联系不上人，正在继续试",
        }
        text = mapping.get(self.status, "正在处理中")
        if latest and latest.eta_minutes:
            from .timefmt import in_future_cn

            text += f"，{in_future_cn(latest.eta_minutes)}"
        return text + "，您别着急。"


# ======================================================================
# 四、通知（三个组都要往外发消息，别各写一套）
# ======================================================================
class NotifyTarget(str, Enum):
    FAMILY = "family"           # 子女
    HOSPITAL = "hospital"       # 医院 / 家庭医生
    COMMUNITY = "community"     # 社区 / 居委会
    EMERGENCY = "emergency"     # 120 / 110


class Urgency(str, Enum):
    """紧急程度决定发送策略：周报可以攒着批量发，呼救必须立刻发+重试。"""

    NORMAL = "normal"           # 周报摘要，允许延迟
    URGENT = "urgent"           # 漏服提醒，尽快发
    CRITICAL = "critical"       # 呼救，必须送达并重试到确认


class Notification(BaseModel):
    """一条待发送的通知。

    ★ 约定：skill 只【产出】Notification 对象，不负责真正发送。
    发送、重试、送达确认由出站层统一做。
    这样呼救这边不用关心到底走短信还是微信。
    """

    id: str
    person_id: str
    targets: list[NotifyTarget]
    urgency: Urgency = Urgency.NORMAL
    title: str
    body: str
    created_at: datetime

    related_incident_id: str | None = None
    sent_at: datetime | None = None
    delivered: bool = False


# ======================================================================
# 五、SkillResult 的扩展（见 docs/接口约定.md 的说明）
# ======================================================================
class ConfirmLevel(str, Enum):
    """执行前需要多强的确认。替代散在 data 字典里的 require_confirm_back。

    ★ 已定稿：写进 SkillResult.confirm_level 一等字段。
    Agent 层据此决定要不要让老人复述、要不要通知家属。
    """

    NONE = "none"               # 直接执行，如纯查询
    REPEAT_BACK = "repeat"      # 让老人复述一遍再执行，如新增药
    GUARDIAN = "guardian"       # 必须家属确认，如停药
