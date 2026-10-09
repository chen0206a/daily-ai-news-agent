# 实际验收记录

生成时间：2026-10-09T11:49:28.472267+08:00（Asia/Shanghai）。下面计数由报告文件读取，不以模拟执行冒充真实结果。

| 验收项目 | 本次结果 |
|---|---|
| 后端 pytest | 56 项，失败/错误 0 |
| Python lint / 依赖一致性 | ruff check 通过；pip check 无依赖冲突 |
| Next.js 生产构建 | Next.js 16.4.0，TypeScript + 静态页面构建通过 |
| npm audit | 锁定依赖审计通过，0 个已知漏洞（含开发依赖） |
| Playwright | 通过 2，失败 0，跳过 0 |
| 真实 RSS | 24 条候选；5 篇正文抓取；来源错误 1 |
| 真实模型 | 配置 deepseek-chat；响应实际模型 deepseek-flash；7 轮；11 次工具调用；状态 completed |
| 模型 Token | 72617，为各轮 API usage.total_tokens 之和（包含反复发送的上下文，不是去重 Token 数） |
| 日报与站内 | 3 条新闻；1 条站内通知 |
| SMTP | 本机 TCP SMTP 集成测试通过；未向外部收件箱发送 |
| 容器 | 提供 compose 与 Dockerfile；当前环境无 Docker，尚未启动验证 |
| Windows 启停脚本 | 实测 start/stop/start；健康检查成功，子进程按项目身份验证后停止 |

## 实际工具顺序

`get_preferences → list_dir → search_news → search_news → fetch_article → fetch_article → fetch_article → fetch_article → fetch_article → save_digest → send_digest`

这是单次实际执行轨迹，不是程序写死顺序。不同请求可能有不同顺序和数量。离线图测试另行证明了两种工具顺序都可通过相同图执行。

## 可复查文件

- `live-e2e.json`：真实 DeepSeek response_id、实际模型名、Token、工具调用和状态。公开副本去除了整篇正文与 RSS 摘录；本机 SQLite 保留原始抓取内容。
- `verified-digest.md`：真实模型生成的日报，含来源链接、原文短证据、发布时间、抓取时间和正文指纹。
- `live-news.json`：独立真实联网抓取记录；Hugging Face 当次连接超时已保留，不编造替代内容。
- `backend-tests.xml` 与 `browser-tests.json`：机器可读报告。
- `dashboard.png`、`agent-trace.png`、`mobile-empty.png`：实际浏览器截图。

## 仍需区分的边界

真实模型和站内推送已经运行。SMTP 的真实外部可达性、认证、邮件服务商限制和最终收件箱投递尚未验证。本机 SMTP 测试仅证明客户端协议、内容和本地幂等路径。

未执行公网部署或 Docker 启动；没有伪造这些结果。用户账户为本地应用账户，公网使用需补充邮箱所有权验证。摘要是 AI 生成，来源与逐字证据可检查不代表语义零误差。
