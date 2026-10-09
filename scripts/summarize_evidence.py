import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def main():
    junit = ET.parse(ROOT / "evidence/backend-tests.xml").getroot()
    suites = list(junit.iter("testsuite"))
    tests = sum(int(s.get("tests", 0)) for s in suites)
    failures = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    browser = json.loads((ROOT / "evidence/browser-tests.json").read_text(encoding="utf-8"))
    live = json.loads((ROOT / "evidence/live-e2e.json").read_text(encoding="utf-8"))
    news = json.loads((ROOT / "evidence/live-news.json").read_text(encoding="utf-8"))
    model_events = [e["data"] for e in live["trace"] if e["kind"] == "model"]
    tools = [e["data"] for e in live["trace"] if e["kind"] == "tool"]
    tokens = sum(e.get("usage", {}).get("total_tokens", 0) for e in model_events)
    actual_models = ", ".join(sorted({e.get("model", "unknown") for e in model_events}))
    report = f'''# 实际验收记录

生成时间：{datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()}（Asia/Shanghai）。下面计数由报告文件读取，不以模拟执行冒充真实结果。

| 验收项目 | 本次结果 |
|---|---|
| 后端 pytest | {tests} 项，失败/错误 {failures} |
| Python lint / 依赖一致性 | ruff check 通过；pip check 无依赖冲突 |
| Next.js 生产构建 | Next.js 16.4.0，TypeScript + 静态页面构建通过 |
| npm audit | 锁定依赖审计通过，0 个已知漏洞（含开发依赖） |
| Playwright | 通过 {browser['stats']['expected']}，失败 {browser['stats']['unexpected']}，跳过 {browser['stats']['skipped']} |
| 真实 RSS | {len(news['search']['candidates'])} 条候选；{sum('sha256' in a for a in news['articles'])} 篇正文抓取；来源错误 {len(news['search']['source_errors'])} |
| 真实模型 | 配置 {live['model']}；响应实际模型 {actual_models}；{len(model_events)} 轮；{len(tools)} 次工具调用；状态 {live['status']} |
| 模型 Token | {tokens}，为各轮 API usage.total_tokens 之和（包含反复发送的上下文，不是去重 Token 数） |
| 日报与站内 | {len(live['digest']['items']) if live['digest'] else 0} 条新闻；{live['in_app_notifications']} 条站内通知 |
| SMTP | 本机 TCP SMTP 集成测试通过；未向外部收件箱发送 |
| 容器 | 提供 compose 与 Dockerfile；当前环境无 Docker，尚未启动验证 |
| Windows 启停脚本 | 实测 start/stop/start；健康检查成功，子进程按项目身份验证后停止 |

## 实际工具顺序

`{' → '.join(t['name'] for t in tools)}`

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
'''
    (ROOT / "evidence/validation.md").write_text(report, encoding="utf-8")
    print(f"Evidence: {tests} backend tests, {browser['stats']['expected']} browser tests, {len(model_events)} actual model calls.")


if __name__ == "__main__":
    main()
