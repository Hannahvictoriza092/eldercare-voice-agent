# 健康和照顾反馈 skill

## 当前职责

本模块消费另外两个 skill 产生的结构化业务记录：

- medication_reminder → MedicationLog（已服、漏服、跳过等）。
- emergency_call → Incident（呼救事件及状态历史）。
- health_report → 周报正文、每周档案快照、待发送 Notification。

调用参数只指定老人 ID、日期范围和接收方；记录由程序读取，不由大模型转抄。
不导入上游的私有 store；默认从 common.EventStore 读取 data/events.jsonl。
三个模块可以各持独立 EventStore 实例：上游写入成功后，下次查询会重新加载最新记录。
稳定 ID 去重保证补服覆盖漏服、呼救状态更新不会多计事件。

## 四个动作

| 动作 | 输入 | 结果 |
|---|---|---|
| generate_weekly | person_id、可选 week_start | 正式周报、统计及同周档案快照 |
| send_report | person_id、targets、可选 week_start | 待发送通知；不表示已送达 |
| query_archive | person_id、可选日期范围 | 已保存的周快照与趋势 |
| query_summary | person_id、可选 days | 近期记录摘要 |

只有呼救记录也能生成、发送及归档；两类记录都没有时返回 insufficient，不生成通知。
档案在生成/发送报告时更新；weekly_scheduler.py 会定期调用生成动作，无需等待查询。
运行方式见 ../../docs/自动周报调度.md。

## 统计口径与兼容

推荐使用以下输出字段（周报 stats、摘要 data、档案 snapshots）：

| 字段 | 定义 |
|---|---|
| record_count | 查询范围内已落库的服药记录总数，不是应服次数 |
| taken | 已服记录数，包括补服；不等于按时服用 |
| missed | 当前状态仍为漏服的记录数 |
| skipped / pending | 主动跳过 / 待确认记录数 |
| taken_ratio | taken / record_count × 100，保留一位小数；无记录时为 null |
| incidents | 异常事件数量，同一事件多次推进状态仍算一起 |

taken_ratio 只是已有记录中的已服占比，不代表按时率或计划完成率。
为兼容原调用方及历史 JSON 档案，planned、adherence 字段保留，分别与
record_count、taken_ratio 同值，但不可再按字段旧名称解释业务语义。
周报、摘要和趋势均使用新口径；没有服药记录的周不推断服药改善。

## 档案与运行边界

- 默认保存到 data/health_archives.json，以 person_id + week_start 更新同周快照。
- 重载时把嵌套快照恢复为 WeeklySnapshot；旧档案没有 skipped/pending 时默认 0。
- 保存先写临时文件，再替换正式文件。
- JSONL 查询每次全量重读，适合当前小规模单进程串行运行。
- 相同相对路径依赖相同工作目录；自定义路径时须传入指向同一文件的 EventStore。
- 尚不保证多进程并发写、跨文件事务、通知实际发送或后台调度。

## 验收

~~~bash
python -m pytest tests/test_skill_pipeline.py tests/test_event_store.py tests/test_health_report.py -q
python -m pytest -q
~~~

集成测试先创建三个独立模块，再实际创建提醒、确认服药、调用漏服调度、发起呼救，
最后验证实时统计、补服覆盖、人员/日期隔离、档案重载和跨周对比。
具体步骤见 ../../docs/闭环验收与修改记录.md。
