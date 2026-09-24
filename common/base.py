"""skill 统一元数据约定。

【这一层为什么存在】
项目规划里说「先建造一个 skill 库，要有 skill 名称、skill 需要的参数」。
这个文件就是那个「库」的格式定义——三个 skill（用药提醒 / 呼救 / 健康和照顾反馈）
都长成同一个样子，注册表和 Qwen 的 tool schema 才拼得起来。

【怎么用】
如果是写「呼救」或「健康和照顾反馈」，只需要：
  1. 继承 BaseSkill
  2. 用 Pydantic 定义每个 action 的参数模型，填进 ACTIONS
  3. 实现 execute()
其余（注册、导出 Qwen schema、参数校验）全部复用这里，不用重复写。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, ValidationError

from .domain import ConfirmLevel, Notification


class RiskLevel(str, Enum):
    """风险等级。Agent 层据此决定要不要二次确认、要不要通知子女。

    这是「意图风险判断」那一步的输入。
    """

    LOW = "low"        # 纯查询，填错没有副作用
    MEDIUM = "medium"  # 有副作用但可撤销，例如取消提醒
    HIGH = "high"      # 涉及人身安全 / 不可撤销，必须让老人复述确认


class SkillContext(BaseModel):
    """一次调用的上下文，由 Agent 层填好传进来，skill 不自己去猜。"""

    speaker_id: str = "unknown"          # 当前说话的老人 ID
    speaker_name: str = "老人"            # 念话术时用
    now: datetime = Field(default_factory=datetime.now)  # 可注入，方便写测试
    session_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    def person(self, override: str | None = None) -> str:
        """多老人场景：参数里指定了就用指定的，没指定就用当前说话人。"""
        return override or self.speaker_id


class SkillResult(BaseModel):
    """所有 skill 的统一返回结构。

    上层 Agent 只认这个结构，不需要知道具体是哪个 skill，
    也不需要写 if skill == "medication_reminder" 这种分支。
    """

    ok: bool
    skill: str
    action: str | None = None
    speech: str = ""                       # 要念给老人听的话（TTS 直接播这句）
    data: dict[str, Any] = Field(default_factory=dict)  # 结构化结果，供日志/前端用
    need_followup: bool = False            # 参数不全，需要 Qwen 追问老人
    followup_question: str = ""            # 追问话术
    error: str | None = None
    # 待发送的通知。skill 只产出对象，真正的发送、重试、送达确认
    # 由上层出站层统一做。三个 skill 都往这里放，出站层只认这一个字段，
    # 不用再猜藏在 data 里的哪个 key（require_confirm_back / notify_family 那种）。
    notifications: list[Notification] = Field(default_factory=list)
    # 执行前需要多强的确认。Agent 层据此决定要不要让老人复述、要不要通知家属。
    confirm_level: ConfirmLevel = ConfirmLevel.NONE


ParamsT = TypeVar("ParamsT", bound=BaseModel)


def flatten_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """把 Pydantic 生成的 $defs / allOf 引用展平成最朴素的一层结构。

    为什么要做这件事：
    Pydantic 会把枚举字段输出成 {"allOf": [{"$ref": "#/$defs/DosageUnit"}], "description": ...}，
    也就是两层嵌套引用。OpenAI 风格的 function calling 各家实现对这个的支持参差不齐，
     DashScope 上实测偶发枚举读不全。展平之后只剩 {type, enum, description}，
     Qwen 填参准确率明显更稳。
    """
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [resolve(x) for x in node]
        if not isinstance(node, dict):
            return node

        # {"$ref": "#/$defs/X"} -> 把 X 的定义内联进来
        if set(node) == {"$ref"}:
            name = node["$ref"].rsplit("/", 1)[-1]
            return {k: v for k, v in resolve(defs.get(name, {})).items() if k != "title"}

        node = {k: resolve(v) for k, v in node.items()}

        # {"allOf": [单个], "description": ...} -> 合并成一层
        if "allOf" in node and len(node["allOf"]) == 1:
            merged = dict(node["allOf"][0])
            merged.update({k: v for k, v in node.items() if k != "allOf"})
            return merged

        return node

    result = resolve(schema)
    result.pop("title", None)
    return result


class BaseSkill(ABC, Generic[ParamsT]):
    """所有 skill 的基类。

    子类需要覆盖：name / display_name / description / ACTIONS / execute
    可选覆盖：risk_level / action_description
    """

    # --- 元数据：会进注册表，也会进 Qwen 的 prompt ---
    name: str = ""              # 英文唯一标识，例如 medication_reminder
    display_name: str = ""      # 中文名，例如 用药提醒
    description: str = ""       # 给 Qwen 看的能力描述，写清楚「什么时候该用我」
    risk_level: RiskLevel = RiskLevel.LOW

    # --- action 名 -> 参数模型 ---
    # 例如 {"create": CreateReminderParams, "query": QueryScheduleParams}
    ACTIONS: dict[str, type[BaseModel]] = {}

    # ------------------------------------------------------------------
    # 导出给 Qwen
    # ------------------------------------------------------------------
    def tool_name(self, action: str) -> str:
        """工具名。用 skill_action 的形式，避免不同 skill 的 action 撞名。"""
        return f"{self.name}_{action}"

    def action_description(self, action: str) -> str:
        """给 Qwen 看：什么话术该触发这个 action。"""
        return f"{self.display_name}：{action}"

    def export_tools(self) -> list[dict[str, Any]]:
        """导出 OpenAI/Qwen function calling 格式的 tools 定义。

        注意一个小设计：一个 skill 会导出成【多个】tool，
        而不是「一个 tool + 一个 action 参数」。
        原因是实测下来 Qwen 在多选一的大参数模型里容易漏填字段，
        拆成独立 tool 后 required 字段稳定，填参准确率明显更高。
        但仍然保持「一个 skill」的粒度，符合规划里「qwen 选择一个 skill」。
        """
        tools: list[dict[str, Any]] = []
        for action, model in self.ACTIONS.items():
            schema = flatten_schema(model.model_json_schema())
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": self.tool_name(action),
                        "description": self.action_description(action),
                        "parameters": schema,
                    },
                }
            )
        return tools

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------
    @abstractmethod
    def execute(self, action: str, params: BaseModel, ctx: SkillContext) -> SkillResult:
        """执行某个 action。参数已经过 Pydantic 校验，类型一定是对的。"""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 统一出口：带异常兜底，保证 Agent 层永远拿到 SkillResult 而不是异常
    # ------------------------------------------------------------------
    def run(
        self,
        action: str,
        raw_params: dict[str, Any] | BaseModel,
        ctx: SkillContext | None = None,
    ) -> SkillResult:
        ctx = ctx or SkillContext()
        model = self.ACTIONS.get(action)
        if model is None:
            return SkillResult(
                ok=False,
                skill=self.name,
                action=action,
                speech="抱歉，我没听明白您要做哪件事。",
                error=f"未知 action：{action}，可用：{list(self.ACTIONS)}",
            )

        # 第 1 步：参数校验（对应规划里的「程序检查填得对不对」）
        try:
            params = raw_params if isinstance(raw_params, BaseModel) else model.model_validate(raw_params)
        except Exception as exc:  # noqa: BLE001 - 校验失败要转成可追问的话术
            # 把出错的字段名挖出来交给 followup_for。
            # 只把 str(exc) 丢过去是不够的：Pydantic 的报错文本里会回显 input_value，
            # 里面含有其它字段的字面量，按关键词猜会猜错（踩过一次）。
            field_name = ""
            if isinstance(exc, ValidationError) and exc.errors():
                loc = exc.errors()[0].get("loc") or ()
                if loc:
                    field_name = str(loc[0])
            return SkillResult(
                ok=False,
                skill=self.name,
                action=action,
                speech="有个信息我还没听清，再问您一下。",
                need_followup=True,
                followup_question=self.followup_for(action, exc, field_name),
                error=str(exc),
            )

        # 第 2 步：真正执行
        try:
            return self.execute(action, params, ctx)
        except Exception as exc:  # noqa: BLE001 - 兜底，别把异常抛给 Agent
            return SkillResult(
                ok=False,
                skill=self.name,
                action=action,
                speech="系统出了点小问题，我马上叫人来帮您。",
                error=f"{type(exc).__name__}: {exc}",
            )

    def followup_for(self, action: str, exc: Exception, field_name: str = "") -> str:
        """校验失败时，生成一句能让老人听懂、也能喂回给 Qwen 的追问。

        field_name 是 Pydantic 报出的出错字段名；跨字段校验（model_validator）
        的 loc 是空的，这种情况下 field_name 为空串，需要看具体是哪个 skill 来决定。
        各 skill 覆盖这个方法，给出符合自己业务的话术。
        """
        return f"请问{self.display_name}还需要补充哪些信息呢？"
