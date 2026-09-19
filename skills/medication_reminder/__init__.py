"""用药提醒 skill 包。

★ 自动发现的入口：模块级变量 `SKILL`。
   skills/__init__.py 会扫描每个子包，凡是导出 SKILL 的就自动注册。
   所以新增 skill 不需要改任何公共文件。
"""

from .executor import MedicationExecutor
from .schema import (
    CancelReminderParams,
    ConfirmTakenParams,
    CreateReminderParams,
    QueryScheduleParams,
    UpdateReminderParams,
)
from .skill import MedicationReminderSkill
from .store import Reminder, ReminderStore

# ↓ 这一行就是注册开关。注册表靠它识别这个包是个 skill。
SKILL = MedicationReminderSkill()

__all__ = [
    "SKILL",
    "MedicationReminderSkill",
    "MedicationExecutor",
    "ReminderStore",
    "Reminder",
    "CreateReminderParams",
    "QueryScheduleParams",
    "UpdateReminderParams",
    "CancelReminderParams",
    "ConfirmTakenParams",
]
