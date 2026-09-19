"""共享层（三个组共同维护）。

分工边界：
    common/   共享契约 —— 三个人一起用，改动前说一声
    skills/   各 skill 自己的实现 —— 各写各的，一般不互相插手

推荐直接从这里导入：
    from common import BaseSkill, SkillResult, SkillContext, RiskLevel
    from common.domain import Person, Incident, MedicationLog, Notification
    from common import timefmt
"""

from .base import (
    BaseSkill,
    RiskLevel,
    SkillContext,
    SkillResult,
    flatten_schema,
)
from .domain import (
    ConfirmLevel,
    Contact,
    Incident,
    IncidentStatus,
    IncidentType,
    MedicationLog,
    MedicationStatus,
    Notification,
    NotifyTarget,
    Person,
    StatusChange,
    Urgency,
)
from .registry import (
    all_skills,
    clear,
    discover,
    export_qwen_tools,
    find_by_tool_name,
    get,
    register,
    skill_index,
    skipped_packages,
    unregister,
)
from . import timefmt

__all__ = [
    # base
    "BaseSkill",
    "SkillResult",
    "SkillContext",
    "RiskLevel",
    "flatten_schema",
    # registry
    "register",
    "unregister",
    "get",
    "all_skills",
    "clear",
    "discover",
    "skipped_packages",
    "skill_index",
    "export_qwen_tools",
    "find_by_tool_name",
    # domain
    "Person",
    "Contact",
    "MedicationLog",
    "MedicationStatus",
    "Incident",
    "IncidentType",
    "IncidentStatus",
    "StatusChange",
    "Notification",
    "NotifyTarget",
    "Urgency",
    "ConfirmLevel",
    # 工具
    "timefmt",
]
