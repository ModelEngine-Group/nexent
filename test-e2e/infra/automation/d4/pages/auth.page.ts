import { expect, Page } from "playwright/test";
import type { TestUser } from "../runner/runtime-config";
import { appPath } from "../runner/runtime-config";

export class AuthPage {
  constructor(readonly page: Page) {}

  async openProtected(path = "/agents"): Promise<void> {
    await this.page.goto(appPath(path), { waitUntil: "domcontentloaded" });
  }

  async expectLoggedOut(): Promise<void> {
    await expect(this.page.getByRole("button", { name: "登录账户" })).toBeVisible();
  }

  async login(user: TestUser): Promise<number> {
    await this.page.getByRole("button", { name: "登录账户" }).click();
    await this.page.getByPlaceholder("your@email.com").first().fill(user.username);
    await this.page.getByPlaceholder("请输入密码").first().fill(user.password);
    const [response] = await Promise.all([
      this.page.waitForResponse((candidate) => candidate.url().includes("/api/user/signin") && candidate.request().method() === "POST"),
      this.page.getByRole("button", { name: "登 录", exact: true }).click(),
    ]);
    await expect(this.page.getByRole("button", { name: "登录账户" })).toBeHidden();
    return response.status();
  }

  async expectCurrentUser(user: TestUser): Promise<void> {
    const response = await this.page.request.get("/api/user/current_user_info");
    expect(response.ok()).toBeTruthy();
    const body = JSON.stringify(await response.json());
    expect(body).toContain(user.username);
  }

  async logout(): Promise<number> {
    const avatar = this.page.locator(".ant-avatar").first();
    await expect(avatar).toBeVisible();
    await avatar.click();
    await this.page.getByRole("menuitem", { name: /退出登录/ }).click();
    const [response] = await Promise.all([
      this.page.waitForResponse((candidate) => candidate.url().includes("/api/user/logout")),
      this.page.getByRole("button", { name: "确 定", exact: true }).click(),
    ]);
    await this.expectLoggedOut();
    return response.status();
  }
}
