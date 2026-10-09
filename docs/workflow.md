# Workflow：由模型控制的循环

![Workflow 图](workflow.svg)

下面保留可编辑 Mermaid 源码；另有同名 PNG 导出。

```mermaid
flowchart TD
  Start[登录用户手动触发 / 每日定时触发] --> Queue[持久化任务\n同日摘要 + slot + 活跃任务去重]
  Queue --> Claim[Worker 原子领取\n固定身份与偏好快照]
  Claim --> Model[DeepSeek 自主决策\n可返回任意合法工具调用或最终回答]
  Model --> Decision{返回 tool_calls?}
  Decision -->|是| Budget{轮数 / 调用数 / 时间 / 上下文预算}
  Budget -->|允许| Guard[校验工具名 · 参数 · 权限 · 来源]
  Guard --> Execute[按模型选择执行工具]
  Guard -->|拒绝| Observation[结构化工具结果或错误]
  Execute --> Observation
  Observation --> Trace[(记录实际 Trace)]
  Trace --> Model
  Budget -->|超出| Failed[failed\n保留已有证据]
  Decision -->|否| Validate{日报保存且所需推送已入队?}
  Validate -->|是| Completed[completed]
  Validate -->|否| Incomplete[incomplete\n不能以模型口头回答冒充交付]
  Execute -. send_digest .-> Outbox[(发件箱唯一键\ndigest_id + channel)]
  Outbox --> Recheck{渠道仍启用?}
  Recheck -->|否| Cancelled[cancelled]
  Recheck -->|是| Deliver[站内事务 / SMTP]
  Deliver --> Sent[sent / failed / uncertain]
```

## 为什么不是固定流水线

`backend/app/agent/graph.py` 只定义 `model → tools → model` 与条件结束。没有 `search → fetch → summarize → send` 的硬编码边。模型可以先读偏好、列文件，也可以再次搜索、连续抓取、读取笔记、根据错误重新调用；多个工具调用也保留模型选择的顺序。

离线测试将两种工具顺序输入同一图，验证调用顺序确实变化；它只是协议测试替身。真实运行证据在 `evidence/live-e2e.json`，包含供应商 response_id、实际模型名、Token 用量和工具参数，不能由离线替身生成。

## 业务数据依赖并非写死流程

`fetch_article` 只允许本轮已发现的 URL；`save_digest` 只接受本轮已抓取文章的 ID 和逐字证据；`send_digest` 只允许本轮已经保存的日报。这些是授权和事实依据的前置条件，不替模型决定搜索词、文章选择、重试方式或调用顺序。
