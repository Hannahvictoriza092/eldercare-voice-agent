"""skill 包入口。

import skills 之后，注册表里就自动装好了所有 skill。

======================================================================
★ 这个文件三个人都不需要改。
======================================================================
它自动扫描本目录下所有子包，凡是导出了模块级 `SKILL` 变量的，
自动注册进注册表。所以新增 skill 只要在自己的文件夹里做事，
不用碰任何公共文件，也就不会有合并冲突。

【队友怎么加自己的 skill】
在你的包（skills/your_skill/）的 __init__.py 里写：

    from .skill import YourSkill
    SKILL = YourSkill()

就这两行，别的什么都不用管。没写 SKILL 的包会被安静跳过，
所以你可以先建空文件夹，不会把系统搞挂。
"""

from pathlib import Path

from common import (
    BaseSkill,
    RiskLevel,
    SkillContext,
    SkillResult,
    all_skills,
    discover,
    export_qwen_tools,
    find_by_tool_name,
    get,
    register,
    skill_index,
    skipped_packages,
    unregister,
)

# 自动发现并注册（扫 skills/ 下的所有子包）
_package_dir = Path(__file__).parent
discover(__name__, _package_dir)

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
    "skipped_packages",
]
