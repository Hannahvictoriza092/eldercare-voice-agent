## 这个 PR 做了什么

<!-- 一句话说清楚。比如：完成呼救 skill 的发起呼救和进度查询 -->

## 我负责的模块

- [ ] 用药提醒（`skills/medication_reminder/`）
- [ ] 呼救（`skills/emergency_call/`）
- [ ] 健康和照顾反馈（`skills/health_report/`）
- [ ] 共享层（`common/`）—— ⚠️ 改这里需要另外两人都同意

## 检查清单

提 PR 前请逐条确认（CI 会自动跑测试，但下面这些 CI 查不出来）：

- [ ] `python -m pytest tests/ -q` 全绿
- [ ] 新增的参数字段**都写了 `description`**（Qwen 靠它填参）
- [ ] 我的 `execute()` 任何情况下都返回 `SkillResult`，不往外抛异常
- [ ] 我没有 import 别人 skill 的私有模块（只从 `common/` 导入）
- [ ] 我改了 `common/` 的话，已经在群里通知了另外两人
- [ ] 念给老人听的话里**没有英文、没有技术术语、没有 ISO 日期格式**
- [ ] 提交前执行过 `git pull --rebase`，没有未解决的冲突

## 我改了哪些文件

<!-- 列出主要文件，方便 reviewer 快速定位 -->

## 有没有需要别人知道的变化

<!-- 
比如：
- 我改了 common/domain.py 里 Incident 的一个字段
- 我新增了一个共享工具函数
- 我的 skill 需要一个新的环境变量

没有就写「无」。
-->

## 相关 issue

<!-- 关联 issue，没有就删掉这一节。比如 Closes #3 -->
