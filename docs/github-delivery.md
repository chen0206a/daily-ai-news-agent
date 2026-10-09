# GitHub 正式交付说明

仓库：[chen0206a/daily-ai-news-agent](https://github.com/chen0206a/daily-ai-news-agent)

交付分支：`main`

## 发布范围

发布源码、测试、依赖锁文件、`.env.example`、README、架构与 Workflow 的 Mermaid/SVG/PNG、3 分钟演示脚本和可公开的脱敏验收证据。此次仅进行发布整理，没有扩展应用功能。

本地交付目录已有 Git 仓库；发布前当前分支为 `main`，没有已有提交或远程。初次检查 GitHub 仓库为空。发布采用普通提交与普通 push，保留任何随后发现的远程历史，不使用强制推送。

## 敏感内容审查

- 检查 Git 索引中的实际文件内容，并与本地 `.env` 密钥及私有演示登录密码做精确比对；同时检查常见供应商密钥、GitHub Token、JWT、私钥、认证 URL、会话 Cookie 与密码哈希模式。
- `.env`、`evidence/private/`、SQLite 用户数据库及 WAL/SHM、运行日志、虚拟环境、依赖目录、缓存、构建产物与 `dist/` 均被忽略；`.env.example` 保留空值和说明。
- 测试代码中的 `test-only` 等值为显式测试夹具，不是外部服务凭据。私有演示账户的实际随机密码不在公开文件中。
- 浏览器 JSON 报告中本机根路径已替换为 `<PROJECT_ROOT>`，保持原始测试计数和执行结果。截图只显示匿名演示标识、公开新闻及执行信息，不包含密钥、密码或 Cookie。
- 公开真实模型 Trace 保留 response_id、工具参数、结果元数据和 Token 用量，移除整篇文章及私有思维内容；原始正文留在本机被忽略的 SQLite 数据库中。

## 历史验收证据

| 已执行验收 | 已记录结果 |
|---|---|
| 后端自动化测试 | 56 项通过 |
| 浏览器验收 | 2 项通过 |
| 真实 DeepSeek | 7 轮模型调用、11 次工具执行 |
| 日报与站内通知 | 3 条新闻、1 条通知 |

以上来自 [保存的验收记录](../evidence/validation.md)。本次 GitHub 发布没有重新运行业务测试或真实模型，不将发布检查计入测试次数。

## 复现与限制

按照 [README](../README.md) 安装并配置自己的 `.env`。`scripts/live_e2e.py` 会消耗 DeepSeek API 额度，创建新的本地演示用户；私有登录文件不会从 GitHub 下载。不要使用截图中的匿名演示账号作为共享账户。

外部邮箱最终送达和 Docker 启动仍未实际验证；公开互联网部署需要邮箱所有权验证与生产访问控制。GitHub Actions 提供无模型密钥的自动化检查；新检出仓库中需要私有演示登录的浏览器场景会跳过，不等同于已有本机真实验收的两项通过。

提交 ZIP 保存在本地 `dist/`，不上传 GitHub。更新包后可用同目录的 `.sha256` 校验。最新提交以 `git rev-parse HEAD` 和 `git ls-remote origin refs/heads/main` 的一致结果为准。
