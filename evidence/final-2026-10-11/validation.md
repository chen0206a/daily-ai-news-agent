# 2026-10-11 最终笔试交付验收

时区：Asia/Shanghai。真实模型、真实RSS、自动化测试分别记录，历史目录不覆盖。本次纳入已完成的订阅增强；没有新增应用功能，也没有更改Agent拓扑或项目定位。

## 实际结果

| 项目 | 实际执行结果 | 证据 |
|---|---|---|
| 完整后端测试 | 87 passed，0 failure/error | [JUnit](backend-tests.xml) |
| 常规浏览器E2E | 4 passed，0 skipped/failed，完整重跑 | [Playwright](browser-tests.json) |
| 真实模型浏览器E2E | 1场景通过：注册后重新登录、偏好、失败/有效RSS、对象、预览、真正DeepSeek生成、引用、归档、Trace、通知 | [初次浏览器报告中该场景](browser-initial.json)、[实际模型Trace](live-e2e.json) |
| DeepSeek实际调用 | 配置deepseek-chat；响应deepseek-flash；10轮、13工具、111,220 total_tokens | [实际响应ID/usage](live-e2e.json) |
| 日报/送达 | 3条新闻、1条in_app通知、0邮件投递 | [日报](verified-digest.md)、[持久化校验](citation-checks.json) |
| 真实新闻独立检查 | 24候选、5篇正文抓取成功，5个来源错误/预算提示 | [联网报告](live-news.json) |
| 前端/静态/依赖 | npm run build、ruff check、pip check实际通过 | 本次终端执行 |
| 内容与链接审查 | 当前公开候选和已拉取Git历史扫描；私有密钥/密码精确比对；相对图片/文档链接检查 | [审查报告](release-audit.json) |
| 外部文档/图片 | README/docs中5个外链实际HTTP200，20个PNG文件结构/CRC有效；本地相对链接无缺失 | [链接与图片检查](links-and-images.json) |

常规浏览器与真实模型场景分别执行，不能把一次模型任务算成87项自动化测试，也不能把CI缺密钥/账号时的跳过计为通过。

## 全链路与失败隔离

- 浏览器注册、注销、重新登录新账号；配置AI/Agent/LLM主题、7天窗口、最多3条、OpenAI对象及ChatGPT/GPT别名。
- 提交OpenAI HTML首页作为RSS：真实访问后失败，保存禁用状态。添加并启用真实OpenAI RSS，和预置源一起使用。
- 测试检索最多5条，命中OpenAI对象。HF超时明确列出，有效自定义RSS仍返回候选。预览后当前用户`/runs`、`/digests`、`/notifications`均为空。
- 点击生成后DeepSeek自主决定两次search_news、三次fetch_article及后续工具；3条最终新闻来自用户自定义RSS。
- 三次save_digest因引文不精确被拒绝，错误返回模型；最终修正保存成功，再send_digest。没有隐藏失败或使用预填数据替换。
- 数据库核对当前用户/运行归属、逐字引用、25词限额、正文SHA-256、原始URL与Markdown引用、渠道和唯一通知；[8项汇总检查均为true](citation-checks.json)。这些检查不保证所有摘要语义正确。
- 浏览器确认实际日报、展开引用、历史记录、完整Trace及通知。完成状态新截图：[日报](dashboard-final.png)、[Trace](agent-trace-final.png)、[失败恢复](trace-error-recovery.png)、[订阅](preferences-final.png)、[历史](history-final.png)，账户标签隐藏。

## 验收发现与修正

第一轮新脚本注册后注销仍在注册视图，没有重新加载就寻找登录按钮；中止后调整验收脚本为重新进入页面，尚未调用模型。随后真实模型场景成功。

完整浏览器套件里关注对象删除后点击保存，脚本立即GET，未等PUT，出现读取旧配置的测试竞争。改为等待保存HTTP响应，再核对数据。初次报告保留为`browser-initial.json`（4通过、1失败）；最终常规4场景单独重跑全部通过。没有为测试放宽产品限流或修改Agent。

为保留主实例登录限流，常规复验使用主数据库的SQLite备份（忽略的`data/final-regression/`），仅该隔离副本清理测试限流记录，关闭worker。副本保留真实日报/Trace供展示，新用户和偏好在副本创建。真实DeepSeek链路在主实例完成，验收后恢复主实例。

## 安全与仓库

原远程main与本地历史一致，保留既有提交，不强推。扫描公开候选、全部可达历史blob，精确比对私有随机登录密码/模型密钥，发现位置为空；`.env`、私有登录、用户DB、日志、node_modules/.next/dist继续忽略。测试夹具和example.com匿名账户不是供应商凭据；本次发布截图隐藏账号标签。

GitHub网页实际HTTP200。匿名REST API本次403，因此不会声称从该API读取了最新CI状态；远程Commit以git ls-remote核对，文件以远程main对应提交及GitHub原始文件验证。

打包采用git archive HEAD直接归档提交字节，拒绝未提交的跟踪改动，校验内容与私有凭据。ZIP不提交GitHub；同目录manifest记录Commit/tree、每文件SHA-256和包哈希，独立验证全部字节。

## 未验证与限制

- 外部邮箱最终送达未验证，SMTP账户未配置。本机TCP SMTP协议、幂等及不确定发送状态测试通过。
- Docker未启动；公开互联网部署、邮箱所有权验证、跨平台浏览器未验收。
- RSS随网络/发布方变化；本次HF、部分候选源超时/404不意味永久不可用。失败真实保留，不编造替代内容。
- 未系统评估摘要质量、召回率或Prompt Injection完备性；引用与哈希仅为可查材料校验。
- CI无私有账号/模型密钥；模型及未显式允许的外部RSS场景跳过。本机真实验证不等于CI验证。
- 再次真实演示产生费用，须用新证据目录。当天日报按用户日期唯一，重复生成不无限创建日报/推送。

历史保留：[最初56/2与7轮11工具](../validation.md)、[2026-10-09订阅增强87/4](../subscription-enhancement/validation.md)。
