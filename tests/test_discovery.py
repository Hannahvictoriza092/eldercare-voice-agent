"""自动发现机制的测试。

这一组测试防的是「我明明写了 skill 怎么没注册」这类问题。
起因：为了不让三个人共改 skills/__init__.py，注册改成了自动扫描，
所以扫描逻辑本身必须可靠，否则队友会莫名其妙注册不上。
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest
from pydantic import BaseModel

import skills
from common import registry
from common.base import BaseSkill, RiskLevel, SkillResult


@pytest.fixture(autouse=True)
def _restore_registry():
    """每个用例前后都恢复注册表。

    这些用例会 clear() 掉注册表来测扫描逻辑。如果不恢复，
    后面跑的 test_medication_reminder.py 就查不到任何 skill 了
    （这个坑真踩过：本文件按字母序先跑，导致另一个文件 6 个用例失败）。
    """
    saved = dict(registry._REGISTRY)
    saved_skipped = list(registry._SKIPPED)
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)
    registry._SKIPPED[:] = saved_skipped


class TestDiscovery:
    def test_用药提醒被自动发现(self):
        """medication_reminder 没在任何地方手动登记，靠自动扫描注册。"""
        assert skills.get("medication_reminder") is not None

    def test_没写SKILL的包被安静跳过(self):
        """队友的占位文件夹不该导致整个系统起不来。"""
        skipped = skills.skipped_packages()
        # 这两个包目前是空占位，应该被跳过而不是报错
        assert "emergency_call" in skipped
        assert "health_report" in skipped

    def test_跳过不影响已注册的skill(self):
        assert "medication_reminder" not in skills.skipped_packages()

    def test_重新扫描结果一致(self):
        """discover 应该幂等：清空再扫，还是同一个结果。"""
        registry.clear()
        assert skills.all_skills() == []

        found = registry.discover("skills", Path(skills.__file__).parent)
        assert found == ["medication_reminder"]
        assert [s.name for s in skills.all_skills()] == ["medication_reminder"]

    def test_导出了非BaseSkill的SKILL会报错(self, tmp_path, monkeypatch):
        """写错入口时要给清楚的报错，而不是静默不注册。"""
        fake = types.ModuleType("skills.fake_skill")
        fake.SKILL = "我不是一个 skill 实例"

        monkeypatch.setattr(registry.importlib, "import_module", lambda name: fake)
        monkeypatch.setattr(
            registry.pkgutil,
            "iter_modules",
            lambda paths: [types.SimpleNamespace(name="fake_skill", ispkg=True)],
        )

        registry.clear()
        with pytest.raises(TypeError) as e:
            registry.discover("skills", tmp_path)
        assert "BaseSkill" in str(e.value)


class TestRegisterValidation:
    """注册时的校验，防止写半成品就以为完工了。"""

    def test_没有name会报错(self):
        class NoName(BaseSkill):
            ACTIONS = {"x": BaseModel}

            def execute(self, action, params, ctx):
                return SkillResult(ok=True, skill="x")

        with pytest.raises(ValueError) as e:
            registry.register(NoName())
        assert "name" in str(e.value)

    def test_没有ACTIONS会报错(self):
        class NoActions(BaseSkill):
            name = "no_actions"

            def execute(self, action, params, ctx):
                return SkillResult(ok=True, skill="no_actions")

        with pytest.raises(ValueError) as e:
            registry.register(NoActions())
        assert "ACTIONS" in str(e.value)

    def test_重名会报错(self):
        class Dup(BaseSkill):
            name = "medication_reminder"      # 和已管理的同一个名字
            ACTIONS = {"x": BaseModel}

            def execute(self, action, params, ctx):
                return SkillResult(ok=True, skill="dup")

        with pytest.raises(ValueError) as e:
            registry.register(Dup())
        assert "重名" in str(e.value)
