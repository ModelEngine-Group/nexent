import { randomBytes } from "node:crypto";
import { journey } from "../../infra/automation/d4/runner/journey";
import { testUser, appPath } from "../../infra/automation/d4/runner/runtime-config";
import { AuthPage } from "../../infra/automation/d4/pages/auth.page";
import { ProfilePage } from "../../infra/automation/d4/pages/profile.page";

journey("PW-PROFILE-01", async ({ page, contract, expect }) => {
  const user = testUser("tenant_a_dev");
  const temporaryPassword = `Px${randomBytes(8).toString("hex")}Aa1!`;
  const auth = new AuthPage(page);
  const profile = new ProfilePage(page);
  let userId = "";
  let passwordChanged = false;
  let activePassword = user.password;
  let tokenCleanupNeeded = false;
  let currentAccessKey = "";
  const observed = {
    oldPasswordRejected: false,
    newPasswordAccepted: false,
    originalPasswordRestored: false,
    initialCredentialShown: false,
    clipboardMatched: false,
    credentialHiddenAfterReload: false,
    regeneratedCredentialShown: false,
    regeneratedCredentialChanged: false,
    tokenDeleted: false,
    ungeneratedStateRestored: false,
  };

  async function signinByRequest(password: string): Promise<number> {
    const response = await page.request.post("/api/user/signin", { data: { email: user.username, password } });
    return response.status();
  }

  async function currentUserId(): Promise<string> {
    const response = await page.request.get("/api/user/current_user_info");
    if (!response.ok()) throw new Error(`current user lookup returned ${response.status()}`);
    const body = await response.json();
    const id = String(body?.data?.user?.user_id || body?.data?.user?.id || "");
    if (!id) throw new Error("current user response did not contain a user id");
    return id;
  }

  async function listTokens(): Promise<Array<{ token_id: number }>> {
    if (!userId) userId = await currentUserId();
    const response = await page.request.get(`/api/user/tokens?user_id=${encodeURIComponent(userId)}`);
    if (!response.ok()) throw new Error(`token list returned ${response.status()}`);
    const body = await response.json();
    return Array.isArray(body?.data) ? body.data : [];
  }

  contract.deferCleanup(async () => {
    const current = await page.request.get("/api/user/current_user_info");
    const currentBody = await current.json().catch(() => null);
    if (current.status() !== 200 || currentBody?.data == null) {
      const status = await signinByRequest(activePassword);
      if (status !== 200) throw new Error(`emergency signin returned ${status}`);
    }
    if (tokenCleanupNeeded) {
      for (const token of await listTokens()) {
        const response = await page.request.delete(`/api/user/tokens/${token.token_id}`);
        if (![200, 204, 404].includes(response.status())) throw new Error(`emergency token cleanup returned ${response.status()}`);
      }
      tokenCleanupNeeded = false;
    }
    if (passwordChanged) {
      const response = await page.request.put("/api/user/password", {
        data: { old_password: temporaryPassword, new_password: user.password },
      });
      if (response.status() !== 200) throw new Error(`emergency password restoration returned ${response.status()}`);
      passwordChanged = false;
      activePassword = user.password;
    }
  });

  await contract.precondition("PRE-01", async () => {
    await page.goto(appPath("/agents"), { waitUntil: "domcontentloaded" });
    await auth.expectLoggedOut();
    const status = await auth.login(user);
    expect(status).toBe(200);
    userId = await currentUserId();
    const tokens = await listTokens();
    expect(tokens).toHaveLength(0);
    return `dedicated ordinary local user ${user.username} authenticated and has no residual access token`;
  });
  await contract.precondition("PRE-02", async () => {
    expect(user.password.length).toBeGreaterThanOrEqual(8);
    expect(temporaryPassword).not.toBe(user.password);
    return "original password is available only from the configured secret environment and restoration is armed";
  });
  await contract.precondition("PRE-03", async () => {
    const base = new URL(process.env.NEXENT_BASE_URL || "http://localhost:3000");
    await page.context().grantPermissions(["clipboard-read", "clipboard-write"], { origin: base.origin });
    return "browser context granted clipboard read/write permission for copy verification";
  });

  await contract.step("STEP-01", async () => {
    await profile.open();
    return "account information and security sections loaded on /users";
  });
  await contract.step("STEP-02", async () => {
    const status = await profile.changePassword(user.password, temporaryPassword);
    expect(status).toBe(200);
    passwordChanged = true;
    activePassword = temporaryPassword;
    return "password was changed through the profile UI and the update endpoint returned 200";
  });
  await contract.step("STEP-03", async () => {
    await auth.logout();
    await page.getByRole("button", { name: "登录账户" }).click();
    const dialog = page.getByRole("dialog", { name: "登录" });
    await dialog.getByPlaceholder("your@email.com").fill(user.username);
    await dialog.getByPlaceholder("请输入密码").fill(user.password);
    const [oldResponse] = await Promise.all([
      page.waitForResponse((candidate) => candidate.url().includes("/api/user/signin") && candidate.request().method() === "POST"),
      dialog.getByRole("button", { name: "登 录", exact: true }).click(),
    ]);
    observed.oldPasswordRejected = oldResponse.status() === 401;
    expect(observed.oldPasswordRejected).toBeTruthy();
    await dialog.getByPlaceholder("请输入密码").fill(temporaryPassword);
    const [newResponse] = await Promise.all([
      page.waitForResponse((candidate) => candidate.url().includes("/api/user/signin") && candidate.request().method() === "POST"),
      dialog.getByRole("button", { name: "登 录", exact: true }).click(),
    ]);
    observed.newPasswordAccepted = newResponse.status() === 200;
    expect(observed.newPasswordAccepted).toBeTruthy();
    await auth.expectCurrentUser(user);
    return "old password was rejected, new password authenticated, and original-password restoration remains armed for test end";
  });
  await contract.step("STEP-04", async () => {
    await profile.open();
    const generated = await profile.generateToken(false);
    expect([200, 201]).toContain(generated.status);
    expect(generated.tokenId).toBeGreaterThan(0);
    expect(generated.accessKey.length).toBeGreaterThan(10);
    currentAccessKey = generated.accessKey;
    tokenCleanupNeeded = true;
    return `a run-scoped access credential was generated through the UI with HTTP ${generated.status}`;
  });
  await contract.step("STEP-05", async () => {
    await expect(page.getByText(currentAccessKey, { exact: true })).toBeVisible();
    observed.initialCredentialShown = true;
    const clipboard = await profile.copyToken(currentAccessKey);
    observed.clipboardMatched = clipboard === currentAccessKey;
    expect(observed.clipboardMatched).toBeTruthy();
    return "the complete credential was displayed in the one-time result state and the copy action matched it";
  });
  await contract.step("STEP-06", async () => {
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.getByText(currentAccessKey, { exact: true })).toBeHidden();
    const copyButton = page.getByRole("button").filter({ has: page.locator("svg.lucide-copy") });
    await expect(copyButton).toHaveCount(0);
    observed.credentialHiddenAfterReload = true;
    return "after reload the complete credential and copy control were no longer available";
  });
  await contract.step("STEP-07", async () => {
    const previous = currentAccessKey;
    const generated = await profile.generateToken(true);
    expect([200, 201]).toContain(generated.status);
    expect(generated.accessKey.length).toBeGreaterThan(10);
    currentAccessKey = generated.accessKey;
    observed.regeneratedCredentialChanged = currentAccessKey !== previous;
    observed.regeneratedCredentialShown = await page.getByText(currentAccessKey, { exact: true }).isVisible();
    expect(observed.regeneratedCredentialChanged).toBeTruthy();
    expect(observed.regeneratedCredentialShown).toBeTruthy();
    return "overwrite confirmation produced a different complete one-time credential";
  });
  await contract.step("STEP-08", async () => {
    const status = await profile.deleteToken(currentAccessKey);
    expect([200, 204]).toContain(status);
    tokenCleanupNeeded = false;
    observed.tokenDeleted = true;
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(profile.generateEntry()).toBeVisible();
    await expect(page.getByText(currentAccessKey, { exact: true })).toBeHidden();
    observed.ungeneratedStateRestored = true;

    await profile.changePassword(temporaryPassword, user.password);
    passwordChanged = false;
    activePassword = user.password;
    await auth.logout();
    const restoredStatus = await auth.login(user);
    observed.originalPasswordRestored = restoredStatus === 200;
    expect(observed.originalPasswordRestored).toBeTruthy();
    return "access token was deleted, the ungenerated UI state persisted after refresh, and the original password was restored and verified";
  });

  await contract.assertion("ASSERT-01", async () => {
    expect(observed.oldPasswordRejected).toBeTruthy();
    expect(observed.newPasswordAccepted).toBeTruthy();
    expect(observed.originalPasswordRestored).toBeTruthy();
    return "old password became invalid, new password worked, and the configured original password was restored at test end";
  });
  await contract.assertion("ASSERT-02", async () => {
    expect(observed.initialCredentialShown).toBeTruthy();
    expect(observed.clipboardMatched).toBeTruthy();
    expect(observed.credentialHiddenAfterReload).toBeTruthy();
    expect(observed.regeneratedCredentialShown).toBeTruthy();
    return "the complete credential appeared only immediately after creation/regeneration and was hidden after reload";
  });
  await contract.assertion("ASSERT-03", async () => {
    expect(observed.regeneratedCredentialChanged).toBeTruthy();
    expect(observed.tokenDeleted).toBeTruthy();
    expect(observed.ungeneratedStateRestored).toBeTruthy();
    return "regeneration replaced the credential and deletion restored the durable ungenerated UI state";
  });
  await contract.assertion("ASSERT-04", async () => {
    expect(observed.initialCredentialShown).toBeTruthy();
    return "UI credential lifecycle is verified here; real access-key authentication remains assigned to the D3 CONTRACT test in V5";
  });
});
