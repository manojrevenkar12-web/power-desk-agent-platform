import { expect, type Page, test } from "@playwright/test";

async function signIn(page: Page, name: RegExp) {
  await page.goto("/");
  await page.getByRole("button", { name }).click();
  await expect(page.getByRole("heading", { name: /quarter hour by quarter hour/ })).toBeVisible();
}

test("a trader's answer links every number to its tool result", async ({ page }) => {
  await signIn(page, /Lena/);
  await expect(page.locator(".strip-svg rect")).toHaveCount(96);
  await page.getByLabel("Question").fill("How did PPA-DE-SOL-04 do in August 2026?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const first = page.locator(".num").first();
  await expect(first).toBeVisible();
  await first.click();
  await expect(page.locator(".evidence")).toContainText("ppa_valuation");
  await expect(page.locator(".num-untraced")).toHaveCount(0);
});

test("another desk's book is refused and the trace names the policy", async ({ page }) => {
  await signIn(page, /Marc/);
  await page.getByLabel("Question").fill("Hedge report for trading-de for July 2026");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.locator(".answer-text")).toContainText("do not have access");
  await expect(page.locator(".trace-denied")).toContainText("hedge_report");
});

test("developer tools never reach book data", async ({ page }) => {
  await signIn(page, /Ravi/);
  await page.getByLabel("Question").fill("PPA portfolio for origination-de from June to September 2026");
  await page.getByText("Developer tools").click();
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.locator(".answer-text")).not.toContainText("MWh");
});

test("measurements, frameworks, rollout and audit pages render", async ({ page }) => {
  await signIn(page, /Tom/);
  await page.getByRole("link", { name: "Measurements" }).click();
  await expect(page.getByRole("heading", { name: "Blind held-out set" })).toBeVisible();
  await page.getByRole("link", { name: "Frameworks" }).click();
  await expect(page.getByRole("cell", { name: "Fit", exact: true }).first()).toBeVisible();
  await page.getByRole("link", { name: "Claude Code rollout" }).click();
  await page.getByRole("tab", { name: "front-office" }).click();
  await expect(page.getByText("Valid against the documented rules")).toBeVisible();
  await expect(page.locator("pre.code").first()).toContainText("CLAUDE_CODE_USE_BEDROCK");
  await page.getByRole("link", { name: "Tool calls" }).click();
  await expect(page.getByRole("heading", { name: "Tool calls" })).toBeVisible();
});

test("works on a phone without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, /Sofia/);
  const w = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(w).toBeLessThanOrEqual(390);
});
