"""对话确认状态：确认只绑定程序保存的具体操作，不信任模型的确认标志。"""
from dataclasses import dataclass
from datetime import datetime
import re

YES = {"对", "对的", "是", "是的", "是这样", "没错", "确认", "确认吧", "好的", "好", "可以", "嗯", "嗯嗯"}
NO = {"算了", "算了吧", "取消", "不要了", "不需要了", "先不弄了", "不用了"}


def short_reply(text: str) -> str:
    # 不删除句中标点，避免把“对，不是八点”误当成肯定答复。
    return text.strip().rstrip("。！!，,？? ").strip()


def urgent_request(text: str) -> bool:
    return bool(re.fullmatch(r"(?:救命[啊呀]?|快救我)(?:[，,！!。\s]+.*)?", text.strip()))


@dataclass
class PendingAction:
    name: str
    arguments: dict
    created_at: datetime
    question: str

    def expired(self, now: datetime) -> bool:
        return (now - self.created_at).total_seconds() > 600 or now < self.created_at
