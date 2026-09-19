"""skill 注册表。

对应规划图里的两步：
  「程序把可用 skill 告诉给 qwen」  -> skill_index()
  「程序查注册表」                  -> get() / all_skills()

新增一个 skill 只需要在自己的包里写一个类，然后在 skills/__init__.py 里 register 一次。
"""

from __future__ import annotations

from typing import Any

from .base import BaseSkill

_REGISTRY: dict[str, BaseSkill] = {}


def register(skill: BaseSkill) -> BaseSkill:
    """把一个 skill 实例登记进注册表。重名会直接报错，避免静默覆盖。"""
    if not skill.name:
        raise ValueError(f"{type(skill).__name__} 没有定义 name")
    if skill.name in _REGISTRY:
        raise ValueError(f"skill 重名：{skill.name}")
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
