import { expect, Locator, Page } from "playwright/test";
import { appPath } from "../runner/runtime-config";

export class ResourcePage {
  constructor(readonly page: Page) {}

  private iconButton(scope: Locator, icon: string): Locator {
    if (icon === "trash-2") return scope.locator("button:has(svg.lucide-trash-2, svg.lucide-trash2)");
    return scope.locator(`button:has(svg.lucide-${icon})`);
  }

  async open(): Promise<void> {
    await this.page.goto(appPath("/resource-manage"), { waitUntil: "domcontentloaded" });
    await expect(this.page.getByText("租户资源管理", { exact: true })).toBeVisible();
  }

  tenant(name: string): Locator {
    return this.page.getByText(name, { exact: true }).first();
  }

  async selectTenant(name: string): Promise<void> {
    await expect(this.tenant(name)).toBeVisible();
    await this.tenant(name).click();
    await expect(this.page.getByRole("heading", { name, exact: true })).toBeVisible();
  }

  async ensureCurrentTenant(name?: string): Promise<void> {
    const detailTabs = this.page.getByRole("tab", { name: "用户", exact: true });
    if (await detailTabs.waitFor({ state: "visible", timeout: 10000 }).then(() => true).catch(() => false)) {
      return;
    }
    if (!name) throw new Error("tenant detail is not open and current user response omitted tenant_name");
    await this.selectTenant(name);
  }

  async createTenant(name: string, admin?: { email: string; password: string }): Promise<void> {
    const tenantPanel = this.page.getByText("租户", { exact: true }).locator("..")
      .locator("..");
    await this.iconButton(tenantPanel, "plus").click();
    const modal = this.page.getByRole("dialog", { name: "创建租户" });
    await expect(modal).toBeVisible();
    await modal.getByPlaceholder("输入租户名称").fill(name);
    if (admin) {
      const switchControl = modal.getByRole("switch").first();
      await expect(switchControl).toBeVisible();
      if ((await switchControl.getAttribute("aria-checked")) !== "true") await switchControl.click();
      await modal.getByLabel("租户管理员邮箱").fill(admin.email);
      await modal.getByLabel("租户管理员密码", { exact: true }).fill(admin.password);
      await modal.getByLabel("确认密码").fill(admin.password);
    }
    const responsePromise = this.page.waitForResponse((r) => /\/api\/tenant/.test(r.url()) && r.request().method() === "POST");
    await modal.getByRole("button", { name: /确\s*定/ }).click();
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`tenant create returned ${response.status()}`);
    await expect(this.tenant(name)).toBeVisible();
  }

  async renameSelectedTenant(oldName: string, newName: string): Promise<void> {
    const heading = this.page.getByRole("heading", { name: oldName, exact: true });
    await heading.click();
    const input = this.page.getByPlaceholder("租户名称");
    await expect(input).toBeVisible();
    await input.fill(newName);
    const responsePromise = this.page.waitForResponse((r) => /\/api\/tenant/.test(r.url()) && ["PUT", "PATCH"].includes(r.request().method()));
    await input.press("Enter");
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`tenant rename returned ${response.status()}`);
    await expect(this.page.getByRole("heading", { name: newName, exact: true })).toBeVisible();
  }

  async deleteTenant(name: string): Promise<void> {
    const row = this.tenant(name).locator("xpath=ancestor::div[contains(concat(' ',normalize-space(@class),' '),' group ')][1]");
    await row.hover();
    await row.getByRole("button").last().click();
    const modal = this.page.locator('[role="dialog"]:visible').filter({ hasText: name });
    await expect(modal).toBeVisible();
    const responsePromise = this.page.waitForResponse((r) => /\/api\/tenant/.test(r.url()) && r.request().method() === "DELETE");
    await modal.getByRole("button", { name: /确\s*定/ }).click();
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`tenant delete returned ${response.status()}`);
    await expect(this.tenant(name)).toHaveCount(0);
  }

  async openTab(name: string): Promise<void> {
    await this.page.getByRole("tab", { name, exact: true }).click();
    await expect(this.page.getByRole("tab", { name, exact: true })).toHaveAttribute("aria-selected", "true");
  }

  async visibleTabs(): Promise<string[]> {
    return this.page.getByRole("tab").allTextContents();
  }

  async createGroup(name: string, description: string): Promise<void> {
    await this.openTab("用户组");
    await this.page.getByRole("button", { name: /创建用户组/ }).click();
    const modal = this.page.getByRole("dialog", { name: "创建用户组" });
    await modal.getByPlaceholder("输入用户组名称").fill(name);
    await modal.locator('textarea[placeholder="描述"]:visible').fill(description);
    const responsePromise = this.page.waitForResponse((r) => /group/i.test(r.url()) && r.request().method() === "POST");
    await modal.getByRole("button", { name: /确\s*定/ }).click();
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`group create returned ${response.status()}`);
    await this.searchCurrentTab("搜索用户组名称", name);
    await expect(this.page.getByRole("row").filter({ hasText: name })).toBeVisible();
  }

  async editGroupMembers(name: string, memberEmail: string): Promise<void> {
    const row = this.page.getByRole("row").filter({ hasText: name });
    await row.getByRole("button").nth(1).click();
    const modal = this.page.getByRole("dialog", { name: "编辑用户组" });
    const members = modal.getByLabel("组成员");
    await members.click();
    // Ant Design renders the visible dropdown item outside the dialog and its
    // virtualized option does not consistently expose an accessible `option`
    // name.  Bind to the visible option container and the configured email.
    const memberOption = this.page.locator(".ant-select-item-option:visible")
      .filter({ hasText: memberEmail });
    await expect(memberOption).toHaveCount(1);
    await memberOption.click();
    await this.page.keyboard.press("Escape");
    const responsePromise = this.page.waitForResponse((r) => /group/i.test(r.url()) && ["PUT", "PATCH"].includes(r.request().method()));
    await modal.getByRole("button", { name: /确\s*定/ }).click();
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`group update returned ${response.status()}`);
  }

  async deleteGroup(name: string): Promise<void> {
    await this.openTab("用户组");
    await this.searchCurrentTab("搜索用户组名称", name);
    const row = this.page.getByRole("row").filter({ hasText: name });
    if (!(await row.count())) return;
    await row.getByRole("button").last().click();
    const modal = this.page.getByRole("dialog").filter({ hasText: `删除用户组\"${name}\"？` });
    const responsePromise = this.page.waitForResponse((r) => /group/i.test(r.url()) && r.request().method() === "DELETE");
    await modal.getByRole("button", { name: /确\s*定/ }).click();
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`group delete returned ${response.status()}`);
  }

  async createInvitation(groupName: string): Promise<string> {
    await this.openTab("邀请码");
    await this.page.getByRole("button", { name: "创建邀请码" }).click();
    const modal = this.page.getByRole("dialog", { name: "创建邀请码" });
    const groups = modal.getByLabel(/用户组/);
    if (await groups.count()) {
      await groups.click();
      await this.page.getByText(groupName, { exact: true }).last().click();
    }
    const responsePromise = this.page.waitForResponse((r) => /invitation/i.test(r.url()) && r.request().method() === "POST");
    await modal.getByRole("button", { name: /确\s*定/ }).click();
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`invitation create returned ${response.status()}`);
    const body = await response.json();
    const code = String(body?.data?.invitation_code || body?.invitation_code || "");
    if (!code) throw new Error("invitation create response omitted invitation_code");
    await expect(this.page.getByText(code, { exact: true })).toBeVisible();
    return code;
  }

  async deleteInvitation(code: string): Promise<void> {
    await this.openTab("邀请码");
    const row = this.page.getByRole("row").filter({ hasText: code });
    if (!(await row.count())) return;
    await row.getByRole("button").last().click();
    const modal = this.page.getByRole("dialog").filter({ hasText: code });
    const responsePromise = this.page.waitForResponse((r) => /invitation/i.test(r.url()) && r.request().method() === "DELETE");
    await modal.getByRole("button", { name: /确\s*定/ }).click();
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`invitation delete returned ${response.status()}`);
  }

  async searchCurrentTab(placeholder: string, value: string): Promise<void> {
    const input = this.page.getByPlaceholder(placeholder);
    await input.fill(value);
    await this.page.waitForLoadState("networkidle").catch(() => undefined);
  }

  async apiKeyRow(email: string): Promise<Locator> {
    await this.openTab("API Key");
    const row = this.page.getByRole("row").filter({ hasText: email });
    await expect(row).toBeVisible();
    return row;
  }

  async refreshApiKey(email: string): Promise<string> {
    const row = await this.apiKeyRow(email);
    await this.iconButton(row, "refresh-cw").click();
    const confirm = this.page.getByRole("dialog", { name: "确认刷新该用户的 API Key？" });
    const responsePromise = this.page.waitForResponse((r) => /api.?key/i.test(r.url()) && ["POST", "PUT"].includes(r.request().method()));
    await confirm.getByRole("button", { name: /确\s*定/ }).click();
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`API key refresh returned ${response.status()}`);
    const success = this.page.getByRole("dialog", { name: "API Key 刷新成功" });
    const secret = (await success.locator("code").innerText()).trim();
    if (secret.length < 16) throw new Error("one-time API key value was missing or implausibly short");
    await success.getByRole("button", { name: /确\s*定|OK/i }).click();
    return secret;
  }

  async revokeApiKey(email: string): Promise<void> {
    const row = await this.apiKeyRow(email);
    await this.iconButton(row, "trash-2").click();
    const confirm = this.page.getByRole("dialog", { name: "确认删除该用户的 API Key？" });
    const responsePromise = this.page.waitForResponse((r) => /api.?key/i.test(r.url()) && r.request().method() === "DELETE");
    await confirm.getByRole("button", { name: /确\s*定/ }).click();
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`API key revoke returned ${response.status()}`);
    await expect(this.page.getByText("API Key 已删除")).toBeVisible();
  }
}
