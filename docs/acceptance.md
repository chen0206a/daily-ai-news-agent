# 目录与分阶段验收

编码前已约定独立 `daily-ai-news-agent/` 目录，按下列顺序实施；不使用预填新闻作为实际成功证据。

| 阶段 | 交付 | 验收方式 |
|---|---|---|
| Stage 1 | SQLite schema、账户会话、工作区、10 个工具与安全门禁 | 最初 28 项工具/安全测试通过；随后持续补充 |
| Stage 2 | DeepSeek 适配、LangGraph 条件循环、真实 RSS/正文、审计 | 两种调用顺序、工具失败恢复、预算；真实网络脚本及真实模型 E2E |
| Stage 3 | Next.js 界面、API、订阅、持久化定时队列、发件箱与历史 | API 多用户测试、时区去重与重启、SMTP/站内幂等、浏览器操作 |
| Stage 4 | 锁文件、部署、来源证据、图、README 与演示 | pytest、ruff、生产构建、Playwright、实际运行报告 |

## 需求到实现映射

| 需求 | 实现入口 |
|---|---|
| 5 基础工具 | `backend/app/tools/filesystem.py` |
| 5 业务工具 | `backend/app/tools/registry.py`、`services/news.py`、`services/delivery.py` |
| 非线性自主 Agent | `backend/app/agent/graph.py`、`model.py` |
| 登录与用户隔离 | `backend/app/api.py`、`security.py` |
| 日报与来源核验 | `ToolRegistry._save`、`evidence/verified-digest.md` |
| 定时与可靠推送 | `backend/app/services/worker.py`、`delivery.py` |
| 前端与 Trace | `frontend/app/page.tsx` |
| 单元/集成/端到端测试 | `backend/tests/`、`frontend/tests/`、`scripts/live_e2e.py` |
| 运行证据与不确定项 | `evidence/validation.md` |

## 验收不包含虚假承诺

抓取源不可用、摘要生成失败、模型未调用保存/推送、SMTP 未配置等情况均有显式状态；来源指纹证明本地证据一致性，不是对新闻事实的外部背书。`completed` 表示日报与所需推送队列完成，具体投递结果需看 delivery 状态。
