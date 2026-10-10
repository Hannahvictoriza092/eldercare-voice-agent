"""模拟 Qwen —— 演示用的大模型替身。

【为什么需要它】
组长说语音模型还在做实验，可以先模拟语音输入。同理，云端 Qwen 服务目前还没在
集群上跑起来（模型文件已经传上去了，环境和服务待装），所以这里先用一套
【规则版意图识别】顶替 Qwen 的 function calling。

【它和真 Qwen 的关系（重要）】
输出格式刻意和真 Qwen 对齐：tool_calls 里的 name + arguments。
所以以后只要把 parse() 换成「调 OpenAI 兼容接口」，下游的
「注册表查询 → 参数校验 → 执行 → 回话」一行都不用改。
UI 上会明确标注「模拟 Qwen」，不会让观众误以为这就是真模型。

【它演示了什么】
- 意图识别：一句话该不该调工具、调哪个 tool
- 填参：从口语里抽取药名/剂量/频次/时间/接收方
- 闲聊不调工具：不属于任何 skill 范围时直接回应
- 故意留错：参数不全时（例如只说"提醒我吃药"）交给程序层的校验去追问，
  这正是「程序检查填得对不对」那一步的价值。
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any


# ======================================================================
# 一、返回结构：与真 Qwen 的 tool_call 对齐
# ======================================================================
@dataclass
class Decision:
    """模拟 Qwen 的一次判断结果。

    对应真 Qwen 返回的 message.tool_calls[0]：
        tool_name  <- function.name
        arguments  <- json.loads(function.arguments)

    不调工具时（闲聊）tool_name 为 None，用 reply 作为直接回应。
    """

    tool_name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    reason: str = ""     # 给演示看的「为什么这么判断」
    reply: str = ""      # 不调工具时的闲聊回应
    hit: str = ""        # 命中的关键词 / 规则，展示判断依据


# ======================================================================
# 二、词典与基础工具
# ======================================================================
_CN_NUM = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# 数字记号：阿拉伯数字或中文数字（支持 八 / 十二 / 二十三）
_NUM_TOKEN = r"(?:\d{1,2}|[一二两三四五六七八九十]{1,3})"

# 演示常见的药名（命中即取，长的优先）
KNOWN_MEDICINES = [
    "阿司匹林", "二甲双胍", "硝苯地平", "氨氯地平", "阿托伐他汀", "瑞舒伐他汀",
    "氯吡格雷", "美托洛尔", "缬沙坦", "厄贝沙坦", "格列美脲", "阿卡波糖",
    "复方丹参滴丸", "速效救心丸", "布洛芬", "感冒灵", "止咳糖浆",
    "钙片", "维生素", "降压药", "降糖药", "降脂药", "他汀", "胰岛素", "胃药",
]

# 剂量单位 -> skill 里的枚举值
_UNIT_MAP = {
    "片": "tablet", "粒": "capsule", "胶囊": "capsule", "袋": "bag",
    "毫升": "ml", "ml": "ml", "毫克": "mg", "mg": "mg", "克": "g",
    "滴": "drop", "喷": "puff", "支": "unit", "贴": "patch",
}

_CHITCHAT_REPLIES = [
    "张奶奶早上好呀，今天天气不错，记得多穿件衣服。",
    "好嘞，我记着呢。您还有别的事尽管说。",
    "嗯，我听着呢，您慢慢说。",
    "您要是觉得哪儿不舒服，随时叫我。",
]


def _cn2int(token: str) -> int | None:
    """把阿拉伯数字或中文数字转成整数。转不出来返回 None。"""
    token = (token or "").strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    if all(ch in _CN_NUM for ch in token):
        if "十" in token:
            left, _, right = token.partition("十")
            tens = _CN_NUM[left] if left else 1
            ones = _CN_NUM[right] if right else 0
            return tens * 10 + ones
        if len(token) == 1:
            return _CN_NUM[token]
    return None


# ----------------------------------------------------------------------
# 抽取器：药名 / 剂量 / 频次 / 时间 / 时机 / 接收方
# ----------------------------------------------------------------------
def extract_medicine(text: str) -> str | None:
    """先查已知药名（长的优先），再退化到「提醒我吃X」这类模式。"""
    for name in sorted(KNOWN_MEDICINES, key=len, reverse=True):
        if name in text:
            return name
    m = re.search(r"(?:提醒我吃|吃|服用|停用|停)\s*([\u4e00-\u9fa5]{2,6}?)(?:片|粒|胶囊|药|滴丸)", text)
    if m:
        return m.group(1)
    return None


def extract_dosage(text: str) -> tuple[float | None, str | None]:
    """抽取「几片/几粒」，返回 (数量, 单位枚举值)。「半片」-> 0.5。"""
    m = re.search(r"(半|\d+(?:\.\d+)?|[一二两三四五六七八九十]{1,2})\s*(片|粒|胶囊|袋|毫升|毫克|克|滴|喷|支|贴)", text)
    if not m:
        return None, None
    raw, unit_cn = m.group(1), m.group(2)
    value: float | None
    if raw == "半":
        value = 0.5
    elif raw.replace(".", "", 1).isdigit():
        value = float(raw)
    else:
        value = _cn2int(raw)
    if value is None:
        return None, None
    return float(value), _UNIT_MAP.get(unit_cn)


def extract_frequency(text: str) -> str | None:
    """抽取服药频次枚举值。"""
    if re.search(r"(一天|每日|每天|一日)\s*(三|3)\s*次", text) or "早中晚各" in text or "三次" in text:
        return "three_times_daily"
    if re.search(r"(一天|每日|每天|一日)\s*(两|2)\s*次", text) or "两次" in text:
        return "twice_daily"
    if re.search(r"(一天|每日|每天|一日)\s*(一|1)\s*次", text) or "一次" in text:
        return "once_daily"
    if "隔天" in text or "隔日" in text:
        return "every_other_day"
    if "每周" in text or "每星期" in text:
        return "weekly"
    return None


def extract_times(text: str) -> list[str]:
    """抽取提醒时间点，统一成 24 小时制 HH:mm。

    支持：「早上八点」「晚上 8 点」「中午十二点半」「下午3点」「睡前」「08:00」。
    """
    times: list[str] = []

    # 1) 显式 HH:mm
    for m in re.finditer(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)", text):
        times.append(f"{int(m.group(1)):02d}:{m.group(2)}")
    if times:
        return sorted(set(times))

    # 2) 「时段 + N点」
    period_map = {
        "凌晨": 0, "清晨": 0, "早上": 0, "早晨": 0, "上午": 0,
        "中午": 12, "下午": 12, "傍晚": 12, "晚上": 12, "夜里": 12,
    }
    pattern = r"(凌晨|清晨|早上|早晨|上午|中午|下午|傍晚|晚上|夜里)?\s*(" + _NUM_TOKEN + r")\s*[点時时]\s*(半)?"
    for m in re.finditer(pattern, text):
        period, num_token, half = m.group(1), m.group(2), m.group(3)
        hour = _cn2int(num_token)
        if hour is None:
            continue
        if period and period in period_map:
            base = period_map[period]
            # 下午/晚上 的 1~11 点要 +12；中午 12 点保持 12
            if base == 12 and hour < 12:
                hour += 12
            elif base == 0 and hour == 12:
                hour = 0
        if 0 <= hour <= 23:
            times.append(f"{hour:02d}:{'30' if half else '00'}")
    if times:
        return sorted(set(times))

    # 3) 只说「睡前」没给时间，按 21:00 处理（演示用约定）
    if "睡前" in text:
        return ["21:00"]

    # 4) 只给了时段、没给具体点 -> 用约定默认值（和 schema 里的说明一致）
    defaults: list[str] = []
    if re.search(r"早上|早晨|清晨|上午", text):
        defaults.append("08:00")
    if "中午" in text:
        defaults.append("12:00")
    if "下午" in text:
        defaults.append("14:00")
    if re.search(r"晚上|傍晚", text):
        defaults.append("20:00")
    return sorted(set(defaults))


def extract_timing(text: str) -> str | None:
    """抽取服药时机。"""
    if "饭前" in text or "空腹吃" in text:
        return "before_meal"
    if "饭后" in text or "吃完饭" in text:
        return "after_meal"
    if "随餐" in text or "吃饭时" in text or "吃饭的时候" in text:
        return "with_meal"
    if "睡前" in text:
        return "bedtime"
    if "空腹" in text:
        return "empty_stomach"
    return None


def extract_targets(text: str) -> list[str]:
    """健康反馈：接收方 -> NotifyTarget 枚举值。"""
    targets: list[str] = []
    if any(k in text for k in ("医生", "医院", "大夫")):
        targets.append("hospital")
    if any(k in text for k in ("儿子", "女儿", "子女", "家人", "家里人", "孩子", "老伴")):
        targets.append("family")
    if any(k in text for k in ("社区", "居委会")):
        targets.append("community")
    return targets or ["family"]


# ======================================================================
# 三、规则关键词
# ======================================================================
_EMERGENCY_TRIGGER = [
    "救命", "救救我", "救我", "摔倒", "摔了", "摔跤", "跌倒", "胸闷", "胸疼",
    "胸口疼", "心口疼", "喘不上", "喘不过", "呼吸困难", "难受死", "快不行",
    "不行了", "晕倒", "昏倒", "流血", "出血", "打120", "叫救护车", "120",
]
_EMERGENCY_PROGRESS = [
    "救护车", "救助", "救援", "人来", "人到", "到了没", "来了没", "什么时候到", "多久到",
]
_EMERGENCY_CANCEL = ["按错", "误报", "取消呼救", "点错了", "不小心按"]
_EMERGENCY_SAFE = ["没事了", "安全了", "好多了", "缓过来", "不用来了", "别叫了", "不用叫"]

_MED_QUERY_HINTS = [
    "要吃什么药", "吃什么药", "哪些药", "还有什么药", "什么药没吃", "服药记录",
    "用药安排", "吃药安排", "今天的药", "吃过药了没有", "吃了什么药", "药吃了没",
]
_MED_UPDATE_HINTS = ["改成", "换成", "改到", "推迟", "提前", "改一下", "调整成"]
_MED_CANCEL_HINTS = ["别提醒", "不用提醒", "不吃了", "停掉", "取消提醒", "停用", "别叫醒"]
_MED_CREATE_HINTS = ["提醒", "设置", "帮我记", "加一个", "安排", "定个"]


# ======================================================================
# 四、主入口
# ======================================================================
def parse(text: str, speaker_id: str = "elder_01") -> Decision:
    """模拟 Qwen 判断一句话该不该调工具、调哪个、填什么参数。"""
    text = (text or "").strip()
    if not text:
        return Decision(reply="您说，我听着呢。", reason="空输入")

    # ---------------- 呼救（最高优先级） ----------------
    for kw in _EMERGENCY_CANCEL:
        if kw in text:
            return Decision(
                tool_name="emergency_call_cancel",
                arguments={"reason": kw, "confirmed": False},
                reason="老人表示误触/按错，走取消流程（skill 会要求一次确认）",
                hit=kw,
            )
    for kw in _EMERGENCY_SAFE:
        if kw in text:
            return Decision(
                tool_name="emergency_call_confirm_safe",
                arguments={"confirmed": True},
                reason="老人明确表示安全了，报平安",
                hit=kw,
            )
    for kw in _EMERGENCY_PROGRESS:
        if kw in text and re.search(r"(吗|没有|到|来|多久)", text):
            return Decision(
                tool_name="emergency_call_check_progress",
                arguments={},
                reason="老人在问救助进度，查询最近一次呼救状态",
                hit=kw,
            )
    for kw in _EMERGENCY_TRIGGER:
        if kw in text:
            return Decision(
                tool_name="emergency_call_trigger",
                arguments={"reason": text, "current_condition": text},
                reason="命中紧急求助词，立即发起呼救（本 skill 设计为不二次确认）",
                hit=kw,
            )

    # ---------------- 用药提醒 ----------------
    # 先判断这句话是不是在问「健康/依从性」——那种归 health_report，
    # 不要被下面的用药查询规则抢走（例如「我这周吃药按时吗」）。
    looks_health = (
        any(k in text for k in ("周报", "总结", "表现", "按时", "漏服", "漏吃", "漏了", "依从", "档案", "趋势"))
        or (
            any(k in text for k in ("发给", "发送", "发一份", "发个", "转给"))
            and any(k in text for k in ("周报", "报告", "总结", "健康", "情况", "档案"))
        )
    )

    if not looks_health:
        # 查询：含「吗/没有/没」的疑问，且不是「我吃了」这种陈述
        is_statement_taken = bool(
            re.search(r"(我|已经|刚|刚刚|早上|中午|晚上)[^，。]{0,4}(吃|服)(了|过|完)", text)
        )
        is_question = bool(re.search(r"(吗|没有|没吃|吃了没|吃过没)", text))
        wants_untaken = ("没吃" in text) or ("还有什么药" in text)
        if (is_question and not is_statement_taken) or wants_untaken or ("要吃什么药" in text):
            if any(k in text for k in ("药", "吃", "服")):
                return Decision(
                    tool_name="medication_reminder_query",
                    arguments={"un_taken_only": True} if wants_untaken else {},
                    reason="老人在询问用药安排 / 服药情况，只读查询",
                    hit="疑问句式",
                )
        for kw in _MED_QUERY_HINTS:
            if kw in text:
                return Decision(
                    tool_name="medication_reminder_query",
                    arguments={"un_taken_only": True} if wants_untaken else {},
                    reason="命中用药查询话术，只读查询",
                    hit=kw,
                )

        # 确认已服药
        if is_statement_taken and not is_question:
            med = extract_medicine(text)
            args = {"medicine_name": med} if med else {}
            return Decision(
                tool_name="medication_reminder_confirm_taken",
                arguments=args,
                reason="老人主动说已经吃过药，记录服药",
                hit="陈述句「吃了/吃过了」",
            )

        # 修改
        for kw in _MED_UPDATE_HINTS:
            if kw in text:
                args: dict[str, Any] = {}
                med = extract_medicine(text)
                if med:
                    args["medicine_name"] = med
                times = extract_times(text)
                if times:
                    args["new_times"] = times
                return Decision(
                    tool_name="medication_reminder_update",
                    arguments=args,
                    reason="老人要调整已有提醒的时间/剂量",
                    hit=kw,
                )

        # 取消
        for kw in _MED_CANCEL_HINTS:
            if kw in text:
                args = {}
                med = extract_medicine(text)
                if med:
                    args["medicine_name"] = med
                return Decision(
                    tool_name="medication_reminder_cancel",
                    arguments=args,
                    reason="老人表示不想再被提醒吃这个药（高风险，skill 会要求确认）",
                    hit=kw,
                )

        # 新增：两种触发
        #   a) 显式话术：「提醒我吃…」「帮我设置…」
        #   b) 直接描述方案：「我饭后要吃两粒二甲双胍，一天三次」
        med = extract_medicine(text)
        dosage, unit = extract_dosage(text)
        freq = extract_frequency(text)
        times = extract_times(text)
        hint_create = any(k in text for k in _MED_CREATE_HINTS) and any(
            k in text for k in ("吃", "服", "药")
        )
        scheme_create = bool(med) and (dosage is not None or freq or times) and any(
            k in text for k in ("吃", "服", "药")
        )
        if hint_create or scheme_create:
            args = {
                k: v
                for k, v in {"medicine_name": med, "dosage": dosage, "dosage_unit": unit}.items()
                if v is not None
            }
            # 频次没明说时，按时间点个数推断（一天一次 / 两次 / 三次）
            if freq is None and times:
                freq = {1: "once_daily", 2: "twice_daily", 3: "three_times_daily"}.get(len(times))
            if freq:
                args["frequency"] = freq
            if times:
                args["times"] = times
            timing = extract_timing(text)
            if timing:
                args["timing"] = timing
            return Decision(
                tool_name="medication_reminder_create",
                arguments=args,
                reason="老人要新增一个用药提醒；参数不全时程序会追问，不会编造",
                hit="「提醒/设置」+「吃药」" if hint_create else "描述了一个用药方案",
            )

    # ---------------- 健康和照顾反馈 ----------------
    send_words = ("发给", "发送", "发一份", "发个", "转给", "发给")
    health_words = ("周报", "报告", "总结", "健康", "情况", "档案")
    if any(k in text for k in send_words) and any(k in text for k in health_words):
        return Decision(
            tool_name="health_report_send_report",
            arguments={"person_id": speaker_id, "targets": extract_targets(text)},
            reason="老人要求把健康总结发给家属/医生/社区",
            hit="「发给」+「周报/报告」",
        )
    if "周报" in text or "总结" in text or re.search(r"(这周|本周|上周)[^，。]{0,5}(怎么样|如何|表现|情况)", text):
        return Decision(
            tool_name="health_report_generate_weekly",
            arguments={"person_id": speaker_id},
            reason="老人想看一周的健康/行为总结",
            hit="「周报/总结」",
        )
    if re.search(r"(按时|漏|有没有出|出了什么|记录|依从)", text) and re.search(
        r"(这周|本周|最近|这几天|今天|这个月)", text
    ):
        return Decision(
            tool_name="health_report_query_summary",
            arguments={"person_id": speaker_id, "days": 7},
            reason="老人问近期表现，快速问答，当场回答",
            hit="「这周/最近」+「按时/漏」",
        )
    if re.search(r"(上个月|上上个月|半年|趋势|长期|一直|最近几个月)", text):
        return Decision(
            tool_name="health_report_query_archive",
            arguments={"person_id": speaker_id},
            reason="老人问长期趋势，查个性化档案",
            hit="「上个月/半年/趋势」",
        )

    # ---------------- 闲聊 ----------------
    return Decision(
        reply=random.choice(_CHITCHAT_REPLIES),
        reason="不属于任何 skill 范围，不调工具，直接温和回应",
        hit="（未命中任何 skill）",
    )
