# 协作规范

三个人 + 一个仓库。核心只有一条：**main 要保持能用，但谁也不用等谁批准。**

---

## 一、我们是平等的，没有审核关系

| 事项 | 我们的做法 |
|---|---|
| 分支 | **不用建分支，直接推 `main`** |
| 谁能合并 | 自己的提交自己推，**不需要任何人批准** |
| `CODEOWNERS` 是什么 | 只是「这块出问题该找谁」的通讯录，**不强制审批** |
| 唯一的纪律 | 开工前 `git pull`，提交前跑 `pytest` |

> 为什么留 CI 这道门？因为它不给你们添麻烦——它只在代码真坏了的时候拦一下。
> 代码坏了影响的是整个小组的进度汇报，那时候解释起来更麻烦。

---

## 二、分支：就用 main，不用建分支

**结论：三个人都直接推 `main`。**

为什么不用分支？我们评估过，对你们这个规模**不划算**：

| | 分支 + PR | 直接推 main（我们的选择） |
|---|---|---|
| 防冲突 | 自动发现已经解决了，分支帮不上忙 | — |
| 防覆盖别人 | PR 机制 | **git 自己就会拦**（见下） |
| 代价 | 忘合并、重复干活、搞不清在哪个分支 | 几乎没有 |

**git 自带的保护**：如果队友先推了，你的 `push` 会被拒绝：

```
! [rejected]  main -> main (fetch first)
error: failed to push some refs
```

这不是坏了，是 git 在说"别人有新东西，你先拉下来"。照做就行（见第三节）。

### 什么时候才需要建分支

只有这三种情况值得开临时分支：

| 情况 | 例子 |
|---|---|
| 大重构，可能要几天 | 「把存储层从 JSON 换成 SQLite」 |
| 实验性尝试 | 「试试用另一个模型提示词，不行就回退」 |
| 要改 `common/` 的公共接口 | 「给 SkillResult 加字段」 |

其余情况（写自己的 skill、修 bug、改文档）**直接推 main**。

需要开的时候：

```bash
git checkout -b feat/你的功能名
# ...干活、提交...
git push -u origin feat/你的功能名
```

干完了就合回 main（在 GitHub 上开 PR 自己合，或者本地 `git checkout main && git merge feat/你的功能名`）。

> ⚠️ 分支别留太久。超过两三天没合，就容易和别人分叉太远，合并时会很痛。

### 分支命名

| 前缀 | 用途 | 例子 |
|---|---|---|
| `feat/` | 新功能 | `feat/emergency-trigger` |
| `fix/` | 修 bug | `fix/medication-time-parse` |
| `docs/` | 只改文档 | `docs/update-contract` |

---

## 三、日常流程（就这三步，照做就行）

```bash
# ① 开工前先拉最新的（最重要的一步！）
git pull

# ② 干活……

# ③ 提交前先自己验证（必须全绿）
python -m pytest

# ④ 提交并推送
git add -A
git commit -m "feat(emergency): 实现发起呼救"
git push
```

**就这四行，记住 `git pull` 在最前面。**

### push 被拒绝了怎么办

```
! [rejected]  main -> main (fetch first)
```

这不是出错，是 git 说"别人先推了新东西，你先拉下来"。照做：

```bash
git pull          # 拉下来并合并
git push          # 再推一次
```

如果 `git pull` 时说有冲突（`CONFLICT`），看第五节的「冲突怎么办」。

> 💡 **养成习惯**：每次 `git push` 之前先 `git pull`，能避免 90% 的麻烦。

### CI 红了怎么办

推送后 CI 会自动跑（看仓库页面的 **Actions** 标签，或你的邮箱）。
红了的话点进去看哪一步失败，常见原因：

| CI 报错 | 原因 |
|---|---|
| 测试失败 | 你改坏了别的模块，或自己的测试没过 |
| 缺少 description | 新增的参数字段没写 `description`，Qwen 会瞎填 |
| schema 导出失败 | 参数模型写错了（比如字段名和类型名撞车） |

**自己修，改完再推一次就行，不用等别人。**

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

**记住一句话就行：每次开工前 `git pull`。**

```bash
git pull        # 开工前 + push 前，各来一次
```

---

## 六、绝对不要做的事

| 🚫 | 为什么 |
|---|---|
| 提交 `data/` 里的数据文件 | 运行时生成的，已在 `.gitignore` 里 |
| 提交 `__pycache__`、`.pytest_cache` | 同上 |
| `git push -f` | 会把别人的提交冲掉，**永远不要用** |
| 提交密码、API Key | 推到 GitHub 后**删都删不干净**（历史里还在） |
| 长期不 pull | 冲突会越积越多，最后变成灾难 |
| 改完不跑测试就推 | 你坏了，别人 `pull` 下来也一起坏 |

---

## 七、仓库设置（管理员操作一次即可）

GitHub 仓库 → Settings：

| 位置 | 设置 |
|---|---|
| General → Default branch | `main` |
| Collaborators | 把两名队员加成 collaborator |
| General → Features → Wiki | 建议关掉（用 `docs/` 就好，两处文档容易对不上） |

**不需要开任何强制审核。** 原因：

1. GitHub 禁止自己批准自己的 PR，开了就变成互相盖章走形式
2. 我们三个人是平等的，不需要谁给谁背书
3. CI 已经能自动拦住坏代码，比人可靠

如果你想多一层保障，可以开 **`Require status checks`**（推送前测试必须绿）——
但这会要求走 PR 流程，和我们"直接推 main"的做法冲突，**建议先不用**。
等以后要改 `common/` 大接口时再说。

---

## 八、第一次推送

> ⚠️ **在国内直连 GitHub 常常失败**（`Connection was reset` 之类）。
> 遇到问题先看 **`docs/网络与Git配置.md`**，里面有针对本项目的排查过程，
> 结论是：**配一次 SSH，之后代理怎么变都不用管。**

```bash
git init -b main
git add -A
git commit -m "chore: 初始化项目结构"

git remote add origin git@github.com:Hannahvictoriza092/eldercare-voice-agent.git
git push -u origin main
```

> ⚠️ 在 GitHub 上新建仓库时**不要勾** "Add a README" / "Add .gitignore"，
> 否则会和你本地的初始提交冲突。

### 推送失败怎么办

```powershell
git remote -v                    # 确认是 git@github.com:... 而不是 https://
ssh -T git@github.com            # 应该显示 "Hi 你的用户名!"
```

详细的排查流程见 `docs/网络与Git配置.md`。

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
