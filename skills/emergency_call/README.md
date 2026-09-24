# 呼救 skill

老人说“救命”“摔倒了”等紧急话语时，调用 `emergency_call_trigger`。
原因、地点、状态都可以暂时未知；不要为了补参数延迟发起。老人问“救助来了吗”
时调用 `emergency_call_check_progress`，默认查询本人最近一次呼救。

| 动作 | 行为 |
|---|---|
| `trigger` | 立即创建 `Incident`，生成紧急 `Notification` |
| `check_progress` | 查询真实写入的状态和预计到达时间 |
| `cancel` | 先追问确认，确认后标记误报并生成取消通知 |
| `confirm_safe` | 确认老人安全后结束事件并生成报平安通知 |

## 接入边界

本 skill 只返回待发送通知，不负责电话、短信或微信发送。`trigger` 返回的
`SkillResult.notifications` 是 `Notification` 对象列表（一等字段，不再是字典）；
`notification_pending=true` 说明尚待出站服务处理。上层必须发送并处理重试，
在接到真实救援反馈后调用 `EmergencyCallExecutor.update_status()` 写入
`ACKED`、`EN_ROUTE`、`ARRIVED` 等状态。未接到反馈前，进度查询只会说
“尚未收到接单消息”，不会声称有人已出发。

`EmergencyStore` 默认存储在 `data/emergency_incidents.json`，构造时可注入路径。
它的 `incidents(person_id, start, end)` 可为健康周报提供异常事件；正式的
跨模块事件流已由 `common/event_store.py` 的 `EventStore` 统一承载。

## 验证

```bash
python -m pytest -q
python qwen_tools.py --index
```

当前库没有真实的呼叫和通知网关，因此不能把这部分当作已经接通 120 的系统。
