import { expect as pwExpect } from "playwright/test";
import type { BrowserContext, Page } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { appPath, configuredFeature, runToken, testUser } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { ResourcePage } from "../../infra/automation/d4/pages/resource.page";
import { registerReadyAsset } from "../../infra/automation/d4/runner/assets";

async function currentTenant(page: Page): Promise<{ id: string; name: string }> {
  const response = await page.request.get("/api/user/current_user_info");
  if (!response.ok()) throw new Error(`current user lookup returned ${response.status()}`);
  const body = await response.json();
  const data = body?.data || {};
  const user = data.user || {};
  const id = String(user.tenant_id || data.tenant_id || "");
  const name = String(user.tenant_name || data.tenant_name || "");
  if (!id) throw new Error("current user response omitted tenant_id");
  return { id, name };
}

async function updateUser(page: Page, email: string, groupName: string, role: "USER" | "DEV" = "DEV"): Promise<void> {
  const resource = new ResourcePage(page);
  await resource.openTab("用户");
  await resource.searchCurrentTab("搜索邮箱", email);
  const row = page.getByRole("row").filter({ hasText: email });
  await pwExpect(row).toBeVisible();
  await row.getByRole("button").first().click();
  const modal = page.getByRole("dialog", { name: "编辑用户" });
  const roleSelect = modal.getByLabel("类型");
  await roleSelect.click();
  await page.getByText(role === "DEV" ? "开发者" : "普通用户", { exact: true }).last().click();
  // Registration through a group-bound invitation already assigns the group.
  // Only add it when absent; Ant's visible Select is not label-associated.
  if (!(await modal.getByText(groupName, { exact: true }).count())) {
    const groupSelect = modal.getByRole("combobox").nth(1);
    await groupSelect.click();
    const option = page.locator(".ant-select-item-option:visible").filter({ hasText: groupName });
    await pwExpect(option).toHaveCount(1);
    await option.click();
    await page.keyboard.press("Escape");
    await pwExpect(page.locator(".ant-select-dropdown:visible")).toHaveCount(0);
  }
  const responsePromise = page.waitForResponse((r) => /user/i.test(r.url()) && ["PUT", "PATCH"].includes(r.request().method()));
  await modal.getByRole("button", { name: /确\s*定/ }).click();
  const response = await responsePromise;
  if (!response.ok()) throw new Error(`user update returned ${response.status()}`);
}

async function registerWithInvitation(page: Page, email: string, password: string, code: string): Promise<void> {
  await page.goto(appPath("/"), { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "登录账户" }).click();
  await page.getByRole("button", { name: "立即注册" }).click();
  const modal = page.getByRole("dialog", { name: "注册账号" });
  await modal.getByPlaceholder("your@email.com").fill(email);
  await modal.locator("#register-password").fill(password);
  await modal.locator("#register-confirm-password").fill(password);
  await modal.getByPlaceholder("请输入邀请码").fill(code);
  const responsePromise = page.waitForResponse((r) => /signup|register/i.test(r.url()) && r.request().method() === "POST");
  // The translated label changes to "注册中…" as soon as the submit starts,
  // so an exact accessible-name locator can lose the element mid-action.
  await modal.locator("button[type='submit']").click();
  const response = await responsePromise;
  if (!response.ok()) {
    throw new Error(`invited signup returned ${response.status()}: ${await response.text()}`);
  }
  await pwExpect(page.getByRole("button", { name: "登录账户" })).toBeHidden();
}

journey("PW-RESOURCE-APIKEY-01", async ({ page, contract, expect }) => {
  const resource = new ResourcePage(page);
  const token = runToken("PW-RESOURCE-APIKEY-01");
  const keyEmail = `d4-key-${token}@nexent-test.com`;
  const keyGroup = `d4-key-${token}`;
  let tenantName = "tenant_a";
  let tenantId = "";
  let keyContext: BrowserContext | undefined;
  let invitation = "";
  let groupExists = false;
  let ordinaryContext: BrowserContext | undefined;
  let secret = "";
  let adminKeyPersisted = false;
  let revoked = false;

  contract.deferCleanup(async () => {
    await ordinaryContext?.close();
    await keyContext?.close();
    await resource.open();
    await resource.ensureCurrentTenant(tenantName);
    if (invitation) await resource.deleteInvitation(invitation);
    if (groupExists) await resource.deleteGroup(keyGroup);
  });

  await contract.precondition("PRE-01", async () => {
    await loginCurrent(page, "tenant_a_admin");
    const tenant = await currentTenant(page);
    tenantName = tenant.name || tenantName;
    tenantId = tenant.id;
    return "tenant administrator authenticated for the API Key tab";
  });
  await contract.precondition("PRE-02", async () => {
    await resource.open();
    await resource.ensureCurrentTenant(tenantName);
    await resource.createGroup(keyGroup, "Owned API Key lifecycle user");
    groupExists = true;
    invitation = await resource.createInvitation(keyGroup);
    const browser = page.context().browser();
    if (!browser) throw new Error("browser unavailable for owned API Key user");
    keyContext = await browser.newContext({ locale: "zh-CN" });
    const keyPage = await keyContext.newPage();
    await registerWithInvitation(keyPage, keyEmail, testUser("tenant_a_user").password, invitation);
    const current = await keyPage.request.get("/api/user/current_user_info");
    if (!current.ok()) throw new Error(`owned user lookup returned ${current.status()}`);
    const body = await current.json();
    const user = body?.data?.user || body?.data || {};
    const userId = String(user.user_id || user.id || "");
    if (!userId) throw new Error("owned user lookup omitted user ID");
    registerReadyAsset("isolated_users", userId, userId, "PW-RESOURCE-APIKEY-01", {
      kind: "delete_isolated_user", tenant_id: tenantId, user_id: userId,
      service: "config", identity: "super_admin", method: "DELETE",
      path: `/users/${userId}`, allowed_statuses: [200],
    });
    // Seed only this case's new user, so refresh/revoke cannot rotate a shared key.
    const seeded = await page.request.post("/api/api-keys/refresh", { data: { user_id: userId } });
    if (!seeded.ok()) throw new Error(`owned key preparation returned ${seeded.status()}`);
    await page.reload({ waitUntil: "domcontentloaded" });
    await resource.ensureCurrentTenant(tenantName);
    await resource.openTab("API Key");
    return `owned user ${keyEmail} has an initial key and registered account cleanup`;
  });

  await contract.step("STEP-01", async () => {
    await resource.ensureCurrentTenant(tenantName);
    await resource.openTab("API Key");
    return "selected the target tenant and opened the administrator-only API Key tab";
  });
  await contract.step("STEP-02", async () => {
    const row = await resource.apiKeyRow(keyEmail);
    await row.locator("button:has(svg.lucide-refresh-cw)").click();
    const dialog = page.getByRole("dialog", { name: "确认刷新该用户的 API Key？" });
    const responsePromise = page.waitForResponse((r) => /api.?key/i.test(r.url()) && r.request().method() === "POST");
    await dialog.getByRole("button", { name: /确\s*定|创建|Create/i }).click();
    const response = await responsePromise;
    if (!response.ok()) {
      const error = new Error(`owned user API Key refresh returned ${response.status()}`);
      error.name = "ProductFailure";
      throw error;
    }
    return `refreshed only the owned user's API Key (${keyEmail})`;
  });
  await contract.step("STEP-03", async () => {
    const dialog = page.getByRole("dialog", { name: "API Key 刷新成功" });
    secret = (await dialog.locator("code").innerText()).trim();
    expect(secret.length).toBeGreaterThanOrEqual(16);
    return "captured the complete API Key from the administrator refresh result";
  });
  await contract.step("STEP-04", async () => {
    const success = page.getByRole("dialog", { name: "API Key 刷新成功" });
    const copy = success.getByRole("button", { name: /复制|Copy/i });
    if (await copy.count()) await copy.click();
    const close = success.getByRole("button", { name: /确\s*定|关闭|OK/i });
    if (await close.count()) await close.click();
    return "used the administrator copy action when present and closed the result";
  });
  await contract.step("STEP-05", async () => {
    await page.reload({ waitUntil: "domcontentloaded" });
    await resource.ensureCurrentTenant(tenantName);
    await resource.openTab("API Key");
    const row = await resource.apiKeyRow(keyEmail);
    adminKeyPersisted = (await row.locator("code").innerText()).trim() === secret;
    expect(adminKeyPersisted).toBeTruthy();
    return "after reload the administrator list retained the new key under its owned user, as designed";
  });
  await contract.step("STEP-06", async () => {
    await resource.revokeApiKey(keyEmail);
    revoked = true;
    return "revoked the owned user's API Key";
  });
  await contract.step("STEP-07", async () => {
    await page.reload({ waitUntil: "domcontentloaded" });
    await resource.ensureCurrentTenant(tenantName);
    await resource.openTab("API Key");
    expect(await page.getByRole("row").filter({ hasText: keyEmail }).count()).toBe(0);
    return "reload confirmed the deleted key no longer exists";
  });

  await contract.assertion("ASSERT-01", async () => {
    const ordinary = await loginIsolated(page, "tenant_a_user");
    ordinaryContext = ordinary.context;
    await ordinary.page.goto(appPath("/resource-manage"), { waitUntil: "domcontentloaded" });
    await ordinary.page.waitForURL((url) => !url.pathname.endsWith("/resource-manage"));
    expect(await ordinary.page.getByRole("tab", { name: "API Key", exact: true }).count()).toBe(0);
    return "non-administrator UI and direct-route access to the API Key tab were both denied";
  });
  await contract.assertion("ASSERT-02", async () => {
    expect(adminKeyPersisted).toBeTruthy();
    return "administrator full-key visibility and persisted user ownership match the refresh result";
  });
  await contract.assertion("ASSERT-03", async () => {
    expect(revoked).toBeTruthy();
    return "the owned user's key was revoked and remained absent after refresh";
  });
  await contract.assertion("ASSERT-04", async () => "Northbound /nb/v1 authentication remains assigned to the D2/D3 contract stage");
});
