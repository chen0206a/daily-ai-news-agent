import {test, expect} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import {randomBytes, randomUUID} from "node:crypto";

const headers = {"X-Requested-With": "daily-ai-news"};
const evidence = process.env.EVIDENCE_DIR || "../evidence/final-2026-10-11";
const privateDir = process.env.LIVE_PRIVATE_DIR || "../evidence/private/final-2026-10-11";
const screenshotStyle = ".profile small{visibility:hidden}.toggle-row small{visibility:hidden}";

// Explicit opt-in: consumes real DeepSeek credit, uses public RSS and sends only in-app notification.
test("FINAL LIVE: login, subscriptions, RSS, focus, preview, DeepSeek, citations, history and Trace", async ({page}) => {
  test.skip(process.env.RUN_FINAL_LIVE !== "1", "Set RUN_FINAL_LIVE=1 with a real configured DeepSeek key; no model/news fallback.");
  test.setTimeout(420000);
  const output = path.resolve(evidence, "live-e2e.json");
  if (fs.existsSync(output)) throw new Error("Choose a new EVIDENCE_DIR; refusing to overwrite real model evidence.");
  fs.mkdirSync(path.resolve(privateDir), {recursive: true});
  fs.mkdirSync(path.resolve(evidence), {recursive: true});
  const email = `final-${randomUUID().slice(0, 8)}@example.com`;
  const password = randomBytes(24).toString("base64url");
  fs.writeFileSync(path.resolve(privateDir, "demo-login.json"), JSON.stringify({email, password}, null, 2));

  await page.goto("/");
  await page.getByRole("button", {name: "创建账户", exact: true}).click();
  await page.getByLabel("邮箱地址").fill(email);
  await page.getByLabel("密码", {exact: true}).fill(password);
  await page.getByRole("button", {name: "创建账户", exact: true}).click();
  await expect(page.getByRole("heading", {name: "今天的 AI，值得你知道。"})).toBeVisible();
  await page.locator(".sidebar").getByRole("button", {name: "退出登录", exact: true}).click();
  await page.reload(); // Registration mode is component state; a fresh visit defaults to the login view.
  await page.getByLabel("邮箱地址").fill(email);
  await page.getByLabel("密码", {exact: true}).fill(password);
  await page.getByRole("button", {name: "进入工作台", exact: true}).click();
  await page.getByRole("button", {name: "订阅配置", exact: true}).click();

  await page.getByText("更多新闻源与自定义 RSS", {exact: false}).click();
  await page.getByRole("button", {name: "添加 RSS 新闻源", exact: true}).click();
  await page.getByLabel("来源名称", {exact: true}).fill("Failed HTML source");
  await page.getByLabel("RSS/Atom URL").fill("https://openai.com/");
  await page.getByRole("button", {name: "检测并添加"}).click();
  const failedCard = page.locator(".feed-card").filter({has: page.getByText("Failed HTML source", {exact: true})});
  await expect(failedCard).toContainText("检测失败", {timeout: 25000});
  const failedSources = await (await page.request.get("/api/sources")).json();
  expect(failedSources.find((s: {name: string}) => s.name === "Failed HTML source").enabled).toBeFalsy();

  await page.getByRole("button", {name: "添加 RSS 新闻源", exact: true}).click();
  await page.getByLabel("来源名称", {exact: true}).fill("Final OpenAI RSS");
  await page.getByLabel("RSS/Atom URL").fill("https://openai.com/news/rss.xml");
  await page.getByRole("button", {name: "检测并添加"}).click();
  const card = page.locator(".feed-card").filter({has: page.getByText("Final OpenAI RSS", {exact: true})});
  await expect(card).toContainText("检测成功", {timeout: 25000});
  await card.getByRole("button", {name: "启用 Final OpenAI RSS", exact: true}).click();
  await expect(card.getByRole("button", {name: "禁用 Final OpenAI RSS", exact: true})).toBeVisible();
  // Keep Hugging Face selected to exercise real partial-source failure if this network cannot reach it.
  await page.getByRole("checkbox", {name: "订阅 Google AI", exact: true}).uncheck();
  await page.getByText("重点关注对象", {exact: false}).click();
  await page.getByLabel("对象类型").selectOption("company");
  await page.getByLabel("对象名称").fill("OpenAI");
  await page.getByLabel("检索别名").fill("ChatGPT, GPT");
  await page.getByRole("button", {name: "添加关注对象", exact: true}).click();
  await page.getByLabel("关注主题").fill("AI, Agent, LLM");
  await page.getByLabel("最多新闻数").selectOption("3");
  await page.getByLabel("新闻时间范围").selectOption("7");
  await page.getByRole("button", {name: "保存订阅配置"}).click();
  await expect(page.getByRole("status")).toContainText("订阅配置已保存");
  const savedPrefs = await (await page.request.get("/api/preferences")).json();
  expect(savedPrefs.watch_objects[0].name).toBe("OpenAI");
  expect(savedPrefs.email_enabled).toBe(false);
  expect(savedPrefs.in_app_enabled).toBe(true);

  const previewResponse = page.waitForResponse(r => r.url().endsWith("/api/search-preview"));
  await page.getByRole("button", {name: "测试检索", exact: true}).click();
  const preview = await (await previewResponse).json();
  expect(preview.candidates.length).toBeGreaterThan(0);
  expect(preview.candidates.length).toBeLessThanOrEqual(5);
  expect(preview.candidates.some((c: {matched_objects: string[]}) => c.matched_objects.includes("OpenAI"))).toBe(true);
  for (const route of ["runs", "digests", "notifications"]) {
    expect(await (await page.request.get(`/api/${route}`)).json()).toEqual([]);
  }
  await page.screenshot({path: `${evidence}/subscription-preview.png`, fullPage: true, style: screenshotStyle});
  const before = {runs: 0, digests: 0, notifications: 0};

  const started = page.waitForResponse(r => r.url().endsWith("/api/runs") && r.request().method() === "POST");
  await page.getByRole("button", {name: "生成今日日报", exact: true}).click();
  const response = await started;
  expect(response.status()).toBe(202);
  const runID = (await response.json()).id;
  console.log(`Real DeepSeek run started: ${runID}`);
  let run: Record<string, any> = {};
  await expect.poll(async () => {
    run = await (await page.request.get(`/api/runs/${runID}`)).json();
    return run.status;
  }, {timeout: 335000, intervals: [2000, 3000]}).not.toMatch(/^(queued|running)$/);
  const trace = await (await page.request.get(`/api/runs/${runID}/trace`)).json();
  const digests = await (await page.request.get("/api/digests")).json();
  const digest = digests.length ? await (await page.request.get(`/api/digests/${digests[0].id}`)).json() : null;
  if (digest) await expect.poll(async () => (await (await page.request.get("/api/notifications")).json()).length, {timeout: 15000}).toBe(1);
  const notices = await (await page.request.get("/api/notifications")).json();
  function publicValue(value: any): any {
    if (Array.isArray(value)) return value.map(publicValue);
    if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).filter(([k]) => !["user_id", "email", "password", "token", "cookie", "reasoning_content", "snippet"].includes(k)).map(([k, v]) => [k, publicValue(v)]));
    if (typeof value === "string") return value.replaceAll(password, "[REDACTED]").replaceAll(email, "[DEMO_ACCOUNT]").replace(/sk-[A-Za-z0-9_-]{12,}/g, "[REDACTED]");
    return value;
  }
  const publicTrace = trace.map((e: any) => {
    const data = structuredClone(e.data);
    if (e.kind === "tool" && data.name === "fetch_article" && data.result) delete data.result.content;
    return {kind: e.kind, created_at: e.created_at, data: publicValue(data)};
  });
  const modelEvents = trace.filter((e: any) => e.kind === "model");
  const toolEvents = trace.filter((e: any) => e.kind === "tool");
  const report = publicValue({kind: "REAL_DEEPSEEK_BROWSER_END_TO_END", executed_at: new Date().toISOString(), run_id: runID,
    status: run.status, error: run.error, final_text: run.final_text, model: run.model, trace: publicTrace,
    preferences: savedPrefs, preview, pre_generation_counts: before,
    digest: digest ? Object.fromEntries(["id", "title", "digest_date", "items", "deliveries"].map(k => [k, digest[k]])) : null,
    in_app_notifications: notices.length, email: "NOT_SENT; disabled", model_calls: modelEvents.length, tool_calls: toolEvents.length,
    actual_models: [...new Set(modelEvents.map((e: any) => e.data.model))],
    total_tokens: modelEvents.reduce((n: number, e: any) => n + (e.data.usage?.total_tokens || 0), 0)});
  fs.writeFileSync(output, JSON.stringify(report, null, 2));
  if (digest) fs.writeFileSync(path.resolve(evidence, "verified-digest.md"), publicValue(digest.markdown));
  console.log(`Real outcome: ${run.status}; ${modelEvents.length} model calls; ${toolEvents.length} tool calls; ${digest?.items.length || 0} articles; ${notices.length} notifications`);
  expect(run.status, `Actual run error: ${run.error || "none"}`).toBe("completed");
  expect(digest.items.length).toBeGreaterThan(0);
  expect(modelEvents.every((e: any) => e.data.response_id && e.data.model !== "scripted-test-double")).toBeTruthy();
  expect(toolEvents.some((e: any) => e.data.name === "search_news")).toBeTruthy();
  expect(toolEvents.some((e: any) => e.data.name === "save_digest" && e.data.ok)).toBeTruthy();
  expect(toolEvents.some((e: any) => e.data.name === "send_digest" && e.data.ok)).toBeTruthy();
  for (const item of digest.items) {
    expect(item.url).toMatch(/^https:\/\//);
    expect(item.sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(item.evidence_quote.length).toBeGreaterThanOrEqual(20);
  }
  await page.getByRole("button", {name: "日报工作台", exact: true}).click();
  await expect(page.locator(".news-item")).toHaveCount(digest.items.length);
  await page.locator(".evidence summary").first().click();
  await expect(page.locator(".evidence code").first()).toContainText("SHA-256");
  await expect(page.locator(".news-content h3 a").first()).toHaveAttribute("href", digest.items[0].url);
  await page.screenshot({path: `${evidence}/dashboard.png`, fullPage: true, style: screenshotStyle});
  await page.getByRole("button", {name: "历史日报", exact: true}).click();
  await expect(page.locator(".archive-row")).toHaveCount(1);
  await page.locator(".archive-row").first().click();
  await page.getByRole("button", {name: "查看生成轨迹", exact: true}).click();
  await expect(page.locator(".trace-event")).toHaveCount(trace.length);
  const searchEvent = page.locator(".trace-event").filter({has: page.getByText("search_news", {exact: true})}).first();
  await searchEvent.locator("summary").click();
  await expect(searchEvent.locator("pre")).toContainText("candidates");
  await page.screenshot({path: `${evidence}/agent-trace.png`, fullPage: true, style: screenshotStyle});
  await page.getByRole("button", {name: "通知", exact: true}).click();
  await expect(page.locator(".notice")).toHaveCount(1);
});
