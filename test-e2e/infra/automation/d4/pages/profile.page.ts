import { expect, Page } from "playwright/test";
import { appPath } from "../runner/runtime-config";

export class ProfilePage {
  constructor(readonly page: Page) {}

  async open(): Promise<void> {
    await this.page.goto(appPath("/users"), { waitUntil: "domcontentloaded" });
    await expect(this.page.getByText("基础信息", { exact: true }).or(this.page.getByText("Account Info", { exact: true }))).toBeVisible();
    await expect(this.page.getByText("安全设置", { exact: true }).or(this.page.getByText("Security", { exact: true }))).toBeVisible();
  }

  async changePassword(currentPassword: string, newPassword: string): Promise<number> {
    await this.page.getByText("修改密码", { exact: true }).or(this.page.getByText("Change Password", { exact: true })).click();
    const dialog = this.page.locator(".ant-modal-wrap:visible").filter({ hasText: /修改密码|Change Password/ });
    await expect(dialog).toBeVisible();
    await dialog.locator("#currentPassword").fill(currentPassword);
    await dialog.locator("#newPassword").fill(newPassword);
    await dialog.locator("#confirmPassword").fill(newPassword);
    const [response] = await Promise.all([
      this.page.waitForResponse((candidate) => candidate.url().includes("/api/user/password") && candidate.request().method() === "PUT"),
      dialog.getByRole("button", { name: /保\s*存|Save/ }).click(),
    ]);
    expect(response.status()).toBe(200);
    await expect(dialog).toBeHidden();
    return response.status();
  }

  generateEntry() {
    return this.page.getByText("生成 API 密钥", { exact: true }).or(this.page.getByText("Generate Access Token", { exact: true }));
  }

  async generateToken(confirmOverwrite = false): Promise<{ status: number; tokenId: number; accessKey: string }> {
    const entry = this.generateEntry();
    await expect(entry).toBeVisible();
    if (confirmOverwrite) {
      await entry.click();
      const dialog = this.page.locator(".ant-modal-wrap:visible").filter({ hasText: /生成新的 (API 密钥|访问密钥)|Generate New Access Key/ });
      await expect(dialog).toBeVisible();
      const confirm = dialog.getByRole("button", { name: /确\s*(认|定)|Confirm/ });
      await expect(confirm).toBeVisible();
      const [response] = await Promise.all([
        this.page.waitForResponse((candidate) => candidate.url().includes("/api/user/tokens") && candidate.request().method() === "POST"),
        confirm.click(),
      ]);
      const body = await response.json();
      return { status: response.status(), tokenId: Number(body?.data?.token_id), accessKey: String(body?.data?.access_key || "") };
    }
    const [response] = await Promise.all([
      this.page.waitForResponse((candidate) => candidate.url().includes("/api/user/tokens") && candidate.request().method() === "POST"),
      entry.click(),
    ]);
    const body = await response.json();
    return { status: response.status(), tokenId: Number(body?.data?.token_id), accessKey: String(body?.data?.access_key || "") };
  }

  tokenRow(accessKey: string) {
    return this.page.getByText(accessKey, { exact: true }).locator("..");
  }

  async copyToken(accessKey: string): Promise<string> {
    const row = this.tokenRow(accessKey);
    const copy = row.getByRole("button").filter({ has: this.page.locator("svg.lucide-copy") });
    await expect(copy).toBeVisible();
    await copy.click();
    return this.page.evaluate(() => navigator.clipboard.readText());
  }

  async deleteToken(accessKey: string): Promise<number> {
    const row = this.tokenRow(accessKey);
    const remove = row.getByRole("button").filter({ has: this.page.locator("svg.lucide-trash2, svg.lucide-trash-2") });
    await expect(remove).toBeVisible();
    await remove.click();
    const dialog = this.page.locator(".ant-modal-wrap:visible").filter({ hasText: /删除 (API 密钥|访问密钥)|Delete Access Key/ });
    await expect(dialog).toBeVisible();
    const confirm = dialog.getByRole("button", { name: /确\s*(认|定)|Confirm/ });
    await expect(confirm).toBeVisible();
    const [response] = await Promise.all([
      this.page.waitForResponse((candidate) => candidate.url().includes("/api/user/tokens/") && candidate.request().method() === "DELETE"),
      confirm.click(),
    ]);
    expect([200, 204]).toContain(response.status());
    return response.status();
  }
}
