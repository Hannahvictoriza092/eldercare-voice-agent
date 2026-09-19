# 协作规范

三个人 + 一个仓库。核心只有一条：**main 要保持能用，但谁也不用等谁批准。**

---

## 一、我们是平等的，没有审核关系

| 事项 | 我们的做法 |
|---|---|
| 谁能改代码 | 三个人都能改任何地方（但最好只改自己的模块） |
| 谁能合并 PR | **自己合自己的**，不需要别人批准 |
| `CODEOWNERS` 是什么 | 只是「这块出问题该找谁」的通讯录，**不强制审批** |
| 唯一的门槛 | **CI 测试必须通过**（机器把关，不是人把关） |

> 为什么留 CI 这道门？因为它不给你们添麻烦——它只在代码真坏了的时候拦一下。
> 代码坏了影响的是整个小组的进度汇报，那时候解释起来更麻烦。

---

## 二、分支模型

```
main  ←── 只放能跑的代码（CI 自动守着）
 │
 ├── feat/medication-xxx     ← 你（用药提醒）
 ├── feat/emergency-xxx      ← 队友 A（呼救）
 └── feat/report-xxx         ← 队友 B（健康和照顾反馈）
```

`main` 受保护，但**不是因为有人要审核你**，而是为了：

- ✅ 只接受 PR 合入（让 CI 先跑一遍）
- ✅ CI 必须绿
- ❌ **不需要任何人的批准** ← 关键

自己开的 PR 自己点「Squash and merge」，全程不用等谁。

### 分支命名

| 前缀 | 用途 | 例子 |
|---|---|---|
| `feat/` | 新功能 | `feat/emergency-trigger` |
| `fix/` | 修 bug | `fix/medication-time-parse` |
| `docs/` | 只改文档 | `docs/update-contract` |

---

## 三、日常流程（每天照做就行）

```bash
# 1. 开工前先同步（每天至少一次）
git checkout main
git pull
git checkout -b feat/你的新功能    # 新功能就建新分支

# 2. 干活

# 3. 本地先自己验证（必须全绿再提交）
python -m pytest

# 4. 提交
git add -A
git commit -m "feat(emergency): 实现发起呼救"

# 5. 推送
git push -u origin feat/emergency-trigger
```

然后去 GitHub 点 **Compare & pull request** → 等 CI 变绿 → **自己点 Squash and merge**。

### 卡在 CI 上了怎么办

看 Actions 页面的红色 ✗，点进去看哪一步失败。常见原因：

| CI 报错 | 原因 |
|---|---|
| 测试失败 | 你改坏了别的模块，或自己的测试没过 |
| 缺少 description | 新增的参数字段没写 `description`，Qwen 会瞎填 |
| schema 导出失败 | 参数模型写错了（比如字段名和类型名撞车） |

**自己修就行，不用等别人。**

---

## 四、提交信息格式

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

## 五、冲突怎么办

好消息：**最容易冲突的文件已经被消灭了。**

`skills/__init__.py` 原本三个人都要改（加自己那两行注册代码），必冲突。
现在改成**自动发现**——只要你的包里写了 `SKILL = YourSkill()`，
系统自己扫到，谁都不用碰公共文件。

还剩下的冲突点：

### 1. `common/` 下的文件

三个人共用的契约，真可能改到同一行。

**规则**：改之前在群里说一声「我要改 `common/domain.py` 的 Incident」。
说了基本就不会撞。

**真冲突了**，通常是因为两个人加了不同的字段，两边都留住就行：

```python
<<<<<<< HEAD
severity: Literal["low", "medium", "high", "critical"] = "high"
=======
location: str | None = None
>>>>>>> feat/your-branch
```

**正确处理**（都保留，去掉冲突标记那三行）：
```python
severity: Literal["low", "medium", "high", "critical"] = "high"
location: str | None = None
```

### 2. `requirements.txt`

**规则**：加依赖前先在群里说，避免三个人各加一个重复的库。

### 怎么减少冲突

```bash
git checkout main
git pull                    # 每天至少一次
git checkout 你的分支
git rebase main             # 把别人的改动接到自己分支下面
```

---

## 六、绝对不要做的事

| 🚫 | 为什么 |
|---|---|
| 提交 `data/` 里的数据文件 | 运行时生成的，已在 `.gitignore` 里 |
| 提交 `__pycache__`、`.pytest_cache` | 同上 |
| `git push -f` 推 main | 会把别人的提交冲掉 |
| 提交密码、API Key | 推到 GitHub 后**删都删不干净**（历史里还在） |
| 长期不 pull | 冲突会越积越多，最后变成灾难 |

---

## 七、要不要开「强制审核」？——不要

GitHub 有个设置叫 `Require review from Code Owners`。**不建议开**，原因：

1. **GitHub 禁止自己批准自己的 PR**。三个人各管各的模块，谁提交谁就得等别人来看，
   而别人未必懂你那块 → 最后变成走形式的乱点「Approve」。
2. 我们本来就平等，不需要谁给谁背书。
3. CI 比人可靠：人会走神，测试不会。

只开 **`Require status checks`**（CI 必须绿）就够了。

---

## 八、仓库设置（管理员操作一次即可）

GitHub 仓库 → Settings：

| 位置 | 设置 |
|---|---|
| General → Default branch | `main` |
| Branches → Add branch protection rule | 见下表 |
| Collaborators | 把两名队员加成 collaborator |
| General → Features → Wiki | 建议关掉（用 `docs/` 就好，两处文档容易对不上） |

### Branch protection rule 怎么勾

```
Branch name pattern: main

✅ Require a pull request before merging
   └─ Require approvals: 0                        ← ★ 关键：不要求任何人批准
   └─ ❌ Require review from Code Owners           ← 一定不要勾

✅ Require status checks to pass before merging
   └─ 选上 CI / 跑测试

❌ Allow force pushes        ← 关掉
❌ Allow deletions           ← 关掉
```

`Require approvals: 0` + `Require status checks` 的组合效果：
**谁都能自己合自己的 PR，但必须测试通过。**

---

## 九、第一次推送

```bash
git init -b main
git add -A
git commit -m "chore: 初始化项目结构"

git remote add origin https://github.com/Hannahvictoriza092/eldercare-voice-agent.git
git push -u origin main
```

> ⚠️ 在 GitHub 上新建仓库时**不要勾** "Add a README" / "Add .gitignore"，
> 否则会和你本地的初始提交冲突。

---

## 十、给两名队友的提醒

```bash
git clone https://github.com/Hannahvictoriza092/eldercare-voice-agent.git
cd eldercare-voice-agent
pip install -r requirements.txt
python -m pytest          # 应该全绿
python demo.py            # 看看整条链路
```

然后读 `skills/你的模块/README.md`。
**你写代码的位置就在那个文件夹里，不需要改任何公共文件。**
