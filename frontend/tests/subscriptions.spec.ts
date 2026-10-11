import {test, expect} from "@playwright/test";
const headers = {"X-Requested-With": "daily-ai-news"};
const evidence = process.env.EVIDENCE_DIR || "../evidence/subscription-enhancement";

async function register(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByRole("button", {name: "创建账户", exact: true}).click();
  await page.getByLabel("邮箱地址").fill(`subscriptions-${Date.now()}@example.com`);
  await page.getByLabel("密码", {exact: true}).fill("Browser-test-password-123");
  await page.getByRole("button", {name: "创建账户", exact: true}).click();
  await page.getByRole("button", {name: "订阅配置", exact: true}).click();
  await expect(page.getByLabel("关注主题")).toBeVisible();
}

test("focus object add edit delete and saved preference reload", async ({page}) => {
  await register(page);
  await page.getByText("重点关注对象", {exact: false}).click();
  await page.getByLabel("对象类型").selectOption("project");
  await page.getByLabel("对象名称").fill("LangGraph");
  await page.getByLabel("检索别名").fill("lang graph, LangGraph framework");
  await page.getByRole("button", {name: "添加关注对象", exact: true}).click();
  await page.getByRole("button", {name: "编辑 LangGraph", exact: true}).click();
  await page.getByLabel("检索别名").fill("lang graph, LangGraph framework, langgraph.js");
  await page.getByRole("button", {name: "更新关注对象", exact: true}).click();
  await page.getByRole("button", {name: "保存订阅配置"}).click();
  await expect(page.getByRole("status")).toContainText("订阅配置已保存");
  await page.reload();
  await page.getByRole("button", {name: "订阅配置", exact: true}).click();
  await page.getByText("重点关注对象", {exact: false}).click();
  await expect(page.locator(".focus-card")).toContainText("langgraph.js");
  await page.setViewportSize({width: 390, height: 844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({path: `${evidence}/subscription-mobile.png`, fullPage: true});
  await page.getByRole("button", {name: "删除 LangGraph", exact: true}).click();
  const saved = page.waitForResponse(r => r.url().endsWith("/api/preferences") && r.request().method() === "PUT");
  await page.getByRole("button", {name: "保存订阅配置"}).click();
  expect((await saved).ok()).toBeTruthy();
  const prefs = await page.request.get("/api/preferences");
  expect((await prefs.json()).watch_objects).toEqual([]);
});

test("RSS validation, lifecycle and live saved-config preview without digest side effects", async ({page}) => {
  test.skip(Boolean(process.env.CI) && process.env.LIVE_RSS_BROWSER !== "1", "External RSS browser test is opt-in on CI via LIVE_RSS_BROWSER=1; never use fabricated news.");
  test.setTimeout(90000);
  await register(page);
  await page.getByText("更多新闻源与自定义 RSS", {exact: false}).click();
  await page.getByRole("button", {name: "添加 RSS 新闻源", exact: true}).click();
  await page.getByLabel("来源名称", {exact: true}).fill("Browser RSS");
  await page.getByLabel("RSS/Atom URL").fill("https://127.0.0.1/feed");
  await page.getByRole("button", {name: "检测并添加"}).click();
  await expect(page.locator(".subscription-extras [role=alert]")).toContainText("public HTTPS");
  await page.getByLabel("RSS/Atom URL").fill("https://openai.com/news/rss.xml");
  await page.getByRole("button", {name: "检测并添加"}).click();
  const card = page.locator(".feed-card").filter({has: page.getByText("Browser RSS", {exact: true})});
  await expect(card).toBeVisible({timeout: 20000});
  // Assert genuine validation status, never substitute a fabricated feed in browser tests.
  await expect(card).toContainText("检测成功");
  await card.getByRole("button", {name: "启用 Browser RSS", exact: true}).click();
  await expect(card.getByRole("button", {name: "禁用 Browser RSS", exact: true})).toBeVisible();
  const sourceList = await (await page.request.get("/api/sources")).json();
  const source = sourceList.find((s: {name: string}) => s.name === "Browser RSS");
  const prefs = await (await page.request.get("/api/preferences")).json();
  prefs.sources = [source.id]; prefs.topics = ["AI"]; prefs.lookback_days = 14;
  prefs.watch_objects = [{type: "model", name: "UnlikelyBrowserObject", aliases: ["NoSuchNewsObject123"]}];
  expect((await page.request.put("/api/preferences", {headers, data: prefs})).ok()).toBeTruthy();
  await page.reload();
  await page.getByRole("button", {name: "订阅配置", exact: true}).click();
  await page.getByLabel("关注主题").fill("unsaved-topic-must-not-be-used");
  const response = page.waitForResponse(r => r.url().endsWith("/api/search-preview"));
  await page.getByRole("button", {name: "测试检索", exact: true}).click();
  const data = await (await response).json();
  expect(data.saved_preferences.topics).toEqual(["AI"]);
  expect(data.candidates.length).toBeLessThanOrEqual(5);
  expect(data.unmatched_objects).toContain("UnlikelyBrowserObject");
  await expect(page.getByRole("region", {name: "测试检索结果"})).toContainText("未生成日报或发送推送");
  for (const route of ["/api/digests", "/api/notifications", "/api/runs"]) {
    expect(await (await page.request.get(route)).json()).toEqual([]);
  }
  await page.screenshot({path: `${evidence}/subscription-preview.png`, fullPage: true});
  // Restoring a preset allows disabling/removing the custom source without leaving zero sources.
  prefs.sources = ["openai", source.id];
  expect((await page.request.put("/api/preferences", {headers, data: prefs})).ok()).toBeTruthy();
  await page.reload();
  await page.getByRole("button", {name: "订阅配置", exact: true}).click();
  await page.getByText("更多新闻源与自定义 RSS", {exact: false}).click();
  await page.getByRole("button", {name: "禁用 Browser RSS", exact: true}).click();
  await expect(page.getByRole("button", {name: "启用 Browser RSS", exact: true})).toBeVisible();
  await page.getByRole("button", {name: "删除 Browser RSS", exact: true}).click();
  await expect(page.getByRole("button", {name: "删除 Browser RSS", exact: true})).not.toBeVisible();
});
