"""从 skill 库自动生成 Qwen 工具调用微调数据。

======================================================================
为什么这样做
======================================================================
组长说训练数据还没准备好。但我们的 skill 库本身就把「什么话该调什么工具、
参数长什么样」写成了机器可读的 Pydantic schema —— 这正是造 SFT 数据的理想来源。

用真实 schema 做两件事：
  1. 生成标签后【逐条用 skill 自己的模型校验】，不合法就丢弃
     → 训练数据里的工具名、参数、枚举值、跨字段规则 100% 合法
  2. 训练时的 system prompt、tools 定义、输出格式，全部与
     qwen_agent.py 推理时【完全一致】（直接 import 它的 POLICY）

======================================================================
生成哪几类样本
======================================================================
  A. 单轮工具调用      用户一句话 -> <tool_call>{...}</tool_call>
  B. 多轮补充信息      参数不全 -> 追问 -> 用户补充 -> 完整调用
  C. 闲聊 / 越界       不调工具，正常回复（防止模型见啥都想调工具）
  D. 信息不足先追问     关键信息缺失（如「那个药不吃了」）-> 纯文本追问

======================================================================
用法（在仓库根目录，也就是服务器上的 skill/ 目录里）
======================================================================
    python train/gen_data.py --out-dir data/sft --n-train 4500 --n-val 400
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import skills  # noqa: E402
from qwen_tools import SYSTEM_PROMPT_HINT  # noqa: E402

try:  # qwen_agent.py 只存在于服务器工作区（未提交到 git）
    from qwen_agent import POLICY
except Exception:  # noqa: BLE001
    POLICY = ""


IDENTITY_FIELDS = ("target_person", "person_id")
SPEAKER_ID = "elder_01"


# ======================================================================
# 一、工具定义：与 qwen_agent.py 完全一致（去掉身份字段）
# ======================================================================
def build_tools() -> list[dict[str, Any]]:
    raw = skills.export_qwen_tools()
    tools: list[dict[str, Any]] = []
    for tool in raw:
        schema = tool["function"]["parameters"]
        for key in IDENTITY_FIELDS:
            schema.get("properties", {}).pop(key, None)
            if key in schema.get("required", []):
                schema["required"].remove(key)
        tools.append(tool)
    return tools


def system_prompt(now: datetime) -> str:
    monday = (now.date() - timedelta(days=now.weekday())).isoformat()
    dated = f"\n当前时间：{now.isoformat()}；本周周一：{monday}。"
    return SYSTEM_PROMPT_HINT + POLICY + dated


def tool_call(name: str, arguments: dict[str, Any]) -> str:
    payload = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False)
    return f"<tool_call>\n{payload}\n</tool_call>"


# ======================================================================
# 二、槽位词表
# ======================================================================
MEDICINES = [
    "阿司匹林", "二甲双胍", "硝苯地平", "氨氯地平", "阿托伐他汀", "瑞舒伐他汀",
    "氯吡格雷", "美托洛尔", "缬沙坦", "厄贝沙坦", "格列美脲", "阿卡波糖",
    "复方丹参滴丸", "速效救心丸", "布洛芬", "感冒灵", "止咳糖浆", "钙片",
    "奥美拉唑", "雷贝拉唑", "甲钴胺", "叶酸", "华法林", "呋塞米", "螺内酯",
    "蒙脱石散", "阿莫西林", "头孢克肟", "碳酸钙D3", "左甲状腺素",
]
# 老人常说的笼统叫法（数据里保留，模型学会照原话说，不擅自替换成具体药名）
VAGUE_MEDS = ["降压药", "降糖药", "降脂药", "胃药", "消炎药", "止痛药", "安眠药"]

DOSES = [(0.5, "tablet"), (1, "tablet"), (2, "tablet"), (1, "capsule"), (2, "capsule"),
         (1, "bag"), (10, "ml"), (5, "ml"), (100, "mg"), (1, "drop"), (1, "puff")]

UNIT_CN = {"tablet": "片", "capsule": "粒", "bag": "袋", "ml": "毫升",
           "mg": "毫克", "g": "克", "drop": "滴", "puff": "喷", "unit": "支"}

FREQ_CN = {"once_daily": "每天一次", "twice_daily": "每天两次",
           "three_times_daily": "每天三次", "every_other_day": "隔天一次",
           "weekly": "每周一次"}

TIMING_CN = {"before_meal": "饭前", "after_meal": "饭后", "with_meal": "随餐",
             "bedtime": "睡前", "empty_stomach": "空腹"}

TIME_SLOTS = ["07:00", "08:00", "09:00", "11:30", "12:00", "12:30",
              "17:30", "18:00", "19:00", "20:00", "21:00", "21:30"]

PERIOD_CN = {7: "早上", 8: "早上", 9: "上午", 11: "中午", 12: "中午",
             17: "下午", 18: "晚上", 19: "晚上", 20: "晚上", 21: "晚上"}


def time_cn(hhmm: str) -> str:
    hh, mm = (int(x) for x in hhmm.split(":"))
    period = PERIOD_CN.get(hh, "上午" if hh < 12 else "下午")
    h12 = hh - 12 if hh > 12 else (12 if hh == 12 else hh)
    base = f"{period}{h12}点"
    return base + "半" if mm == 30 else base


# ======================================================================
# 三、标签校验（用 skill 自己的模型）
# ======================================================================
_INSTANCES = {s.name: s for s in skills.all_skills()}


def validate(skill_name: str, action: str, args: dict[str, Any]) -> bool:
    """用真实的 Pydantic 模型校验标签。不合法就丢弃，绝不让脏标签进训练集。"""
    skill = _INSTANCES[skill_name]
    model = skill.ACTIONS[action]
    probe = dict(args)
    if "person_id" in model.model_fields:
        probe["person_id"] = SPEAKER_ID      # 推理时由程序注入，标签里不出现
    try:
        model.model_validate(probe)
        return True
    except Exception:  # noqa: BLE001
        return False


# ======================================================================
# 四、各类样本生成
# ======================================================================
def gen_create(rng: random.Random) -> tuple[str, str, dict] | None:
    """用药提醒 - 新增。"""
    med = rng.choice(MEDICINES + VAGUE_MEDS * 2)
    freq = rng.choice(["once_daily", "once_daily", "twice_daily", "twice_daily",
                       "three_times_daily", "every_other_day", "weekly"])
    need = {"once_daily": 1, "twice_daily": 2, "three_times_daily": 3,
            "every_other_day": 1, "weekly": 1}[freq]
    # 按频次挑时间点，尽量符合生活作息
    pools = {
        1: [["07:00"], ["08:00"], ["08:00"], ["12:00"], ["20:00"], ["21:00"]],
        2: [["08:00", "20:00"], ["07:00", "19:00"], ["08:00", "18:00"]],
        3: [["08:00", "12:00", "18:00"], ["07:00", "12:00", "20:00"]],
    }
    times = (rng.choice(pools[1]) if need == 1 else rng.choice(pools[need]))
    times_cn = "、".join(time_cn(t) for t in times)
    dose, unit = rng.choice(DOSES)
    unit_cn = UNIT_CN[unit]
    timing = rng.choice([None, "after_meal", "before_meal", "with_meal",
                         "bedtime", "empty_stomach"])
    args: dict[str, Any] = {
        "medicine_name": med, "dosage": dose, "dosage_unit": unit,
        "frequency": freq, "times": list(times),
    }
    if timing:
        args["timing"] = timing
    if freq == "weekly":
        day = rng.randint(0, 6)
        args["weekdays"] = [day]
    dose_cn = f"{dose:g}{unit_cn}"
    timing_cn = TIMING_CN.get(timing or "", "")

    patterns = [
        f"{times_cn}提醒我吃{dose_cn}{med}",
        f"帮我设个提醒，{times_cn}吃{dose_cn}{med}",
        f"我现在开始吃{med}了，{FREQ_CN[freq]}，一次{dose_cn}，{times_cn}",
        f"我{timing_cn + '要吃' if timing_cn else '要吃'}{dose_cn}{med}，{FREQ_CN[freq]}，{times_cn}提醒我",
        f"给我加个{med}的提醒，{FREQ_CN[freq]}，每次{dose_cn}，{times_cn}",
        f"医生让我吃{med}，{FREQ_CN[freq]}一次{dose_cn}，{times_cn}",
        f"你帮我记一下，{times_cn}我要吃{med}，{dose_cn}",
    ]
    if freq == "weekly":
        wd = args["weekdays"][0]
        patterns.append(f"每周{'一二三四五六日'[wd]}{time_cn(times[0])}提醒我吃{dose_cn}{med}")
    utt = rng.choice(patterns)
    if timing_cn and timing_cn not in utt:
        utt += f"，{timing_cn}吃"
    return utt, "medication_reminder_create", args


def gen_query(rng: random.Random, now: datetime) -> tuple[str, str, dict] | None:
    """用药提醒 - 查询。"""
    med = rng.choice(MEDICINES + VAGUE_MEDS)
    kind = rng.choice(["all", "untaken", "specific", "history", "yesterday"])
    if kind == "all":
        utt = rng.choice(["我今天要吃什么药", "今天都有什么药要吃", "我今天吃什么药呀",
                          "帮我看下今天的用药安排", "今天要吃哪几种药"])
        return utt, "medication_reminder_query", {}
    if kind == "untaken":
        utt = rng.choice(["我今天还有什么药没吃", "还有哪些药没吃", "我还有药没吃吗",
                          "今天哪个药还没吃", "我早上那个药吃了没"])
        return utt, "medication_reminder_query", {"un_taken_only": True}
    if kind == "specific":
        utt = rng.choice([f"{med}吃了吗", f"{med}我吃了没有", f"{med}今天的吃了没"])
        return utt, "medication_reminder_query", {"medicine_name": med,
                                                  "un_taken_only": True}
    if kind == "history":
        utt = rng.choice(["我前几天吃了什么药", "最近几天我吃什么药了",
                          "昨天的药吃了没"])
        args: dict[str, Any] = {"include_history": True}
        if "昨天" in utt:
            args["date"] = (now.date() - timedelta(days=1)).isoformat()
        return utt, "medication_reminder_query", args
    utt = "昨天吃了什么药"
    return utt, "medication_reminder_query", {
        "date": (now.date() - timedelta(days=1)).isoformat(), "include_history": True}


def gen_confirm(rng: random.Random) -> tuple[str, str, dict] | None:
    med = rng.choice(MEDICINES + VAGUE_MEDS)
    kind = rng.choice(["named", "generic", "generic"])
    if kind == "named":
        utt = rng.choice([f"我刚吃完{med}了", f"{med}我吃过了", f"早上{med}吃了",
                          f"我已经吃过{med}了", f"{med}吃完了"])
        return utt, "medication_reminder_confirm_taken", {"medicine_name": med}
    utt = rng.choice(["我吃过药了", "刚吃完药", "药吃了", "我吃过了",
                      "今早的药吃了", "我按时吃了"])
    return utt, "medication_reminder_confirm_taken", {}


def gen_update(rng: random.Random) -> tuple[str, str, dict] | None:
    med = rng.choice(MEDICINES + VAGUE_MEDS)
    kind = rng.choice(["times", "dosage", "timing", "end"])
    if kind == "times":
        t = rng.choice(TIME_SLOTS)
        utt = rng.choice([f"把{med}改成{time_cn(t)}提醒", f"{med}改到{time_cn(t)}",
                          f"提醒时间改一下，{med}{time_cn(t)}",
                          f"把吃{med}的时间改成{time_cn(t)}"])
        return utt, "medication_reminder_update", {"medicine_name": med, "new_times": [t]}
    if kind == "dosage":
        dose, unit = rng.choice([(0.5, "tablet"), (1, "tablet"), (2, "tablet"), (1, "capsule")])
        utt = rng.choice([f"{med}我改成吃{dose:g}{UNIT_CN[unit]}了",
                          f"{med}现在改成{dose:g}{UNIT_CN[unit]}",
                          f"{med}的用量改成{dose:g}{UNIT_CN[unit]}"])
        return utt, "medication_reminder_update", {
            "medicine_name": med, "new_dosage": dose, "new_dosage_unit": unit}
    if kind == "timing":
        t = rng.choice(list(TIMING_CN))
        utt = rng.choice([f"{med}改成{TIMING_CN[t]}吃", f"{med}以后{TIMING_CN[t]}吃"])
        return utt, "medication_reminder_update", {"medicine_name": med, "new_timing": t}
    end = (datetime(2026, 11, 30).date()).isoformat()
    utt = rng.choice([f"{med}吃到这个月底就不吃了", f"{med}吃到月底就停",
                      f"{med}先吃到十一月底"])
    return utt, "medication_reminder_update", {"medicine_name": med, "new_end_date": end}


def gen_cancel(rng: random.Random) -> tuple[str, str, dict] | None:
    med = rng.choice(MEDICINES + VAGUE_MEDS)
    utt = rng.choice([f"别提醒我吃{med}了", f"{med}不用提醒了", f"把{med}的提醒去掉",
                      f"{med}我不吃了，别再叫我", f"取消{med}的提醒"])
    args: dict[str, Any] = {"medicine_name": med}
    if rng.random() < 0.4:
        args["reason"] = rng.choice(["医生说停了", "换药了", "吃了不舒服", "吃完这盒不吃了"])
    return utt, "medication_reminder_cancel", args


def gen_emergency(rng: random.Random) -> tuple[str, str, dict] | None:
    kind = rng.choice(["trigger", "trigger", "trigger", "trigger",
                       "progress", "cancel", "safe"])
    if kind == "trigger":
        reason, cond = rng.choice([
            ("摔倒了，起不来", "腿动不了，人还清醒"),
            ("胸口疼得厉害", "喘不上气"),
            ("喘不上气", "憋得慌"),
            ("头晕得厉害，站不住", "浑身没劲"),
            ("流血了，止不住", "手上都是血"),
            ("心口疼", "出冷汗"),
            ("从床上摔下来了", "腰疼得起不来"),
            ("难受得不行了", "说话都没力气"),
        ])
        utt = rng.choice([f"救命，我{reason}", f"我{reason}，快来帮我",
                          f"哎呀我{reason}", f"快叫人，我{reason}",
                          "救命啊", "快打120", "我不行了，快叫救护车"])
        args: dict[str, Any] = {}
        if rng.random() < 0.85:
            args["reason"] = reason
        if rng.random() < 0.4:
            args["current_condition"] = cond
        if rng.random() < 0.3:
            args["location"] = rng.choice(["客厅", "卧室", "卫生间", "厨房", "楼道里"])
        return utt, "emergency_call_trigger", args
    if kind == "progress":
        utt = rng.choice(["救护车来了吗", "人到了没有", "救助的人到哪了",
                          "有人来吗", "车到楼下了吗", "怎么还没人来"])
        return utt, "emergency_call_check_progress", {}
    if kind == "cancel":
        utt = rng.choice(["我按错了，取消吧", "刚才是误报，取消", "不小心按到了，取消呼救"])
        return utt, "emergency_call_cancel", {"reason": "误报"}
    utt = rng.choice(["我没事了，不用来了", "我好多了，别叫人了", "我缓过来了，取消吧"])
    return utt, "emergency_call_confirm_safe", {}


def gen_health(rng: random.Random, now: datetime) -> tuple[str, str, dict] | None:
    kind = rng.choice(["weekly", "summary", "send", "archive"])
    if kind == "weekly":
        if rng.random() < 0.5:
            return (rng.choice(["这周我表现怎么样", "帮我看看这周的情况",
                                "这周我怎么样", "给我总结一下这周"]),
                    "health_report_generate_weekly", {})
        last_monday = (now.date() - timedelta(days=now.weekday() + 7)).isoformat()
        return (rng.choice(["上周我表现怎么样", "帮我看看上周的情况",
                            "上周我吃药按时吗"]),
                "health_report_generate_weekly", {"week_start": last_monday})
    if kind == "summary":
        days = rng.choice([7, 7, 30])
        utt = ("我这周吃药按时吗" if days == 7 else "我这个月吃药按时吗")
        if rng.random() < 0.3:
            utt = rng.choice(["我最近有没有漏吃药", "这周有没有出什么事"])
        return utt, "health_report_query_summary", {"days": days}
    if kind == "send":
        targets = rng.choice([["hospital"], ["family"], ["family", "hospital"],
                              ["community"], ["family", "community"]])
        utt = {("hospital",): "把周报发给医生",
               ("family",): "把周报发给我儿子",
               ("family", "hospital"): "把周报发给医生和我女儿",
               ("community",): "把周报发给社区",
               ("family", "community"): "周报发给家里人和社区"}[tuple(targets)]
        args: dict[str, Any] = {"targets": targets}
        if rng.random() < 0.4:
            args["week_start"] = (now.date() - timedelta(days=now.weekday() + 7)).isoformat()
        return utt, "health_report_send_report", args
    utt = rng.choice(["我上个月吃药怎么样", "这半年我身体情况有什么变化",
                      "我最近几个月漏服多吗", "看看我长期的记录"])
    args = {}
    if rng.random() < 0.5:
        args["start_date"] = (now.date() - timedelta(days=rng.choice([30, 90, 180]))).isoformat()
    return utt, "health_report_query_archive", args


CHITCHAT = [
    ("今天天气怎么样呀", "张奶奶早上好，今天外头有点凉，出门记得加件外套。"),
    ("你给我唱个歌吧", "我唱歌不好听，怕吵着您。要不我陪您说说话？"),
    ("你是谁呀", "我是您的语音助手，帮您记着吃药、有事儿也能帮您叫人。"),
    ("我孙子什么时候回来", "这个我可说不好，您要不给他打个电话问问？"),
    ("我睡不着", "那您躺好，别老看手机，我陪您说几句话。"),
    ("帮我订个外卖", "订外卖这事儿我暂时还做不了，您让家里人帮您弄一下吧。"),
    ("我想看电视", "我这儿没法开电视，您用遥控器试试，实在不行叫家里人帮您。"),
    ("今天星期几", "您稍等，我看看……今天是工作日，孩子们都上班去了。"),
    ("我有点闷", "那咱们聊聊天，您今天感觉身体怎么样？"),
    ("谢谢你啊", "不客气，您有事儿随时叫我。"),
]

# 信息不足时应当先追问（不调工具）
ASK_BACK = [
    ("那个药不吃了", "您说的是哪个药呀？我这儿记着好几种呢。"),
    ("帮我改一下提醒", "您想把哪个药改成什么样呢？说得细一点我好帮您改。"),
    ("提醒我吃药", "请问是哪种药呀？您说个名字我好帮您记下来。"),
    ("我不舒服", "您哪儿不舒服呀？要是着急，直接说救命，我马上帮您叫人。"),
    ("把那个发给医生", "您想把什么发给医生呢？是这周的情况总结吗？"),
]


# ======================================================================
# 五、组装样本
# ======================================================================
def sample(now: datetime, turns: list[tuple[str, str]]) -> dict:
    messages = [{"role": "system", "content": system_prompt(now)}]
    for role, content in turns:
        messages.append({"role": role, "content": content})
    return {"messages": messages}


def gen_one(rng: random.Random, now: datetime) -> dict | None:
    """生成一条样本，可能是单轮、多轮、闲聊或追问。"""
    roll = rng.random()
    if roll < 0.10:                                  # 闲聊 / 越界
        utt, reply = rng.choice(CHITCHAT)
        return sample(now, [("user", utt), ("assistant", reply)])
    if roll < 0.15:                                  # 信息不足先追问
        utt, reply = rng.choice(ASK_BACK)
        return sample(now, [("user", utt), ("assistant", reply)])

    maker = rng.choice([gen_create, gen_create, gen_create, gen_query, gen_confirm,
                        gen_update, gen_cancel, gen_emergency, gen_emergency, gen_health])
    # 多轮样本只能从「必填字段多」的 action 拆出来，这里固定用 create 抬高产量
    if roll < 0.25:
        maker = gen_create
    if maker in (gen_query, gen_health):
        out = maker(rng, now)          # type: ignore[call-arg]
    else:
        out = maker(rng)
    if out is None:
        return None
    utt, name, args = out

    # 用注册表反查，确保工具名与 skill 完全对得上
    found = skills.find_by_tool_name(name)
    if found is None:
        return None
    skill, action = found
    if not validate(skill.name, action, args):
        return None

    if roll < 0.25:                                  # 多轮：先给不全，再补充
        multi = gen_multiturn(rng, now, skill, action, utt, args)
        if multi is not None:
            return multi

    return sample(now, [("user", utt), ("assistant", tool_call(name, args))])


def gen_multiturn(rng: random.Random, now: datetime, skill, action: str,
                  utt: str, args: dict[str, Any]) -> dict | None:
    """参数不全 -> 追问 -> 补充 -> 完整调用。

    只对「必填字段」做拆分；拆分后第一轮参数必须仍然无法通过校验，
    这样第一轮调 tool_call 时 skill 会给出追问（与推理时的真实行为一致）。
    """
    model = skill.ACTIONS[action]
    required = [k for k in model.model_fields if model.model_fields[k].is_required()]
    if len(required) < 2:
        return None
    # 第一轮只保留一部分必填字段
    keep = [k for k in required if rng.random() < 0.5]
    if not keep or len(keep) == len(required):
        return None
    partial = {k: v for k, v in args.items() if k in keep}
    if validate(skill.name, action, partial):
        return None                                  # 第一轮就合法，失去追问意义
    tool_name = skill.tool_name(action)
    first_utt = utt
    # 第二轮补充的话术：把缺的字段用口语说出来
    supplements = {
        "medicine_name": f"是{args.get('medicine_name')}",
        "dosage": f"一次{args.get('dosage', 1):g}{UNIT_CN.get(args.get('dosage_unit', 'tablet'), '片')}"
                  if "dosage" in args else "一次一片",
        "dosage_unit": "",
        "frequency": FREQ_CN.get(args.get("frequency", ""), ""),
        "times": "、".join(time_cn(t) for t in args.get("times", [])),
        "targets": "发给医生",
    }
    missing = [k for k in required if k not in partial]
    pieces = [supplements.get(k, "").strip() for k in missing]
    second_utt = "，".join(p for p in pieces if p) or "就是刚才说的那样"
    followup = f"还差一点信息：{ '、'.join(missing) }，您再说一下？"
    return sample(now, [
        ("user", first_utt),
        ("assistant", tool_call(tool_name, partial)),
        ("user", second_utt),
        ("assistant", tool_call(tool_name, args)),
    ])


# ======================================================================
# 六、主流程
# ======================================================================
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="data/sft")
    ap.add_argument("--n-train", type=int, default=4500)
    ap.add_argument("--n-val", type=int, default=400)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--tools-out", default="data/sft/tools.json")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tools = build_tools()
    Path(args.tools_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.tools_out).write_text(
        json.dumps(tools, ensure_ascii=False, indent=1), encoding="utf-8")

    rng = random.Random(args.seed)
    base_now = datetime(2026, 10, 18, 9, 0)

    def build(n: int, offset: int) -> list[dict]:
        rows: list[dict] = []
        guard = 0
        while len(rows) < n and guard < n * 40:
            guard += 1
            now = base_now + timedelta(days=rng.randint(-20, 20),
                                       hours=rng.randint(-3, 8))
            row = gen_one(rng, now)
            if row:
                rows.append(row)
        return rows

    train = build(args.n_train, 0)
    val = build(args.n_val, 1)

    for name, rows in (("train", train), ("val", val)):
        path = out_dir / f"{name}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{path}: {len(rows)} 条")

    # 统计
    from collections import Counter
    counter: Counter[str] = Counter()
    for row in train + val:
        last = row["messages"][-1]["content"]
        if not last.startswith("<tool_call>"):
            counter["无工具（闲聊/追问）"] += 1
            continue
        payload = json.loads(last.split("<tool_call>")[1].split("</tool_call>")[0])
        counter[payload["name"]] += 1
    print("\n样本分布：")
    for k, v in counter.most_common():
        print(f"  {k:42s} {v}")
    print(f"  {'多轮样本':42s} "
          f"{sum(1 for r in train + val if len(r['messages']) > 3)}")


if __name__ == "__main__":
    main()
