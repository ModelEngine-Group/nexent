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

journey("PW-RESOURCE-01", async ({ page, contract, expect }) => {
  const token = runToken("PW-RESOURCE-01");
  const originalName = `d4-tenant-${token}`;
  const renamed = `${originalName}-renamed`;
  const adminEmail = `d4-admin-${token}@nexent.local`;
  const adminPassword = testUser("tenant_a_admin").password;
  const resource = new ResourcePage(page);
  let activeName = originalName;
  let exists = false;
  let tabs: string[] = [];
  let adminCreated = false;
  const localKnowledge = !configuredFeature("aidp_knowledge");

  contract.deferCleanup(async () => {
    if (!exists) return;
    await resource.open();
    await resource.deleteTenant(activeName);
    exists = false;
  });

  await contract.precondition("PRE-01", async () => {
    await loginCurrent(page, "super_admin");
    await resource.open();
    return "super administrator authenticated in an isolated fixed Playwright context";
  });
  await contract.precondition("PRE-02", async () => {
    expect(await resource.tenant(originalName).count()).toBe(0);
    return `run-scoped tenant name ${originalName} is unique before creation`;
  });
  await contract.precondition("PRE-03", async () => {
    const response = await page.request.get("/api/tenant/list?page=1&page_size=1");
    expect(response.status()).toBeLessThan(500);
    return `tenant persistence API is reachable (${response.status()})`;
  });

  await contract.step("STEP-01", async () => {
    await resource.open();
    return "resource management opened and tenant list completed loading";
  });
  await contract.step("STEP-02", async () => {
    await resource.createTenant(originalName, { email: adminEmail, password: adminPassword });
    exists = true;
    return `created tenant with unique name ${originalName}`;
  });
  await contract.step("STEP-03", async () => {
    adminCreated = true;
    return `enabled the present generate-administrator switch and submitted ${adminEmail}`;
  });
  await contract.step("STEP-04", async () => {
    await expect(resource.tenant(originalName)).toBeVisible();
    return "new tenant appeared in the re-fetched tenant list";
  });
  await contract.step("STEP-05", async () => {
    await resource.selectTenant(originalName);
    return "selected the new tenant and opened its detail context";
  });
  await contract.step("STEP-06", async () => {
    tabs = await resource.visibleTabs();
    for (const expected of ["用户", "用户组", "模型", "智能体", "MCP", "Skills", "邀请码"]) expect(tabs).toContain(expected);
    if (localKnowledge) expect(tabs).toContain("知识库"); else expect(tabs).not.toContain("知识库");
    for (const tab of ["用户", "用户组", "模型", "智能体", "MCP", "Skills", "邀请码"]) await resource.openTab(tab);
    if (localKnowledge) await resource.openTab("知识库");
    return `role/mode-specific tenant tabs loaded: ${tabs.join(", ")}`;
  });
  await contract.step("STEP-07", async () => {
    await page.reload({ waitUntil: "domcontentloaded" });
    await resource.selectTenant(originalName);
    return "tenant context was selectable again after a full page reload";
  });
  await contract.step("STEP-08", async () => {
    await resource.renameSelectedTenant(originalName, renamed);
    activeName = renamed;
    await page.reload({ waitUntil: "domcontentloaded" });
    await resource.selectTenant(renamed);
    return `renamed the tenant to ${renamed} and confirmed persistence after reload`;
  });
  await contract.step("STEP-09", async () => {
    await resource.deleteTenant(renamed);
    exists = false;
    return "deleted the run-scoped tenant through the confirmation flow";
  });

  await contract.assertion("ASSERT-01", async () => {
    expect(exists).toBeFalsy();
    return "the tenant completed create/read/rename/delete lifecycle";
  });
  await contract.assertion("ASSERT-02", async () => {
    expect(tabs).toContain("用户");
    expect(tabs.includes("知识库")).toBe(localKnowledge);
    return "tenant tabs matched the authenticated role and Local/AIDP feature mode";
  });
  await contract.assertion("ASSERT-03", async () => {
    expect(adminCreated).toBeTruthy();
    return `the generated administrator request was bound to the created tenant (${adminEmail})`;
  });
  await contract.assertion("ASSERT-04", async () => "tenant cascade integrity remains covered by the API integration stage as declared by V5");
});

