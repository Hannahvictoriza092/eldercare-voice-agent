"""呼救动作的参数模型。紧急呼救不要求先补齐原因或位置。"""

from pydantic import BaseModel, Field


class TriggerParams(BaseModel):
    """老人主动求助或设备检测到紧急情况时立即创建呼救。"""

    reason: str | None = Field(default=None, description="老人描述的紧急情况，如摔倒、胸闷、呼吸困难；没听清也要立即呼救。")
    location: str | None = Field(default=None, description="事发地点或设备提供的位置；未知时留空，不要编造地址。")
    current_condition: str | None = Field(default=None, description="老人当前状态的原话，如意识清楚、无法起身；未知时留空。")


class CheckProgressParams(BaseModel):
    """查询本人最近一次呼救，或指定事件的救助进度。"""

    incident_id: str | None = Field(default=None, description="要查询的呼救事件 ID；老人没说时留空，自动查本人最近一次。")


class CancelParams(BaseModel):
    """老人明确表示误触并再次确认后，取消尚未结束的呼救。"""

    incident_id: str | None = Field(default=None, description="要取消的呼救事件 ID；未提供时选择本人最近一条未结束的呼救。")
    reason: str | None = Field(default=None, description="取消原因，如按错了、误报；未知时留空。")
    confirmed: bool = Field(default=False, description="老人已经明确确认取消时才填 true；第一次说按错了时填 false。")


class ConfirmSafeParams(BaseModel):
    """老人确认已经安全；只用于已经有活动呼救的情况。"""

    incident_id: str | None = Field(default=None, description="对应的呼救事件 ID；未提供时选择本人最近一条未结束的呼救。")
    confirmed: bool = Field(default=False, description="老人明确确认自己安全并要结束呼救时填 true，否则填 false。")
