"""skill 包入口。

import skills 之后，注册表里就装好了所有 skill。
队友新增 skill 时，只要在这里加两行：import + register。
"""

from common import (
    BaseSkill,
    RiskLevel,
    SkillContext,
    SkillResult,
    all_skills,
    export_qwen_tools,
    find_by_tool_name,
    get,
    register,
    skill_index,
    unregister,
)

from .medication_reminder import MedicationReminderSkill

# ======================================================================
# 在这里注册所有 skill
# 顺序无所谓，注册表按 name 索引。每人只加自己那一块，不要重排别人的行，
# 否则每次合并都会冲突。
# ======================================================================

# --- 用药提醒（负责人：你） ---
register(MedicationReminderSkill())

# --- 呼救（负责人：队友 A） ---
# 建好 skills/emergency_call/ 下的文件后，打开下面两行：
# from .emergency_call import EmergencyCallSkill
# register(EmergencyCallSkill())

# --- 健康和照顾反馈（负责人：队友 B） ---
# 注意：健康反馈依赖前两个 skill 产出的数据，建议最后接入
# from .health_report import HealthReportSkill
# register(HealthReportSkill())

__all__ = [
    "BaseSkill",
    "RiskLevel",
    "SkillContext",
    "SkillResult",
    "register",
    "unregister",
    "get",
    "all_skills",
    "skill_index",
    "export_qwen_tools",
    "find_by_tool_name",
    "MedicationReminderSkill",
]
