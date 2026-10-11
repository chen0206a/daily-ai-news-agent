# 3 分钟笔试演示脚本

## 演示前准备（不计时）

按README启动服务。私有账号仅在本机 `evidence/private/final-2026-10-11/demo-login.json`，输入后关闭文件，不投屏密钥、密码、Cookie或开发日志。当前真实任务已经完成：**10轮DeepSeek、13次工具、3条新闻、1条站内通知**；这是单次观测，不是固定流程。

打开Daybreak、`backend/app/agent/graph.py`及README/最终验收。真实模型和联网延迟不保证能在三分钟内再次完成。新机器没有私有账号，需配置自己的密钥并提前跑真实验收：

```powershell
# 服务运行后，在frontend目录；该命令实际消耗DeepSeek额度：
$env:RUN_FINAL_LIVE='1'
$env:LIVE_RSS_BROWSER='1'
$env:EVIDENCE_DIR='../evidence/my-live-demo'
$env:LIVE_PRIVATE_DIR='../evidence/private/my-live-demo'
npm run test:e2e -- tests/final-live.spec.ts
```

已有输出会拒绝覆盖，请选择新目录。项目根目录也可执行 `python scripts/live_e2e.py --output-dir evidence/my-cli-live`，这是API版本演示，私有登录在 `evidence/private/my-cli-live/`。公开截图里的匿名账户不是共享登录账户。

## 计时与点击

| 时间 | 点击/画面 | 讲解重点 |
|---|---|---|
| 00:00–00:20 | 登录 →「日报工作台」 | “Daily AI News Agent，界面名Daybreak。Python/LangGraph/DeepSeek/FastAPI/Next.js/SQLite，模型自主选择工具，日报来自真实抓取。”展示已完成任务，不投屏密码。 |
| 00:20–00:55 | 「订阅配置」→展开「更多新闻源与自定义RSS」和「重点关注对象」 | 滚动到Final OpenAI RSS，展示启用、检测时间；Failed HTML source检测失败且禁用。展示OpenAI对象、ChatGPT/GPT别名、普通主题、站内开启/邮件关闭。数据按登录用户隔离。 |
| 00:55–01:15 | 点击「测试检索」（网络慢则展示已保存的真实检索截图） | 最多5条，标题、原始URL、时间、匹配对象与HF失败提示。读取已保存配置，25秒网络预算，不生成日报/邮件/站内通知。无结果必须如实说明。 |
| 01:15–02:10 | 「Agent Trace」→选择本次completed任务→展开下列事件 | 展示真实response_id/usage、两次搜索、三次抓取、错误拒绝和恢复、最终保存入队。切到graph.py条件边：model↔tools循环，10工具没有变，没有固定搜索/生成/推送节点。 |
| 02:10–02:40 | 「日报工作台」→展开首条「原文证据与来源指纹」→打开原文 | 指出逐字证据、发布时间、抓取时间、SHA-256；服务端验证引用并插入链接。本次3条均通过数据库对照；指纹不能保证摘要语义绝对正确。 |
| 02:40–03:00 | 「历史日报」→打开本次记录→通知图标→README | 展示归档和1条通知。“87后端回归、4常规浏览器E2E，另有1场景真实模型全链路通过。SMTP仅本机协议验证，外部邮件/Docker未验证。交付含源码、图、文档、证据和与Commit一致的ZIP。” |

## 必须展示的实际Trace

1. **model**：实际deepseek-flash、response_id和usage；不展示私密思维链。
2. **get_preferences**：对象与别名、自定义源ID、语言、时间窗和送达设置。
3. **两次search_news**：query、candidates、matched_objects、source_errors。HF超时没有阻止有效RSS返回。
4. **fetch_article**：article_id、url、published_at、fetched_at、sha256；公开报告不含整篇正文。
5. **第一次失败save_digest**：ok=false，引文不是逐字摘录被拒绝；错误返回模型，由模型决定后续工具。本次3次保存失败，不讲成全部一次成功。
6. **成功save_digest → send_digest**：3条内容持久化、按用户渠道入队。入队不等于邮件送达；本次邮件关闭，in_app为sent且通知唯一。
7. **lifecycle completed**：结合日报、投递状态确认完成，不凭模型口头声明。

辅助材料：[最终验收](../evidence/final-2026-10-11/validation.md)、[完成日报截图](../evidence/final-2026-10-11/dashboard-final.png)、[错误恢复截图](../evidence/final-2026-10-11/trace-error-recovery.png)、[架构](architecture.md)、[Workflow](workflow.md)、[安全边界](security.md)。

同一用户当天再次点击「生成今日日报」会返回既有日报/任务，应说明幂等；若要现场新的模型调用，提前创建新演示账号，接受实时延迟，不伪装为重新生成。
