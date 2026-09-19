# 健康和照顾反馈 skill

> 📄 **第一次动手先看 `docs/上手指南.md`**（4 步搞定环境，10 分钟）。
> 这份文档讲业务设计，那份讲怎么把代码跑起来。

> 代码写在 `skills/health_report/` 这个文件夹里就行。
> `common/` 是三个人一起用的，要动的话先在群里说一声；
> 另外**建议不要 import 其他 skill 的私有模块**（原因见第六节）。

---

## 一、这个 skill 要实现的功能

来自项目规划：

> 第三个功能就是每周老人的行为记录，生成一个摘要反馈给医院和子女，自动建立一个个性化档案。

拆成三件事：

1. **每周行为记录** —— 汇总老人这一周做了什么
2. **生成摘要 → 反馈给医院和子女**
3. **自动建立个性化档案** —— 长期积累的老人画像

---

## 二、⚠️ 先说最关键的：这个 skill 在「下游」

这个 skill 和另外两个**不是平行关系**，要依赖它们的产出：

```mermaid
flowchart LR
    M["用药提醒"] -->|服药记录 MedicationLog| H["健康反馈"]
    E["呼救"] -->|异常事件 Incident| H
    H -->|"周报摘要"| F["子女"]
    H -->|"周报摘要"| G["医院"]
    H -->|"长期积累"| P["个性化档案"]
```

**这意味着**：这里没法自己造数据，只能**消费**其他两个 skill 产出的数据。

所以做法是：
- ✅ 从共享事件流读 `MedicationLog` 和 `Incident`
- ❌ 不建议 `from skills.medication_reminder.store import ReminderStore` 去读别的 skill 的私有文件

后者看起来能用，但只要用药提醒那边改一下存储结构，这边就崩了——这是最典型的耦合。

> 🔴 **动手前最好先确认**：共享事件流存在哪里、用什么接口读。
> 这个还没定（`common/domain.py` 里是草案）。**建议先和另外两人把这件事定下来再动手**，
> 否则容易写出一堆要返工的代码。

---

## 三、需要哪些文件（照 `medication_reminder/` 的样子建）

```
skills/health_report/
├── __init__.py      # 导出 Skill 类
├── schema.py        # 参数模型 + 校验规则
├── executor.py      # 业务逻辑（汇总统计 + 生成文案）
├── messages.py      # 话术（周报是正式语气，不是口语！）
└── skill.py         # 继承 BaseSkill，填 ACTIONS，实现 execute
```

---

## 四、需要留意的约定

```python
from common import BaseSkill, RiskLevel, SkillContext, SkillResult
from common.domain import Person, MedicationLog, Incident, Notification, NotifyTarget
```

| 约定 | 说明 |
|---|---|
| 类属性 `name` | 固定填 `"health_report"`，**定下来之后建议不要再改** |
| `display_name` | `"健康和照顾反馈"` |
| `risk_level` | 建议 `RiskLevel.LOW`（周报是只读汇总，没有副作用） |
| `ACTIONS` | `{action名: 参数模型}`，每个字段**记得写 `description`** |
| `execute()` | 返回 `SkillResult`，**尽量别抛异常** |
| 念给老人的话 | 走 `SkillResult.speech`；**发给医院/子女的正式文案走 `Notification.body`，两者不一样** |
| `followup_for(action, exc, field_name)` | 签名照抄 |

---

## 五、Action 设计建议

| action | 触发话术 | 必填参数 | 说明 |
|---|---|---|---|
| `generate_weekly` | 「这周我表现怎么样」 | 老人 ID、周起始日 | 生成周报（可预览） |
| `send_report` | 「把周报发给医生/我儿子」 | 老人 ID、周起始日、接收方 | 走 `Notification` |
| `query_archive` | 「我上个月吃药怎么样」 | 老人 ID、时间范围 | 查个性化档案 |
| `query_summary` | 「我这周吃药按时吗」 | 老人 ID | 快速问答，当场答老人 |

### 周报里该统计什么（建议）

| 指标 | 数据来源 |
|---|---|
| 服药依从率（本周按时服药 X/Y 次） | `MedicationLog` |
| 漏服次数与具体药名 | `MedicationLog`（`status=MISSED`） |
| 异常事件次数（呼救/跌倒） | `Incident` |
| 与上周对比的变化趋势 | 上面两项按周聚合 |

---

## 六、⚠️ 几个容易出问题的地方

1. **建议不要 import 其他 skill 的私有模块**。
   ❌ `from skills.medication_reminder.store import ReminderStore`
   ✅ 通过共享事件流读取

2. **给老人听的话 ≠ 给医生看的报告**。
   - 给老人：「这周您吃药挺准时的，有两次忘了，下回注意哈。」
   - 给医生：「本周服药依从率 86.7%（13/15），漏服 2 次，均为晚间二甲双胍。」

3. **医疗措辞要谨慎**。这里做的是反馈，不是诊断。
   ❌「老人疑似阿尔茨海默，建议就医」
   ✅「本周出现 3 次漏服，较上周增加 2 次，供医生参考」

4. **隐私**。用药和健康记录是敏感个人信息，周报内容里身份证号、具体住址这些都不合适。

5. **周报生成尽量不要失败**。数据不全时给「数据不足」提示，不要抛错。

---

## 七、提交前可以过一遍

- [ ] `python -m pytest tests/ -q` 全绿
- [ ] `python -c "import skills; print([s.name for s in skills.all_skills()])"` 能看到 `health_report`
- [ ] 没有 import 任何 `skills.<其他 skill>.*`
- [ ] 数据为空时（新老人、没有记录）不崩溃，给出合理话术
- [ ] 周报数字算对（自己造几条假数据验算一遍）

---

## 八、开工第一步

1. 🔴 **先和另外两人确认共享事件流的读取方式**（这一步不定下来，后面容易返工）
2. 定下来之后，复制 `medication_reminder/` 的 5 个文件开始改造
3. 在自己的 `__init__.py` 里加两行（这就是注册动作，**不用改任何公共文件**）：

   ```python
   from .skill import HealthReportSkill
   SKILL = HealthReportSkill()
   ```

4. 验证一下被扫到了：

   ```bash
   python -c "import skills; print(skills.all_skills()); print('跳过:', skills.skipped_packages())"
   ```

5. 先用假数据把「生成周报」跑通，再接真实数据源

> 💡 `skills/__init__.py` 是自动发现的，**你永远不需要改它**，所以不会和别人冲突。
> 你的包现在还没写 `SKILL`，会被安静跳过——这样你不会影响另外两个人。
