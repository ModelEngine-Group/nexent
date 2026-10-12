import type { BrowserContext, Page } from "playwright/test";
import { AuthPage } from "../pages/auth.page";
import { appPath, testUser } from "./runtime-config";

export async function loginCurrent(page: Page, userId: string): Promise<AuthPage> {
  const auth = new AuthPage(page);
  await page.goto(appPath("/"), { waitUntil: "domcontentloaded" });
  await auth.expectLoggedOut();
  const response = await auth.login(testUser(userId));
  if (response !== 200) throw new Error(`${userId} signin returned ${response}`);
  return auth;
}

export async function loginIsolated(source: Page, userId: string): Promise<{ context: BrowserContext; page: Page; auth: AuthPage }> {
  const browser = source.context().browser();
  if (!browser) throw new Error("Playwright browser is unavailable for isolated context");
  const context = await browser.newContext({ locale: "zh-CN" });
  const page = await context.newPage();
  const auth = await loginCurrent(page, userId);
  return { context, page, auth };
}
