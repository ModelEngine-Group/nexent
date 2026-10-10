import { journey } from "../../infra/automation/d4/runner/journey";
import { testUser, appPath, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { AuthPage } from "../../infra/automation/d4/pages/auth.page";
import type { BrowserContext } from "playwright/test";

journey("PW-AUTH-01", async ({ page, contract, expect }) => {
  const user = testUser("tenant_a_user");
  const auth = new AuthPage(page);
  const observed = {
    unauthenticatedProtectedContentHidden: false,
    loginStatus: 0,
    currentUserVerified: false,
    protectedRoutesVerified: false,
    reloadVerified: false,
    secondTabVerified: false,
    logoutStatus: 0,
    oldSessionRejected: false,
  };

  await contract.precondition("PRE-01", async () => `configured local test user ${user.username} is available`);
  await contract.precondition("PRE-02", async () => {
    const cookies = await page.context().cookies();
    expect(cookies).toHaveLength(0);
    return "new browser context has no cookies";
  });
  await contract.precondition("PRE-03", async () => {
    const response = await page.request.get(appPath("/"));
    expect(response.ok()).toBeTruthy();
    return `frontend health returned ${response.status()}`;
  });

  await contract.step("STEP-01", async () => {
    await auth.openProtected("/agents");
    await auth.expectLoggedOut();
    await expect(page.getByText("智能体开发", { exact: true })).toBeHidden();
    observed.unauthenticatedProtectedContentHidden = true;
    return "unauthenticated /agents displayed login entry without protected agent content";
  });
  await contract.step("STEP-02", async () => {
    observed.loginStatus = await auth.login(user);
    expect(observed.loginStatus).toBe(200);
    return `signin completed with HTTP ${observed.loginStatus}`;
  });
  await contract.step("STEP-03", async () => {
    await auth.expectCurrentUser(user);
    await expect(page.getByText("智能体开发", { exact: true })).toBeVisible();
    observed.currentUserVerified = true;
    return `current user ${user.username} and protected navigation are visible`;
  });
  await contract.step("STEP-04", async () => {
    for (const path of ["/models", "/knowledges"]) {
      await page.goto(appPath(path), { waitUntil: "domcontentloaded" });
      await expect(page.getByRole("button", { name: "登录账户" })).toBeHidden();
      await auth.expectCurrentUser(user);
    }
    observed.protectedRoutesVerified = true;
    return "models and knowledges opened without a second login";
  });
  await contract.step("STEP-05", async () => {
    await page.reload({ waitUntil: "domcontentloaded" });
    await auth.expectCurrentUser(user);
    observed.reloadVerified = true;
    return "session restored after page reload";
  });
  await contract.step("STEP-06", async () => {
    const secondPage = await page.context().newPage();
    contract.deferCleanup(async () => secondPage.close());
    const secondAuth = new AuthPage(secondPage);
    await secondAuth.openProtected("/agents");
    await secondAuth.expectCurrentUser(user);
    observed.secondTabVerified = true;
    return "same browser context restored the session in a second tab";
  });
  await contract.step("STEP-07", async () => {
    await page.bringToFront();
    observed.logoutStatus = await auth.logout();
    expect(observed.logoutStatus).toBeLessThan(500);
    return `logout completed with HTTP ${observed.logoutStatus}`;
  });
  await contract.step("STEP-08", async () => {
    await auth.openProtected("/agents");
    await auth.expectLoggedOut();
    const currentUser = await page.request.get("/api/user/current_user_info");
    const currentUserBody = await currentUser.json().catch(() => null);
    observed.oldSessionRejected =
      currentUser.status() === 401 ||
      currentUser.status() === 403 ||
      (currentUser.status() === 200 && currentUserBody?.data == null);
    expect(observed.oldSessionRejected).toBeTruthy();
    expect(JSON.stringify(currentUserBody)).not.toContain(user.username);
    return `old session rejected with HTTP ${currentUser.status()} and no authenticated user data`;
  });

  await contract.assertion("ASSERT-01", async () => {
    expect(observed.unauthenticatedProtectedContentHidden).toBeTruthy();
    expect(observed.currentUserVerified).toBeTruthy();
    return "protected content was hidden before login and the configured user identity was verified after login";
  });
  await contract.assertion("ASSERT-02", async () => {
    expect(observed.reloadVerified).toBeTruthy();
    expect(observed.secondTabVerified).toBeTruthy();
    return "session survived reload and was shared by a second tab in the same context";
  });
  await contract.assertion("ASSERT-03", async () => {
    expect(observed.oldSessionRejected).toBeTruthy();
    return "logout invalidated the old session";
  });
  await contract.assertion("ASSERT-04", async () => {
    expect(observed.loginStatus).toBeLessThan(500);
    expect(observed.logoutStatus).toBeLessThan(500);
    expect(await page.locator("body").innerText()).not.toContain(user.password);
    return "authentication flow completed without 5xx and the password was not rendered";
  });
});

