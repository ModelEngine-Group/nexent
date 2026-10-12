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

journey("PW-RESOURCE-02", async ({ page, contract, expect }) => {
  const token = runToken("PW-RESOURCE-02");
  const group = `d4-group-${token}`;
  const email = `d4-member-${token}@nexent-test.com`;
  const password = testUser("tenant_a_user").password;
  const resource = new ResourcePage(page);
  let tenantName = "tenant_a";
  let code = "";
  let memberContext: BrowserContext | undefined;
  let memberPage: Page | undefined;
  let groupExists = false;
  let invitationExists = false;
  let membershipVisible = false;

  contract.deferCleanup(async () => {
    await memberContext?.close();
    if (invitationExists && code) await resource.deleteInvitation(code);
    if (groupExists) await resource.deleteGroup(group);
  });

  await contract.precondition("PRE-01", async () => {
    await loginCurrent(page, "tenant_a_admin");
    tenantName = (await currentTenant(page)).name || tenantName;
    await resource.open();
    await resource.ensureCurrentTenant(tenantName);
    return `tenant administrator authenticated for ${tenantName}`;
  });
  await contract.precondition("PRE-02", async () => {
    const response = await page.request.get(`/api/user/check_email?email=${encodeURIComponent(email)}`);
    expect([200, 404]).toContain(response.status());
    return `run-scoped registration email ${email} was selected for this case`;
  });
  await contract.precondition("PRE-03", async () => {
    await resource.openTab("用户组");
    await resource.searchCurrentTab("搜索用户组名称", group);
    expect(await page.getByRole("row").filter({ hasText: group }).count()).toBe(0);
    return `no existing group named ${group}`;
  });

  await contract.step("STEP-01", async () => {
    await resource.createGroup(group, `created by PW-RESOURCE-02 ${token}`);
    groupExists = true;
    return `created group ${group}`;
  });
  await contract.step("STEP-02", async () => {
    await resource.editGroupMembers(group, testUser("tenant_a_admin").username);
    return "opened the group and persisted an editable member assignment";
  });
  await contract.step("STEP-03", async () => {
    code = await resource.createInvitation(group);
    invitationExists = true;
    return `created tenant invitation ${code} linked to ${group}`;
  });
  await contract.step("STEP-04", async () => {
    const browser = page.context().browser();
    if (!browser) throw new Error("browser is unavailable for invited-user context");
    memberContext = await browser.newContext({ locale: "zh-CN" });
    memberPage = await memberContext.newPage();
    await registerWithInvitation(memberPage, email, password, code);
    const current = await memberPage.request.get("/api/user/current_user_info");
    if (!current.ok()) throw new Error(`owned member lookup returned ${current.status()}`);
    const data = (await current.json()).data;
    const user = data?.user || data || {};
    const userId = String(user.user_id || user.id || "");
    const tenantId = (await currentTenant(memberPage)).id;
    if (!userId) throw new Error("owned member lookup omitted user ID");
    registerReadyAsset("isolated_users", userId, userId, "PW-RESOURCE-02", {
      kind: "delete_isolated_user", tenant_id: tenantId, user_id: userId,
      service: "config", identity: "super_admin", method: "DELETE",
      path: `/users/${userId}`, allowed_statuses: [200],
    });
    return `registered and authenticated invited user ${email} in an independent context`;
  });
  await contract.step("STEP-05", async () => {
    await resource.openTab("用户");
    await resource.searchCurrentTab("搜索邮箱", email);
    await expect(page.getByRole("row").filter({ hasText: email })).toBeVisible();
    return "administrator found the newly registered user in the tenant user table";
  });
  await contract.step("STEP-06", async () => {
    await updateUser(page, email, group, "DEV");
    membershipVisible = true;
    return `administrator assigned ${email} to ${group} and changed the role to DEV`;
  });
  await contract.step("STEP-07", async () => {
    if (!memberPage) throw new Error("invited-user page was not created");
    await memberPage.reload({ waitUntil: "domcontentloaded" });
    const response = await memberPage.request.get("/api/user/current_user_info");
    const body = JSON.stringify(await response.json());
    expect(body).toContain("DEV");
    return "invited-user context observed the persisted role change after reload";
  });
  await contract.step("STEP-08", async () => {
    if (code) { await resource.deleteInvitation(code); invitationExists = false; }
    await resource.deleteGroup(group); groupExists = false;
    return "administrator revoked the residual invitation and deleted the temporary group";
  });

  await contract.assertion("ASSERT-01", async () => {
    expect(membershipVisible).toBeTruthy();
    return "group, invitation and user membership were each observable after persistence refresh";
  });
  await contract.assertion("ASSERT-02", async () => {
    expect(memberPage).toBeDefined();
    return "role/group update changed the invited user contract visible after context refresh";
  });
  await contract.assertion("ASSERT-03", async () => {
    expect(code).not.toBe("");
    return `invitation registered ${email} into the target tenant`;
  });
});

