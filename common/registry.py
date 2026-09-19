"""skill 注册表。

对应规划图里的两步：
  「程序把可用 skill 告诉给 qwen」  -> skill_index()
  「程序查注册表」                  -> get() / all_skills()

【自动发现】
技能包不需要有人手动登记。skills/__init__.py 会扫描子目录，
凡是导出了模块级 `SKILL` 对象的包，都会被自动注册。

为什么这么设计：手动登记意味着三个人都要改同一个文件（skills/__init__.py），
每次合并必然冲突。改成自动发现后，那个文件谁都不用动了——
你只需要在自己的文件夹里定义 SKILL，别人完全不用配合。
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Any

from .base import BaseSkill

_REGISTRY: dict[str, BaseSkill] = {}
_SKIPPED: list[str] = []  # 扫到了但没导出 SKILL 的包（可能是工具目录，也可能是忘了写）


def register(skill: BaseSkill) -> BaseSkill:
    """把一个 skill 实例登记进注册表。重名会直接报错，避免静默覆盖。"""
    if not skill.name:
        raise ValueError(f"{type(skill).__name__} 没有定义 name")
    if skill.name in _REGISTRY:
        raise ValueError(f"skill 重名：{skill.name}")
    if not skill.ACTIONS:
        raise ValueError(f"{skill.name} 的 ACTIONS 是空的，至少要实现一个 action")
    _REGISTRY[skill.name] = skill
    return skill


def unregister(name: str) -> None:
    _REGISTRY.pop(name, None)


def get(name: str) -> BaseSkill | None:
    return _REGISTRY.get(name)


def all_skills() -> list[BaseSkill]:
    return list(_REGISTRY.values())


def clear() -> None:
    """清空注册表。主要给测试用，避免用例之间互相污染。"""
    _REGISTRY.clear()
    _SKIPPED.clear()


def skipped_packages() -> list[str]:
    """列出了哪些包被跳过（没导出 SKILL）。

    排查用：「我明明写了 skill 怎么没注册」——十有八九是忘了定义 SKILL。
    """
    return list(_SKIPPED)


# ----------------------------------------------------------------------
# 自动发现
# ----------------------------------------------------------------------
def discover(package_name: str, package_dir: Path) -> list[str]:
    """扫描包目录，把每个导出了 `SKILL` 的子包注册进来。

    约定（写进 docs/接口约定.md 了）：
        每个 skill 包必须在 __init__.py 里定义模块级变量 SKILL，
        值是一个 skill 实例。

    例：
        # skills/emergency_call/__init__.py
        from .skill import EmergencyCallSkill
        SKILL = EmergencyCallSkill()

    没有 SKILL 的包会被安静跳过，这样队友还没开工时不会把整个系统搞挂。
    """
    found: list[str] = []
    for info in sorted(pkgutil.iter_modules([str(package_dir)]), key=lambda i: i.name):
        if not info.ispkg or info.name.startswith("_"):
            continue

        module = importlib.import_module(f"{package_name}.{info.name}")
        skill = getattr(module, "SKILL", None)

        if skill is None:
            _SKIPPED.append(info.name)
            continue
        if not isinstance(skill, BaseSkill):
            raise TypeError(
                f"{package_name}.{info.name} 的 SKILL 不是 BaseSkill 实例，"
                f"而是 {type(skill).__name__}"
            )

        register(skill)
        found.append(skill.name)
    return found



# ----------------------------------------------------------------------
# 给 Qwen 用的两种输出
# ----------------------------------------------------------------------
def skill_index() -> list[dict[str, str]]:
    """精简的 skill 清单，适合塞进 system prompt 让 Qwen 先做粗选。

    这一步是低成本的「选哪个 skill」，选完再把对应的详细 tool schema 给它。
    """
    return [
        {
            "name": s.name,
            "display_name": s.display_name,
            "description": s.description,
            "risk_level": s.risk_level.value,
        }
        for s in all_skills()
    ]


def export_qwen_tools(skill_names: list[str] | None = None) -> list[dict[str, Any]]:
    """导出 function calling 的 tools 数组。

    skill_names 为空时导出全部；传了列表就只导出指定的 skill，
    方便做「二阶段调用」——先让 Qwen 选 skill，再只把那个 skill 的工具给它。
    """
    skills = all_skills() if not skill_names else [get(n) for n in skill_names]
    tools: list[dict[str, Any]] = []
    for s in skills:
        if s is None:
            continue
        tools.extend(s.export_tools())
    return tools


def find_by_tool_name(tool_name: str) -> tuple[BaseSkill, str] | None:
    """反查：Qwen 返回了 medication_reminder_create，我要知道是哪个 skill 的哪个 action。"""
    for s in all_skills():
        for action in s.ACTIONS:
            if s.tool_name(action) == tool_name:
                return s, action
    return None
