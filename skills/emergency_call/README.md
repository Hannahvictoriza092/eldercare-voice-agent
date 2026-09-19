# 呼救 skill

> 📄 **第一次动手先看 `docs/上手指南.md`**（4 步搞定环境，10 分钟）。
> 这份文档讲业务设计，那份讲怎么把代码跑起来。

> 代码写在 `skills/emergency_call/` 这个文件夹里就行。
> `common/` 是三个人一起用的，要动的话先在群里说一声。

---

## 一、这个 skill 要实现的功能

来自项目规划：

> 第二个是呼救，除了呼救以外，老人问「救助来了吗」，还可以查询救助进度给出反馈。

拆成两件事：

1. **老人说「救命」「我不舒服」→ 发起呼救**
2. **老人问「救助来了吗」「人来了没有」→ 查进度并给出反馈**

补充考虑（建议一并做）：
3. 老人说「我没事，按错了」→ **取消呼救**（误报处理，很重要）
4. 老人确认自己安全 → **报平安**（避免家属白跑一趟）

---

## 二、需要哪些文件（照 `medication_reminder/` 的样子建）

```
skills/emergency_call/
├── __init__.py      # 导出 Skill 类
├── schema.py        # 参数模型 + 校验规则
├── executor.py      # 业务逻辑
├── messages.py      # 语音话术（呼救的语气和用药提醒完全不同！）
└── skill.py         # 继承 BaseSkill，填 ACTIONS，实现 execute
```

**最省事的做法**：把 `medication_reminder/` 那 5 个文件复制过来，把内容替换成这个 skill 的业务。
结构照着走，比较容易和大家对上。

---

## 三、需要留意的约定（不一致会导致三个 skill 拼不到一起）

```python
from common import BaseSkill, RiskLevel, SkillContext, SkillResult
from common.domain import Incident, IncidentStatus, IncidentType, Notification
```

| 约定 | 说明 |
|---|---|
| 类属性 `name` | 固定填 `"emergency_call"`，**定下来之后建议不要再改**（会进 Qwen prompt、日志、数据库） |
| `display_name` | `"呼救"` |
| `risk_level` | 填 `RiskLevel.HIGH`（呼救失败会出人命） |
| `ACTIONS` | `{action名: 参数模型}`，每个字段**记得写 `description`**（Qwen 靠它填参） |
| `execute()` | 返回 `SkillResult`，**尽量别抛异常**（用 `try/except` 兜住） |
| 念给老人的话 | 统一走 `SkillResult.speech` 字段，在别处拼容易漏掉语气统一 |
| `followup_for(action, exc, field_name)` | 签名照抄，用来生成追问话术 |
| tool 名 | 自动生成为 `emergency_call_trigger` 这种，不用手动管 |

---

## 四、可以直接复用的东西

| 复用对象 | 位置 | 用途 |
|---|---|---|
| `Incident` / `IncidentStatus` | `common/domain.py` | **事件状态机已经有现成的**，「救助来了吗」直接读 `status_history` 就行 |
| `Incident.progress_cn()` | `common/domain.py` | 已经把状态翻译成「救助的人已经在来的路上了」这类话，可以按实际流程改写 |
| `Notification` | `common/domain.py` | 通知家属/医院/社区。**只产出对象就行，不用管怎么发** |
| `timefmt.ago_cn()` / `in_future_cn()` | `common/timefmt.py` | 「10 分钟前出发的」「还有 5 分钟」 |
| `flatten_schema()` | `common/base.py` | 已经在基类里调用了，不用管 |

**不需要再定义一套事件状态枚举**——`IncidentStatus` 已经有了，健康和照顾反馈那边要读它。

---

## 五、Action 设计建议

| action | 触发话术 | 必填参数 | 风险 |
|---|---|---|---|
| `trigger` | 「救命」「快来人」「我摔倒了」 | 呼救原因、事发地点 | HIGH，**立即执行，不要二次确认** |
| `check_progress` | 「救助来了吗」「人到了没有」 | 事件 ID（可自动取最近一条） | LOW，纯查询 |
| `cancel` | 「我没事，按错了」 | 事件 ID、取消原因 | MEDIUM，**要复述确认** |
| `confirm_safe` | 「我没事了」 | 事件 ID | MEDIUM |

### 参数模型可以参考的字段（自己定就行，这里只提示别漏）

`trigger`：呼救原因（枚举：摔倒/胸闷/说不出话/其他）、地点、老人当前状态描述
`check_progress`：事件 ID、老人 ID

---

## 六、⚠️ 几个容易出问题的地方

1. **呼救不能有二次确认**。老人喊「救命」时系统要是回一句「您确定要呼救吗」，是要出事的。
   其他 skill 可以加确认，呼救不行。

2. **话术语气完全不同**。用药提醒可以温和（「该吃药啦」），呼救要**短、肯定、安抚**：
   - ✅ 「我马上叫人来，您别动，我陪着您。」
   - ❌ 「已为您创建呼救事件，正在处理中。」

3. **技术细节不要念给老人听**。像「事件 ID」「状态机」「超时」这种词都不合适。

4. **`cancel` 要防止老人误取消**。老人可能慌乱中点了取消，建议让家属也收到一条通知。

---

## 七、提交前可以过一遍

- [ ] `python -m pytest tests/ -q` 全绿（记得给自己写测试）
- [ ] `python -c "import skills; print([s.name for s in skills.all_skills()])"` 能看到 `emergency_call`
- [ ] `python qwen_tools.py` 导出的 tools 里有这个 skill 的工具，且每个字段都有 description
- [ ] `execute()` 在任何异常下都返回 `SkillResult` 而不是抛出去
- [ ] 没有 import 其他 skill 的私有模块（`skills.medication_reminder.*`）

---

## 八、开工第一步

1. 复制 `medication_reminder/` 的 5 个文件过来，改造成这个 skill 的业务
2. 在自己的 `__init__.py` 里加两行（这就是注册动作，**不用改任何公共文件**）：

   ```python
   from .skill import EmergencyCallSkill
   SKILL = EmergencyCallSkill()
   ```

3. 验证一下被扫到了：

   ```bash
   python -c "import skills; print(skills.all_skills()); print('跳过:', skills.skipped_packages())"
   ```

   这个 skill 应该出现在 `all_skills()` 里，而不是 `skipped` 里。

4. 先跑通一个最简单的 `trigger`（哪怕只返回一句固定的话），再逐步加功能
5. 有疑问的地方，去 `docs/接口约定.md` 找，或者直接问

> 💡 `skills/__init__.py` 是自动发现的，**不用改它**，所以不会和别人冲突。
