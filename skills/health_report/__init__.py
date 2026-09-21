"""健康和照顾反馈 skill 包。

★ 自动发现的入口：模块级变量 `SKILL`。
   skills/__init__.py 会扫描每个子包，凡是导出 SKILL 的就自动注册。
   所以新增 skill 不需要改任何公共文件。

依赖说明：本 skill 消费「用药提醒」和「呼救」产出的数据
（common/domain.py 里的 MedicationLog / Incident），属于下游。
数据通过 EventStore 接口读取（见 executor.py），不 import 其他 skill 的私有模块。
"""

from .executor import EventStore, HealthReportExecutor, InMemoryEventStore
from .schema import (
    GenerateWeeklyParams,
    QueryArchiveParams,
    QuerySummaryParams,
    SendReportParams,
)
from .skill import HealthReportSkill
from .store import HealthArchive, HealthArchiveStore, WeeklySnapshot

# ↓ 这一行就是注册开关。注册表靠它识别这个包是个 skill。
SKILL = HealthReportSkill()

__all__ = [
    "SKILL",
    "HealthReportSkill",
    "HealthReportExecutor",
    "EventStore",
    "InMemoryEventStore",
    "HealthArchiveStore",
    "HealthArchive",
    "WeeklySnapshot",
    "GenerateWeeklyParams",
    "SendReportParams",
    "QueryArchiveParams",
    "QuerySummaryParams",
]
