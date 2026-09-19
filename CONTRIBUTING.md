# 协作规范

三个人 + 一个仓库，规则越简单越能执行。

---

## 一、分支模型

```
main  ←── 只放能跑的代码，受保护，不许直接 push
 │
 ├── feat/medication-xxx     ← 你（用药提醒）
 ├── feat/emergency-xxx      ← 队友 A（呼救）
 └── feat/report-xxx         ← 队友 B（健康和照顾反馈）
```

**规则**：
- `main` 上必须始终能跑通测试
- 每个人只在自己分支上干活
- 通过 PR 合进 `main`，CI 绿了才能合

### 分支命名

| 前缀 | 用途 | 例子 |
|---|---|---|
| `feat/` | 新功能 | `feat/emergency-trigger` |
| `fix/` | 修 bug | `fix/medication-time-parse` |
| `docs/` | 只改文档 | `docs/add-api-contract` |

---

## 二、日常流程（每天照做就行）

```bash
# 1. 同步最新代码（每天开工前 + 提交前各一次）
git checkout main
git pull
git checkout feat/xxx你的分支
git rebase main            # 把别人的改动接到自己分支下面

# 2. 干活

# 3. 提交
git add -A
git commit -m "feat(emergency): 实现发起呼救"

# 4. 推送
git push
```

---

## 三、提交信息格式

```
<类型>(<模块>): <做了什么>
```

| 类型 | 用途 |
|---|---|
| `feat` | 新功能 |
| `fix` | 修 bug |
| `docs` | 只改文档 |
| `refactor` | 重构，不改功能 |
| `test` | 加测试 |
| `chore` | 杂项（配置、依赖） |

**模块**填你负责的那块，方便一眼看出来是谁改的：

```bash
git commit -m "feat(medication): 支持按需服用的药"
git commit -m "feat(emergency): 实现救助进度查询"
git commit -m "fix(health_report): 修复周报漏服次数统计错误"
git commit -m "docs(common): 补充 domain 字段说明"
```

> 💡 **不要**写「更新」「修改」「提交」这种没有信息的 message。三个月后你自己看不懂。

---

## 四、⚠️ 冲突高发区

### 高危 1：`skills/__init__.py`

三个人都要改这个文件（加自己那两行注册代码），**必冲突**。

**预防**：只在你那两行上改，不要重排、不要格式化别人的行。

**真冲突了怎么办**：内容其实不冲突，保留所有人的就行：

```python
# 冲突标记长这样：
<<<<<<< HEAD
from .emergency_call import EmergencyCallSkill
register(EmergencyCallSkill())
=======
from .health_report import HealthReportSkill
register(HealthReportSkill())
>>>>>>> feat/your-branch
```

**正确处理**（两段都留）：
```python
from .emergency_call import EmergencyCallSkill
register(EmergencyCallSkill())

from .health_report import HealthReportSkill
register(HealthReportSkill())
```

### 高危 2：`common/` 下的任何文件

这里是共享契约，改动会影响三个人。

**规则**：改之前**必须在群里说一声**，PR 要三个人都 review。

### 高危 3：`requirements.txt`

**规则**：加依赖前先在群里说，避免三个人各加一个重复的库。

---

## 五、绝对不要做的事

| 🚫 | 为什么 |
|---|---|
| 直接 push 到 `main` | 会让别人拿到跑不起来的代码 |
| 改别人文件夹里的文件 | 别人的领地，要改先沟通 |
| 提交 `data/` 里的数据文件 | 是运行时产生的，已在 `.gitignore` 里 |
| 提交 `__pycache__`、`.pytest_cache` | 同上 |
| 用 `git push -f` 推公共分支 | 会把别人提交的东西冲掉 |
| 提交密码、API Key | 上 GitHub 后是公开的，**删都删不干净** |

---

## 六、PR 流程

1. 推分支 → GitHub 上点 **Compare & pull request**
2. PR 模板会自动出现，照着填
3. CI 自动跑测试，**红了先修，别求 review**
4. `CODEOWNERS` 会自动指派对应的人来 review
5. 至少一个人 approve → **Squash and merge** 合并
6. 合并后删掉自己的分支

### 合并方式统一用 Squash

好处：`main` 上每个功能只有一条提交记录，历史干净，回滚方便。

---

## 七、仓库设置建议（组长操作）

在 GitHub 仓库页面：

| 位置 | 设置 |
|---|---|
| Settings → General → Default branch | 改成 `main` |
| Settings → Branches → Add rule | 保护 `main`：勾选 Require pull request、Require status checks（选 CI） |
| Settings → Collaborators | 把两名队员加成 collaborator |
| Settings → General → Features | 关掉 Wiki（用 `docs/` 就好，避免两处文档对不上） |

保护 `main` 是最重要的一条——**能防止有人不小心把半成品推上去**。

---

## 八、第一次推送仓库

```bash
# 在项目根目录
git init -b main

# 确认 .gitignore 生效了（data/、__pycache__ 不该出现）
git status

git add -A
git commit -m "chore: 初始化项目结构"

# 在 GitHub 上新建空仓库（不要勾 README/gitignore），然后：
git remote add origin https://github.com/你的用户名/仓库名.git
git push -u origin main

# 建自己的分支
git checkout -b feat/medication-xxx
git push -u origin feat/medication-xxx
```

> ⚠️ 新建 GitHub 仓库时**不要勾选** "Add a README" / "Add .gitignore"，
> 否则会和你本地的初始提交冲突。
