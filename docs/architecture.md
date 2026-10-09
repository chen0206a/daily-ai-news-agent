# 架构图

![架构图](architecture.svg)

下面保留可编辑 Mermaid 源码；另有同名 PNG 导出。

```mermaid
flowchart TB
  Browser[用户浏览器] --> Web[Next.js / React\n登录 · 订阅 · 日报 · Trace]
  Web -->|同源 /api 代理 · HttpOnly Cookie| API[FastAPI\n鉴权 · CSRF · 资源归属校验]
  API --> DB[(SQLite WAL\n用户 / 偏好 / 队列 / Trace / 日报 / 发件箱)]
  Clock[时区感知定时器] -->|每天唯一 slot| DB
  DB -->|原子领取 queued 任务| Worker[单实例 Worker\nOS 锁 · 超时 · 重启恢复]
  Worker --> Graph[LangGraph StateGraph]
  Graph <-->|tool_choice=auto| LLM[DeepSeek API\nOpenAI-compatible tool calling]
  Graph --> Guard[工具注册表\n参数 schema · 用户绑定 · 预算]
  Guard --> FS[5 个基础工具\n隔离工作区 / 无 shell 白名单]
  Guard --> News[search_news / fetch_article\nRSS · DNS 固定 IP · HTTPS 域名校验]
  Guard --> Biz[get_preferences / save_digest / send_digest\n引用片段校验 · 幂等入库]
  News --> Sources[OpenAI / Hugging Face\nGoogle AI / TechCrunch]
  Biz --> DB
  DB --> Delivery[持久化发件箱]
  Delivery --> Site[站内通知 · 事务去重]
  Delivery --> SMTP[SMTP STARTTLS\n不确定发送状态禁止自动重试]
  Graph -->|实际调用 / 用量 / 结果| DB
```

所有工具的 user_id、run_id、工作区和收件邮箱由后端绑定；模型 schema 不含这些可越权参数。模型看到的是工具能力描述，API 从不接受直接执行任意工具的请求。

本项目针对单机笔试交付，数据库与任务队列共用 SQLite，运行一个 API worker。OS 文件锁防止多个调度器争抢重启恢复逻辑；不依赖内存中的任务列表保存进度。SQLite 保存完整执行审计，但不保存可跨版本恢复的 LangGraph checkpoint；进程中断的运行标记为 interrupted，排队任务可继续处理。

多实例部署需将任务队列/租约与数据库迁移到独立服务，而不是简单增加 uvicorn workers。
