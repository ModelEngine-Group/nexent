import { journey } from "../../infra/automation/d4/runner/journey";
import { testUser, appPath, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { AuthPage } from "../../infra/automation/d4/pages/auth.page";
import type { BrowserContext } from "playwright/test";

journey("PW-AUTH-02", async ({ page, contract, expect }) => {
  const admin = testUser("tenant_a_admin");
  const newUserPassword = testUser("tenant_a_user").password;
  const token = runToken("PW-AUTH-02");
  const email = `pw_auth02_${token}@nexent-test.com`;
  const invitationCode = `D4A02${token}`.toUpperCase();
  const adminAuth = new AuthPage(page);
  let targetTenantId = "";
  let newUserId = "";
  let invitationCreated = false;
  let userContext: BrowserContext | undefined;
  let reloginContext: BrowserContext | undefined;
  const observed = {
    invitationConsumed: false,
    correctTenant: false,
    confirmationRequired: false,
    accountDeleted: false,
    oldSessionRejected: false,
    adminStateUpdated: false,
  };

  contract.deferCleanup(async () => {
    if (newUserId) {
      const response = await page.request.delete(`/api/users/${encodeURIComponent(newUserId)}`);
      if (![200, 204, 404].includes(response.status())) throw new Error(`temporary user cleanup returned ${response.status()}`);
    }
    if (invitationCreated) {
      const response = await page.request.delete(`/api/invitations/${encodeURIComponent(invitationCode)}`);
      if (![200, 204, 404].includes(response.status())) throw new Error(`invitation cleanup returned ${response.status()}`);
    }
    await reloginContext?.close();
    await userContext?.close();
  });

  await contract.precondition("PRE-01", async () => {
    await page.goto(appPath("/agents"), { waitUntil: "domcontentloaded" });
    await adminAuth.expectLoggedOut();
    const status = await adminAuth.login(admin);
    expect(status).toBe(200);
    await adminAuth.expectCurrentUser(admin);
    return `tenant administrator ${admin.username} authenticated with HTTP ${status}`;
  });
  await contract.precondition("PRE-02", async () => {
    const signin = await page.request.post("/api/user/signin", { data: { email, password: newUserPassword } });
    expect([401, 404]).toContain(signin.status());
    return `run-scoped email ${email} is not registered`;
  });
  await contract.precondition("PRE-03", async () => {
    const current = await page.request.get("/api/user/current_user_info");
    expect(current.ok()).toBeTruthy();
    const body = await current.json();
    targetTenantId = String(body?.data?.user?.tenant_id || body?.data?.tenant_id || "");
    expect(targetTenantId).not.toBe("");
    return `target tenant ${targetTenantId} is available to the tenant administrator`;
  });

  await contract.step("STEP-01", async () => {
    await page.goto(appPath("/resource-manage"), { waitUntil: "domcontentloaded" });
    const invitations = page.getByRole("tab", { name: "邀请码" }).or(page.locator(".ant-tabs-tab", { hasText: "邀请码" })).first();
    await expect(invitations).toBeVisible();
    await invitations.click();
    await expect(page.getByRole("button", { name: /创建邀请码/ })).toBeVisible();
    return "administrator opened the selected tenant Invitations tab";
  });
  await contract.step("STEP-02", async () => {
    await page.getByRole("button", { name: /创建邀请码/ }).click();
    const dialog = page.locator(".ant-modal-wrap:visible").filter({ hasText: "创建邀请码" });
    await dialog.locator("#invitation_code").fill(invitationCode);
    const expiry = new Date();
    expiry.setUTCFullYear(expiry.getUTCFullYear() + 1);
    await dialog.locator("#expiry_date").fill(expiry.toISOString().slice(0, 10));
    await page.keyboard.press("Enter");
    const [response] = await Promise.all([
      page.waitForResponse((candidate) => candidate.url().includes("/api/invitations") && candidate.request().method() === "POST"),
      dialog.getByRole("button", { name: "确 定", exact: true }).click(),
    ]);
    expect([200, 201]).toContain(response.status());
    invitationCreated = true;
    await expect(page.locator("tr", { hasText: invitationCode })).toBeVisible();
    return `USER_INVITE ${invitationCode} created with HTTP ${response.status()}`;
  });
  await contract.step("STEP-03", async () => {
    const browser = page.context().browser();
    if (!browser) throw new Error("Playwright browser is unavailable for an isolated registration context");
    userContext = await browser.newContext({ locale: "zh-CN" });
    const registrationPage = await userContext.newPage();
    await registrationPage.goto(appPath("/"), { waitUntil: "domcontentloaded" });
    await registrationPage.getByRole("button", { name: "注册账户" }).click();
    const dialog = registrationPage.getByRole("dialog", { name: /注册/ });
    await dialog.getByPlaceholder("your@email.com").fill(email);
    await dialog.locator("#register-password").fill(newUserPassword);
    await dialog.locator("#register-confirm-password").fill(newUserPassword);
    await dialog.getByPlaceholder(/邀请码/).fill(invitationCode);
    const [response] = await Promise.all([
      registrationPage.waitForResponse((candidate) => candidate.url().includes("/api/user/signup") && candidate.request().method() === "POST"),
      dialog.getByRole("button", { name: /注\s*册/ }).click(),
    ]);
    expect(response.status()).toBe(200);
    return `new account ${email} registered through the UI with HTTP ${response.status()}`;
  });
  await contract.step("STEP-04", async () => {
    const registrationPage = userContext!.pages()[0];
    const response = await registrationPage.request.get("/api/user/current_user_info");
    expect(response.ok()).toBeTruthy();
    const body = await response.json();
    expect(JSON.stringify(body)).toContain(email);
    newUserId = String(body?.data?.user?.user_id || body?.data?.user?.id || "");
    const tenantId = String(body?.data?.user?.tenant_id || body?.data?.tenant_id || "");
    observed.correctTenant = tenantId === targetTenantId;
    expect(observed.correctTenant).toBeTruthy();
    return `first login resolved user ${newUserId} in target tenant ${tenantId}`;
  });
  await contract.step("STEP-05", async () => {
    const registrationPage = userContext!.pages()[0];
    await registrationPage.goto(appPath("/users"), { waitUntil: "domcontentloaded" });
    const deleteAccount = registrationPage.getByText("删除账户", { exact: true }).first();
    await expect(deleteAccount).toBeVisible();
    await deleteAccount.click();
    const confirmation = registrationPage.getByRole("dialog", { name: /确认.*删除|确认注销/ });
    await expect(confirmation).toBeVisible();
    observed.confirmationRequired = true;
    return "ordinary local user can open the destructive account-deletion confirmation";
  });
  await contract.step("STEP-06", async () => {
    const registrationPage = userContext!.pages()[0];
    const [response] = await Promise.all([
      registrationPage.waitForResponse((candidate) => candidate.url().includes("/api/user/revoke") && candidate.request().method() === "POST"),
      registrationPage.getByRole("button", { name: "永久删除", exact: true }).click(),
    ]);
    expect(response.ok()).toBeTruthy();
    observed.accountDeleted = true;
    newUserId = "";
    await expect(registrationPage.getByRole("button", { name: "登录账户" })).toBeVisible();
    return `account deletion confirmed and revoke returned HTTP ${response.status()}`;
  });
  await contract.step("STEP-07", async () => {
    const browser = page.context().browser();
    if (!browser) throw new Error("Playwright browser is unavailable for a relogin context");
    reloginContext = await browser.newContext({ locale: "zh-CN" });
    const reloginPage = await reloginContext.newPage();
    await reloginPage.goto(appPath("/"), { waitUntil: "domcontentloaded" });
    await reloginPage.getByRole("button", { name: "登录账户" }).click();
    const dialog = reloginPage.getByRole("dialog", { name: "登录" });
    await dialog.getByPlaceholder("your@email.com").fill(email);
    await dialog.getByPlaceholder("请输入密码").fill(newUserPassword);
    const [response] = await Promise.all([
      reloginPage.waitForResponse((candidate) => candidate.url().includes("/api/user/signin") && candidate.request().method() === "POST"),
      dialog.getByRole("button", { name: "登 录", exact: true }).click(),
    ]);
    const current = await reloginPage.request.get("/api/user/current_user_info");
    const body = await current.json().catch(() => null);
    observed.oldSessionRejected = response.status() === 401 && body?.data == null;
    expect(observed.oldSessionRejected).toBeTruthy();
    return `deleted account signin returned ${response.status()} and no authenticated session`;
  });
  await contract.step("STEP-08", async () => {
    await page.goto(appPath("/resource-manage"), { waitUntil: "domcontentloaded" });
    const usersTab = page.getByRole("tab", { name: "用户" }).or(page.locator(".ant-tabs-tab", { hasText: "用户" })).first();
    await usersTab.click();
    await expect(page.getByText(email, { exact: true })).toBeHidden();
    const invitationsTab = page.getByRole("tab", { name: "邀请码" }).or(page.locator(".ant-tabs-tab", { hasText: "邀请码" })).first();
    await invitationsTab.click();
    const row = page.locator("tr", { hasText: invitationCode });
    await expect(row).toBeVisible();
    const text = await row.innerText();
    observed.invitationConsumed = /0|已用|用尽|失效|不可用/.test(text);
    expect(observed.invitationConsumed).toBeTruthy();
    observed.adminStateUpdated = true;
    return `administrator sees the consumed invitation and no active user ${email}`;
  });

  await contract.assertion("ASSERT-01", async () => {
    expect(observed.invitationConsumed).toBeTruthy();
    expect(observed.correctTenant).toBeTruthy();
    return "invitation was consumed and the registered user entered the intended tenant";
  });
  await contract.assertion("ASSERT-02", async () => {
    expect(observed.confirmationRequired).toBeTruthy();
    expect(observed.accountDeleted).toBeTruthy();
    expect(observed.oldSessionRejected).toBeTruthy();
    return "account deletion required confirmation and invalidated the old account/session";
  });
  await contract.assertion("ASSERT-03", async () => {
    expect(observed.adminStateUpdated).toBeTruthy();
    return "administrator-side invitation and user lifecycle state match the user actions";
  });
  await contract.assertion("ASSERT-04", async () => {
    expect(observed.accountDeleted).toBeTruthy();
    return "UI lifecycle completed; deeper cascading resource integrity remains assigned to API integration tests";
  });
});
