"""老人语音助手 · 可视化演示界面（Gradio）。

一句话概括它演示什么：
    老人说一句话 → （模拟）Qwen 判断意图 → 查注册表 → 校验参数 → 执行 skill → 回话
    —— 每一步都在右侧「决策链路」里摊开给观众看。

跑法（在仓库根目录）：
    python webapp/app.py
然后浏览器打开 http://127.0.0.1:7860

【关于「模拟 Qwen」】
组长说语音模型还在做实验，可以模拟语音输入；同理云端 Qwen 服务还没起，
这里用 webapp/sim_qwen.py 的规则版意图识别顶替，输出格式和真 Qwen 的
tool_call 一致。界面上明确标注了「模拟」，接真模型时只需替换 sim_qwen.parse。
"""

from __future__ import annotations

import html
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import skills  # noqa: E402
from webapp.runtime import DemoRuntime  # noqa: E402

RUNTIME = DemoRuntime()

# 待对齐细节文档：界面第 4 页直接渲染它，保证「文档 ↔ 界面」是同一份内容
ALIGNMENT_FILE = Path(__file__).resolve().parent / "待对齐细节.md"

# ----------------------------------------------------------------------
# 演示剧本：观众按顺序点这些按钮，就能看到完整故事
# ----------------------------------------------------------------------
SCENARIOS: list[tuple[str, str]] = [
    ("💊 设置吃药提醒", "每天早上八点提醒我吃一片阿司匹林，饭后吃"),
    ("💊 只说药名（触发追问）", "提醒我吃药"),
    ("💊 方案描述", "我饭后要吃两粒二甲双胍，一天三次"),
    ("❓ 查用药安排", "还有什么药没吃"),
    ("✅ 主动报吃药", "我刚吃完阿司匹林了"),
    ("✏️ 改提醒时间", "把阿司匹林改成早上七点提醒"),
    ("❌ 取消提醒（高风险）", "别提醒我吃阿司匹林了"),
    ("🚨 紧急呼救", "哎呀我摔倒了，起不来了"),
    ("🚑 问救助进度", "救护车来了吗"),
    ("🕊️ 报平安", "我没事了，不用来了"),
    ("📊 问本周表现", "我这周吃药按时吗"),
    ("📄 生成周报", "帮我看看这周的表现"),
    ("📤 发送周报", "把周报发给医生"),
    ("📈 查长期趋势", "我上个月吃药怎么样"),
    ("💬 闲聊（不调工具）", "今天天气怎么样呀"),
]


# ======================================================================
# HTML 渲染
# ======================================================================
_CSS = """
:root {
  --ink: #1f2933;
  --muted: #6b7280;
  --brand: #0f766e;
  --brand-soft: #ccfbf1;
  --line: #e5e7eb;
}
.gradio-container { max-width: 1320px !important; }
.app-header {
  background: linear-gradient(135deg, #0f766e 0%, #0e7490 100%);
  color: #fff; border-radius: 16px; padding: 20px 24px; margin-bottom: 14px;
}
.app-header h1 { margin: 0 0 6px; font-size: 26px; letter-spacing: .5px; }
.app-header p { margin: 0; opacity: .92; font-size: 14px; line-height: 1.7; }
.badge-sim {
  display: inline-block; background: #fef3c7; color: #92400e;
  border-radius: 999px; padding: 2px 10px; font-size: 12px; margin-left: 8px;
}
.flow { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.flow .chip {
  background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.35);
  color: #fff; border-radius: 999px; padding: 5px 12px; font-size: 13px;
}
.flow .arrow { color: rgba(255,255,255,.7); align-self: center; }

.trace-wrap { display: flex; flex-direction: column; gap: 9px; }
.step {
  border: 1px solid var(--line); border-left: 5px solid #94a3b8;
  border-radius: 10px; padding: 10px 13px; background: #fff;
}
.step.ok { border-left-color: #10b981; background: #f0fdf4; }
.step.followup { border-left-color: #f59e0b; background: #fffbeb; }
.step.chitchat { border-left-color: #64748b; background: #f8fafc; }
.step.error { border-left-color: #ef4444; background: #fef2f2; }
.step .hd {
  font-size: 12px; font-weight: 700; color: var(--muted);
  letter-spacing: .6px; margin-bottom: 6px; text-transform: uppercase;
}
.step .bd { font-size: 14px; color: var(--ink); line-height: 1.75; }
.kv { font-family: ui-monospace, Consolas, monospace; font-size: 13px; }
.pill {
  display: inline-block; border-radius: 6px; padding: 1px 7px; font-size: 12px;
  background: var(--brand-soft); color: var(--brand); margin-right: 5px;
}
.pill.risk-high { background: #fee2e2; color: #b91c1c; }
.pill.risk-medium { background: #fef3c7; color: #b45309; }
.pill.risk-low { background: #dcfce7; color: #15803d; }
.speech {
  background: #0f766e; color: #fff; border-radius: 12px; padding: 12px 15px;
  font-size: 15px; line-height: 1.75;
}
.empty {
  color: var(--muted); font-size: 14px; padding: 34px 16px; text-align: center;
  line-height: 1.9; background: #fff; border: 1px dashed var(--line); border-radius: 12px;
}
pre.json {
  background: #f8fafc; border: 1px solid var(--line); border-radius: 8px;
  padding: 8px 10px; font-size: 12.5px; overflow-x: auto; margin: 6px 0 0;
  white-space: pre-wrap; word-break: break-all;
}
"""

_HEADER = """
<div class="app-header">
  <h1>🧓 老人语音助手 · Agent 链路演示<span class="badge-sim">Qwen 为模拟</span></h1>
  <p>
    面向独居老人的语音助手。老人说一句话，系统识别意图、调用对应 skill、校验参数、执行后把结果念回去。
    下方右侧会把「Agent 内部到底发生了什么」逐步摊开。
  </p>
  <div class="flow">
    <span class="chip">老人语音</span><span class="arrow">→</span>
    <span class="chip">ASR 转文字<br><small>（本演示用文本模拟）</small></span><span class="arrow">→</span>
    <span class="chip">Qwen 判断意图<br><small>（模拟）</small></span><span class="arrow">→</span>
    <span class="chip">查注册表</span><span class="arrow">→</span>
    <span class="chip">参数校验</span><span class="arrow">→</span>
    <span class="chip">执行 skill</span><span class="arrow">→</span>
    <span class="chip">语音反馈</span>
  </div>
</div>
"""


def _esc(v) -> str:
    return html.escape(str(v))


def _json_block(obj) -> str:
    if not obj:
        return ""
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    return f'<pre class="json">{_esc(text)}</pre>'


def render_trace(trace: dict | None) -> str:
    """把一次处理的轨迹渲染成竖排步骤卡片。"""
    if trace is None:
        return '<div class="empty">👈 点左边的示例话术，或在输入框里说一句话，<br>这里会逐步显示 Agent 的判断过程。</div>'

    stage = trace["stage"]
    qwen = trace["qwen"]
    registry = trace["registry"]
    result = trace["result"]
    stage_class = stage if stage in ("ok", "followup", "chitchat", "error") else ""

    parts: list[str] = ['<div class="trace-wrap">']

    # ① 输入
    parts.append(
        '<div class="step"><div class="hd">① 老人说（ASR 文字）</div>'
        f'<div class="bd">{_esc(trace["utterance"])}</div></div>'
    )

    # ② 模拟 Qwen
    if qwen["tool_name"] is None:
        body = (
            f'<span class="pill">不调用工具</span>{_esc(qwen["reason"])}'
            f'<br><span class="kv">判断依据：{_esc(qwen["hit"])}</span>'
        )
    else:
        body = (
            f'<span class="pill">tool_call</span>'
            f'<span class="kv"><b>{_esc(qwen["tool_name"])}</b></span>'
            f'<br><span class="kv">判断依据：{_esc(qwen["hit"])} —— {_esc(qwen["reason"])}</span>'
            + _json_block(qwen["arguments"])
        )
    parts.append(
        '<div class="step"><div class="hd">② 模拟 Qwen 判断意图 / 填参数</div>'
        f'<div class="bd">{body}</div></div>'
    )

    # ③ 注册表
    if registry is None:
        if qwen["tool_name"] is not None:
            parts.append(
                '<div class="step error"><div class="hd">③ 查注册表</div>'
                '<div class="bd">没找到这个工具名，忽略本次调用。</div></div>'
            )
    else:
        risk = registry["risk_level"]
        parts.append(
            '<div class="step"><div class="hd">③ 查注册表：命中 skill</div>'
            f'<div class="bd"><span class="pill">{_esc(registry["display_name"])}</span>'
            f'<span class="kv">{_esc(registry["skill"])} / <b>{_esc(registry["action"])}</b></span>'
            f'<span class="pill risk-{risk}">风险：{_esc(risk)}</span></div></div>'
        )

    # ④ 参数校验
    if result is not None:
        if result["need_followup"]:
            check = ('<span class="pill">未通过</span>参数不全，转成一句追问，'
                     '<b>不抛异常</b>（老人信息常常不全，追问是正常流程）')
        elif result["ok"]:
            check = '<span class="pill">通过</span>类型/范围/必填/跨字段规则全部满足'
        else:
            check = '<span class="pill">执行失败</span>' + _esc(result["error"] or "")
        # 确认级别：Agent 层据此决定要不要让老人复述、要不要通知家属。
        # （第 4 页「待对齐细节」正在讨论三个 skill 这个字段是否统一。）
        level = result.get("confirm_level") or "none"
        check += (
            f'<br><span class="kv">确认级别 confirm_level：<b>{_esc(level)}</b></span>'
        )
        parts.append(
            '<div class="step"><div class="hd">④ Pydantic 参数校验</div>'
            f'<div class="bd">{check}</div></div>'
        )

    # ⑤ 执行结果
    if result is not None and result["ok"]:
        extra = ""
        if result["data"]:
            extra += _json_block(result["data"])
        if result["notifications"]:
            extra += (
                '<div class="bd" style="margin-top:6px">📮 产出待发送通知 '
                f'<b>{len(result["notifications"])}</b> 条（真正发送由上层出站层统一做）：</div>'
                + _json_block(result["notifications"])
            )
        parts.append(
            '<div class="step ok"><div class="hd">⑤ 执行 skill（成功）</div>'
            f'<div class="bd">{extra or "已执行完成。"}</div></div>'
        )

    # ⑥ 回话
    parts.append(
        '<div class="step"><div class="hd">⑥ 助手回话（TTS 直接播这句）</div>'
        f'<div class="speech">🔊 {_esc(trace["speech"])}</div></div>'
    )

    parts.append("</div>")
    return "".join(parts)


def _events_rows() -> list[list[str]]:
    return RUNTIME.events_snapshot()


def _notifications_rows() -> list[list[str]]:
    snap = RUNTIME.notifications_snapshot()
    return [[n["来源"], n["对象"], n["状态"], n["说明"]] for n in snap]


def _tools_rows() -> list[list[str]]:
    rows: list[list[str]] = []
    for tool in skills.export_qwen_tools():
        fn = tool["function"]
        required = fn["parameters"].get("required", [])
        rows.append([fn["name"], "、".join(required) or "（无必填）", fn["description"][:80]])
    return rows


def _alignment_md() -> str:
    """读取待对齐细节文档。界面与文档共用同一份内容，避免两处不一致。"""
    if ALIGNMENT_FILE.exists():
        return ALIGNMENT_FILE.read_text(encoding="utf-8")
    return "⚠️ 找不到 `webapp/待对齐细节.md`，请确认文件是否被移动。"


def _confirm_level_rows() -> list[list[str]]:
    """实时扫描三个 skill 的源码，看谁真正设置了 confirm_level。

    为什么要做成实时的：这样「呼救和健康反馈没设」这个结论是可验证的——
    改完代码刷新页面，表格里的 ❌ 就会变成 ✅，不用手改文档。

    只统计非 NONE 的级别：有些地方写 `ConfirmLevel.NONE` 只是取默认值
    （例如 data.pop("confirm_level", ConfirmLevel.NONE)），不算真的设置了确认。
    """
    import re

    root = REPO_ROOT / "skills"
    meaning = {
        "REPEAT_BACK": "让老人复述确认",
        "GUARDIAN": "需通知家属",
    }
    rows: list[list[str]] = []
    for skill_name in ("medication_reminder", "emergency_call", "health_report"):
        path = root / skill_name / "executor.py"
        if not path.exists():
            rows.append([skill_name, "（找不到 executor.py）", "—"])
            continue
        text = path.read_text(encoding="utf-8")
        found = {
            lv for lv in re.findall(r"ConfirmLevel\.([A-Z_]+)", text) if lv != "NONE"
        }
        if found:
            detail = "、".join(f"{lv}（{meaning.get(lv, lv)}）" for lv in sorted(found))
            rows.append([skill_name, "✅ " + detail, "已设置"])
        else:
            rows.append([
                skill_name,
                "❌ 从未设置 → 默认 NONE（Agent 层会认为不需要任何确认）",
                "待补",
            ])
    return rows


# ======================================================================
# 事件处理
# ======================================================================
def _turn(history: list[dict], utterance: str):
    """跑一轮对话，返回 (history, trace_html, events, notifications)。"""
    trace = RUNTIME.handle(utterance)
    history = history + [
        {"role": "user", "content": utterance},
        {"role": "assistant", "content": trace["speech"]},
    ]
    return history, render_trace(trace), _events_rows(), _notifications_rows()


def on_send(message: str, history: list[dict]):
    if not (message or "").strip():
        return history, "", render_trace(None), _events_rows(), _notifications_rows()
    result = _turn(history or [], message.strip())
    return (result[0], "") + result[1:]


def make_scenario_handler(utterance: str):
    def handler(history: list[dict]):
        return _turn(history or [], utterance)

    return handler


def on_reset():
    RUNTIME.reset()
    return [], render_trace(None), _events_rows(), _notifications_rows()


def on_due(at_text: str):
    try:
        hh, mm = (int(x) for x in at_text.strip().replace("：", ":").split(":"))
        at = datetime(2026, 10, 10, hh, mm)
    except Exception:
        return "⚠️ 时间格式请填 HH:MM，例如 08:00"

    due = RUNTIME.due_reminders(at)
    if not due:
        return (
            f"⏰ **{at:%H:%M}** 没有到点需要提醒的药。\n\n"
            "（说明：已经确认吃过的那个时间点不会再重复提醒；漏服超过阈值会升级为通知子女。）"
        )
    lines = [f"⏰ **{at:%H:%M}** 调度器结果："]
    for d in due:
        if d.get("escalate"):
            lines.append(
                f"- 🚨 **漏服升级**：{d.get('medicine_name')} 的 {d.get('slot')} 那次"
                f"已超时 {d.get('overdue_minutes')} 分钟 → 通知子女：{d.get('notify_text')}"
            )
        else:
            lines.append(f"- 🔊 **到点播报**：{d.get('speech')}")
    return "\n".join(lines)


# ======================================================================
# 界面
# ======================================================================
def build_app():
    import gradio as gr

    # Gradio 5 / 6 的 API 差异：6.0 起 css 从 Blocks() 移到 launch()，
    # Chatbot 也去掉了 type 参数（messages 成为唯一格式）。这里做自适应。
    major = int(gr.__version__.split(".")[0])
    blocks_kwargs = {} if major >= 6 else {"css": _CSS}
    chatbot_kwargs = {} if major >= 6 else {"type": "messages"}

    with gr.Blocks(title="老人语音助手 · Agent 演示", **blocks_kwargs) as demo:
        gr.HTML(_HEADER)

        with gr.Tabs():
            # ---------------- Tab 1：对话演示 ----------------
            with gr.Tab("① 对话演示"):
                # 先建右侧的「链路 + 数据」组件，再建底部的按钮，这样按钮能引用到它们
                with gr.Row():
                    with gr.Column(scale=6):
                        chatbot = gr.Chatbot(
                            label="对话（模拟老人语音输入）",
                            height=460,
                            **chatbot_kwargs,
                        )
                    with gr.Column(scale=6):
                        gr.Markdown("### 🔍 Agent 决策链路")
                        trace_view = gr.HTML(render_trace(None))
                        with gr.Accordion("📋 共享事件流（三个 skill 共用）", open=True):
                            events_view = gr.Dataframe(
                                headers=["类型", "内容", "剂量", "状态", "时间", "来源"],
                                value=_events_rows(),
                                wrap=True,
                                show_label=False,
                            )
                        with gr.Accordion("📮 待发送通知（出站层的输入）", open=False):
                            notif_view = gr.Dataframe(
                                headers=["来源", "对象", "状态", "说明"],
                                value=_notifications_rows(),
                                wrap=True,
                                show_label=False,
                            )

                with gr.Row():
                    msg = gr.Textbox(
                        placeholder="模拟老人说的话，例如：每天早上八点提醒我吃一片阿司匹林",
                        show_label=False,
                        scale=9,
                        autofocus=True,
                    )
                    send_btn = gr.Button("发送", variant="primary", scale=1)
                    reset_btn = gr.Button("🔄 重置", size="sm", scale=1)

                gr.Markdown("**示例话术（点一下直接演示）**")
                # 每行固定 3 个，避免 Gradio 自动换行导致按钮错位
                for start in range(0, len(SCENARIOS), 3):
                    with gr.Row():
                        for label_text, utt in SCENARIOS[start:start + 3]:
                            gr.Button(label_text, size="sm").click(
                                make_scenario_handler(utt),
                                inputs=[chatbot],
                                outputs=[chatbot, trace_view, events_view, notif_view],
                            )

            # ---------------- Tab 2：定时调度 ----------------
            with gr.Tab("② 定时调度"):
                gr.Markdown(
                    "用药提醒除了「老人主动问」，还需要**后台定时器**到点播报、漏服升级。\n\n"
                    "调度器每分钟调用一次 `medication_reminder.due_reminders()`：\n"
                    "- 到点未服 -> 返回该播报的话\n"
                    "- 超过阈值仍未服 -> 判定漏服，落一条 `missed` 事件到共享事件流，并升级通知子女\n\n"
                    "（已确认服用的时间点不会再重复提醒。）"
                )
                with gr.Row():
                    due_input = gr.Textbox(value="08:00", label="模拟当前时刻（HH:MM）", scale=2)
                    due_btn = gr.Button("查询此刻该提醒谁", variant="primary", scale=1)
                due_out = gr.Markdown()

            # ---------------- Tab 3：内部结构 ----------------
            with gr.Tab("③ 内部结构"):
                gr.Markdown(
                    "#### 每个 skill 导出成多个 tool\n"
                    "规划里说「Qwen 选择一个 skill」，实现上把一个 skill 拆成多个 tool"
                    "（`skill_action`）。原因是「一个大参数模型 + 一个 action 字段」的做法"
                    "实测会让 Qwen 漏填字段；拆开后每个 tool 的必填字段稳定，填参准确率更高。\n\n"
                    "下面就是程序交给 Qwen 的完整工具清单（由注册表自动生成）。"
                )
                gr.Dataframe(
                    headers=["工具名", "必填参数", "给 Qwen 的说明"],
                    value=_tools_rows(),
                    wrap=True,
                    show_label=False,
                )
                with gr.Accordion("接真 Qwen 时只改一处", open=False):
                    gr.Markdown(
                        "本演示用 `webapp/sim_qwen.py` 的规则版意图识别顶替 Qwen，"
                        "**输出格式与真 Qwen 的 tool_call 一致**。接真模型时只改 `parse()`：\n\n"
                        "```python\n"
                        "# 现在（模拟）：规则版意图识别\n"
                        "decision = sim_qwen.parse(text)\n\n"
                        "# 接真模型后：\n"
                        "resp = client.chat.completions.create(\n"
                        "    model='Qwen2.5-7B-Instruct',\n"
                        "    messages=[{'role': 'system', 'content': SYSTEM_PROMPT},\n"
                        "              {'role': 'user', 'content': text}],\n"
                        "    tools=skills.export_qwen_tools(),   # 就是界面第三页那张表\n"
                        ")\n"
                        "```\n\n"
                        "下游的「查注册表 → Pydantic 校验 → 执行 → 回话」一行都不用改。"
                    )

            # ---------------- Tab 4：待对齐细节 ----------------
            with gr.Tab("④ 待对齐细节 ⚠️"):
                gr.Markdown(
                    "### ⚠️ 三个人一起过一遍\n"
                    "下面是**做这个演示时暴露出的接口不一致处**：都是"
                    "`docs/接口约定.md` 里已经定稿但还没落实的条款，"
                    "或者约定没写、但三个 skill 必须统一的地方。\n\n"
                    "每条都标了**证据（哪个文件第几行）**和**建议改法**，可以直接照着改。"
                    "改完请勾上对应条目并在群里说一声。"
                )
                gr.Markdown("#### 🔎 实时核对：`confirm_level` 谁设了谁没设")
                gr.Dataframe(
                    headers=["skill", "代码里出现的确认级别", "状态"],
                    value=_confirm_level_rows(),
                    wrap=True,
                    show_label=False,
                )
                gr.Markdown(_alignment_md())

        # ---------------- 事件绑定 ----------------
        msg.submit(
            on_send,
            inputs=[msg, chatbot],
            outputs=[chatbot, msg, trace_view, events_view, notif_view],
        )
        send_btn.click(
            on_send,
            inputs=[msg, chatbot],
            outputs=[chatbot, msg, trace_view, events_view, notif_view],
        )
        reset_btn.click(
            on_reset,
            outputs=[chatbot, trace_view, events_view, notif_view],
        )
        due_btn.click(on_due, inputs=[due_input], outputs=[due_out])

    return demo


def _launch(app) -> None:
    """启动服务。css 在 Gradio 6 才作为 launch 参数传入。

    ⚠️ 端口为什么不用默认的 7860：
    Windows 上装了安卓模拟器 / 启用 Hyper-V / WSL 后，系统会【保留】若干 TCP 端口段
    （可用 `netsh interface ipv4 show excludedportrange protocol=tcp` 查看），
    绑到保留段里的端口会直接抛 PermissionError(10013)，表现为「所有端口都被占用」。
    实测这台机器的保留段包含 7845-7944，正好覆盖 Gradio 默认的 7860。
    所以这里从 8000 起逐个试，跳过被保留/占用的端口。
    """
    import gradio as gr

    major = int(gr.__version__.split(".")[0])
    base: dict = {"server_name": "127.0.0.1"}
    if major >= 6:
        base["css"] = _CSS
    else:
        base["show_api"] = False

    candidates = [8000 + i for i in range(40)] + [8800 + i for i in range(20)]
    last_error: Exception | None = None
    for port in candidates:
        try:
            print(f"[webapp] 尝试启动 http://127.0.0.1:{port}/ ...")
            app.launch(server_port=port, **base)
            return
        except OSError as exc:  # 端口被保留或被占用，换下一个
            last_error = exc
            continue
    raise RuntimeError(f"候选端口都不可用：{last_error}")


if __name__ == "__main__":
    _launch(build_app())
