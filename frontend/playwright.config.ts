import {defineConfig} from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  timeout: 45000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["json", {outputFile: "../evidence/browser-tests.json"}]],
  use: {baseURL: process.env.TEST_BASE_URL || "http://localhost:3000", browserName: "chromium", viewport: {width: 1440, height: 1050}, screenshot: "only-on-failure", trace: "retain-on-failure"}
});
