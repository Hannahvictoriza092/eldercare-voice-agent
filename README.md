# 老人语音助手 · Skill 库

面向独居老人的语音助手。老人说一句话，系统转成文字，由大模型判断意图，
调用对应的 skill 并校验参数，最后把结果念回给老人。

```
老人语音 → ASR 转文字 → Agent 判断意图/风险 → 调用 skill → 参数校验 → 执行 → 语音反馈
```

---

## 一、三个人负责什么

| 模块 | 文件夹 | 负责人 | 状态 |
|---|---|---|---|
| **用药提醒** | `skills/medication_reminder/` | 我 | ✅ 已完成 |
| **呼救** | `skills/emergency_call/` | 队友 A | 🚧 待实现 |
| **健康和照顾反馈** | `skills/health_report/` | 队友 B | 🚧 待实现 |
| **共享契约层** | `common/` | 三人共同 | ⚠️ 草案待定稿 |

> 📌 每个 skill 文件夹下都有一份 `README.md`，写清了那个模块要做什么、怎么开工。
> **先读自己文件夹里的 README。**

### 三个模块的依赖关系（重要）

它们不是平行的，是有数据依赖的：

```mermaid
flowchart LR
    M["用药提醒"] -->|"服药记录"| H["健康和照顾反馈"]
    E["呼救"] -->|"异常事件"| H
    H -->|"周报"| F["子女 / 医院"]
```

所以**健康反馈组是下游**，它的数据源是另外两组的产出。
这就是为什么必须有共享层 `common/`。

### 协作方式：平等，不需要审批

| 事项 | 我们的做法 |
|---|---|
| 谁能合并 PR | **自己合自己的**，不需要任何人批准 |
| `CODEOWNERS` | 只是「这块该找谁」的通讯录，**不强制审批** |
| 唯一的门槛 | **CI 测试必须通过**（机器把关） |
| 注册新 skill | 自己包里写 `SKILL = YourSkill()`，**不用改公共文件** |

详见 `CONTRIBUTING.md`。

---

## 二、目录结构

```
.
├── common/                       # ★ 共享契约层（三人共同维护，改前要打招呼）
│   ├── base.py                   #   BaseSkill / SkillResult / SkillContext / RiskLevel
│   ├── registry.py               #   注册表：程序查表、导出 Qwen schema
│   ├── domain.py                 #   数据实体 Person / MedicationLog / Incident / Notification
│   └── timefmt.py                #   时间口语化：08:00 → 「早上 8 点」
│
├── skills/                       # 各 skill 的私有领地
│   ├── __init__.py               #   自动发现（★ 谁都不需要改这个文件）
│   ├── medication_reminder/      #   ← 我负责
│   ├── emergency_call/           #   ← 队友 A（含 README 说明怎么开工）
│   └── health_report/            #   ← 队友 B（含 README 说明怎么开工）
│
├── tests/                        # 测试
├── docs/
│   ├── 接口约定.md                #   ★ 三人必须遵守的契约
│   └── reference/                #   项目规划截图
│
├── .github/
│   ├── CODEOWNERS                #   ⚠️ 需替换成真实 GitHub 用户名
│   ├── pull_request_template.md
│   └── workflows/ci.yml          #   PR 自动跑测试
│
├── README.md                     # 本文件
├── CONTRIBUTING.md               # ★ Git 协作规范（分支、提交、冲突处理）
├── demo.py                       # 端到端演示（不接真实 Qwen 也能跑）
├── qwen_tools.py                 # 导出 Qwen 的 tools JSON
├── pyproject.toml
└── requirements.txt
```

---

## 三、快速开始

```bash
pip install -r requirements.txt

python -m pytest        # 跑测试，应该 46 passed
python demo.py          # 看完整链路演示（8 个场景）
```

环境：Python 3.10+（开发用 3.12）+ Pydantic 2.x，没有其它依赖。

### 常用命令

```bash
python qwen_tools.py            # 导出 Qwen 的 tools 数组
python qwen_tools.py --index    # 只导出 skill 清单（塞 system prompt 用）
python qwen_tools.py --write    # 写到 data/qwen_tools.json

python -c "import skills; print([s.name for s in skills.all_skills()])"   # 看注册了哪些 skill
```

---

## 四、我该从哪开始

| 你是谁 | 第一步 |
|---|---|
| **队友 A（呼救）** | 读 `skills/emergency_call/README.md` |
| **队友 B（健康反馈）** | 读 `skills/health_report/README.md`，⚠️ **先跟队友确认共享事件流怎么读**，那是你的阻塞点 |
| **所有人** | 读 `docs/接口约定.md`（契约）和 `CONTRIBUTING.md`（Git 规范） |

### 新人上手最快的路径

1. 跑一遍 `python demo.py`，理解整条链路
2. 读 `common/base.py` 的注释，理解一个 skill 长什么样
3. 打开 `skills/medication_reminder/schema.py`，看参数模型和校验规则怎么写
4. 复制 `medication_reminder/` 的 5 个文件到自己的文件夹，改造成自己的业务

**不要从零开始写**——照着 `medication_reminder` 的结构走，就不会和别人的对不上。

---

## 五、核心设计（为什么这么写）

### 1. 一份定义，两边使用

参数模型用 Pydantic 写一次，同时服务两个用途：

| 用途 | 方式 |
|---|---|
| 程序校验参数 | `Model.model_validate(...)` |
| 生成 Qwen 的 tool schema | `Model.model_json_schema()` |

**所以字段的 `description` 是写给 Qwen 看的，不是注释。**
Qwen 填参准不准，直接取决于这段文字写得好不好。

### 2. 一个 skill 拆成多个 tool

规划里说「Qwen 选择一个 skill」，但实现上一个 skill 会导出成多个 tool：

```
medication_reminder_create / _query / _update / _cancel / _confirm_taken
```

原因：如果用「一个大参数模型 + 一个 action 字段」，Qwen 会看到一堆
「只有某个 action 才必填」的字段，实测容易漏填。拆成独立 tool 后
`required` 变得稳定，填参准确率高很多。但仍然保持「一个 skill」的粒度，符合规划。

### 3. 参数校验分两层

- **第一层**：Pydantic 管类型、范围、必填、枚举
- **第二层**：`model_validator` 管跨字段规则

跨字段规则是最容易出错的地方，比如「说一天吃三次，却只给了两个时间点」——
这类错误必须程序拦住，不能指望 Qwen 自己发现。

**校验失败不是报错崩掉，而是转成一句追问话术**回给老人。
因为老人说的信息本来就常常不全，追问是正常流程，不是异常。

### 4. 已经踩过的坑

| 坑 | 处理方式 |
|---|---|
| Pydantic 把枚举输出成两层 `$ref`，Qwen 读不全 | `flatten_schema()` 展平 |
| 字段名叫 `date` 会遮蔽 `datetime.date` 类型 | 用 `DateType` 别名 |
| 把 `2026-09-19` 直接念给老人听 | `timefmt.day_cn()` → 「今天」 |
| 靠报错文本猜是哪个字段错了会猜错 | 用 Pydantic 的 `loc` 精确定位 |

---

## 六、当前待办

### 🔴 阻塞点（三个人一起定，越早越好）

- [ ] `Person.id` 的规则 —— 现在 `person` 是裸字符串，取值可能是 ID 也可能是姓名，**这是个隐患**
- [ ] 共享事件流存哪、怎么读 —— **队友 B 的阻塞点**
- [ ] 把 `CODEOWNERS` 里的 `@your-github-id` 换成真实 GitHub 用户名

### 🟠 待办

- [ ] `SkillResult` 增加 `confirm_level` / `notifications` 字段
      （现在是藏在 `data` 里的 `require_confirm_back` / `notify_family`，靠约定不靠谱）
- [ ] 用药提醒的 `taken_log` 改成完整事件流（含漏服记录），否则健康反馈组读不到漏服数据

### 🟡 后期

- [ ] 真实 Qwen 接入（用 `qwen_tools.py --write` 的输出拼 DashScope 的 tools 参数）
- [ ] 存储换成数据库
- [ ] 定时调度器（每分钟调 `due_reminders()`，负责播报和去重）
- [ ] 药品名标准化（老人说「降压药」，需要别名表映射到具体药名）
- [ ] 药物相互作用检查（医疗安全，建议后期做）

---

## 七、文档索引

| 文档 | 什么时候看 |
|---|---|
| `docs/接口约定.md` | 写代码前必看，三人契约 |
| `CONTRIBUTING.md` | 第一次提交代码前，以及遇到冲突时 |
| `skills/*/README.md` | 开工前看自己那份 |
| `common/domain.py` 的注释 | 需要老人/事件/通知这些实体时 |
