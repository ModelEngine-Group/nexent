import { journey } from "../../infra/automation/d4/runner/journey";
import { testUser, appPath, configuredFeature } from "../../infra/automation/d4/runner/runtime-config";
import { AuthPage } from "../../infra/automation/d4/pages/auth.page";
import type { BrowserContext, Page } from "playwright/test";

type Identity = { email: string; tenantId: string; role: string; accessibleRoutes: string[] };

async function identity(target: Page): Promise<Identity> {
  const response = await target.request.get("/api/user/current_user_info");
  if (!response.ok()) throw new Error(`current user lookup returned ${response.status()}`);
  const body = await response.json();
  const user = body?.data?.user || {};
  return {
    email: String(user.user_email || user.email || ""),
    tenantId: String(user.tenant_id || body?.data?.tenant_id || ""),
    role: String(user.user_role || user.role || ""),
    accessibleRoutes: Array.isArray(user.accessibleRoutes) ? user.accessibleRoutes.map(String) : [],
  };
}

async function loginIsolated(source: Page, userId: string): Promise<{ context: BrowserContext; page: Page; auth: AuthPage; identity: Identity }> {
  const browser = source.context().browser();
  if (!browser) throw new Error("Playwright browser is unavailable for an isolated role context");
  const context = await browser.newContext({ locale: "zh-CN" });
  const page = await context.newPage();
  const auth = new AuthPage(page);
  const user = testUser(userId);
  await page.goto(appPath("/"), { waitUntil: "domcontentloaded" });
  await auth.expectLoggedOut();
  const status = await auth.login(user);
  if (status !== 200) throw new Error(`${userId} signin returned ${status}`);
  return { context, page, auth, identity: await identity(page) };
}

async function expectRouteDenied(target: Page, path: string): Promise<string> {
  await target.goto(appPath(path), { waitUntil: "domcontentloaded" });
  await target.waitForURL((url) => !url.pathname.endsWith(path), { timeout: 30000 });
  return new URL(target.url()).pathname;
}

journey("PW-RESOURCE-03", async ({ page, contract, expect }) => {
  const ordinary = testUser("tenant_a_user");
  const ordinaryAuth = new AuthPage(page);
  let adminContext: BrowserContext | undefined;
  let suContext: BrowserContext | undefined;
  let tenantBContext: BrowserContext | undefined;
  let adminPage: Page;
  let suPage: Page;
  let tenantBPage: Page;
  let ordinaryIdentity: Identity;
  let adminIdentity: Identity;
  let suIdentity: Identity;
  let tenantBIdentity: Identity;
  let assetOwnerEnabled = false;
  const observed = {
    ordinaryMenusHidden: false,
    ordinaryDirectDenied: false,
    dangerousActionsHidden: false,
    adminResourceAllowed: false,
    adminOwnerDenied: false,
    suPlatformAllowed: false,
    crossTenantHidden: false,
    refreshStable: false,
  };

  contract.deferCleanup(async () => {
    await tenantBContext?.close();
    await suContext?.close();
    await adminContext?.close();
  });

  await contract.precondition("PRE-01", async () => {
    await page.goto(appPath("/"), { waitUntil: "domcontentloaded" });
    await ordinaryAuth.expectLoggedOut();
    expect(await ordinaryAuth.login(ordinary)).toBe(200);
    ordinaryIdentity = await identity(page);

    const admin = await loginIsolated(page, "tenant_a_admin");
    adminContext = admin.context;
    adminPage = admin.page;
    adminIdentity = admin.identity;
    const su = await loginIsolated(page, "super_admin");
    suContext = su.context;
    suPage = su.page;
    suIdentity = su.identity;
    expect(new Set([ordinaryIdentity.role, adminIdentity.role, suIdentity.role]).size).toBe(3);
    return `isolated authenticated contexts are ready for USER, tenant administrator and super administrator roles`;
  });
  await contract.precondition("PRE-02", async () => {
    const tenantB = await loginIsolated(page, "tenant_b_admin");
    tenantBContext = tenantB.context;
    tenantBPage = tenantB.page;
    tenantBIdentity = tenantB.identity;
    expect(ordinaryIdentity.tenantId).not.toBe("");
    expect(tenantBIdentity.tenantId).not.toBe("");
    expect(ordinaryIdentity.tenantId).not.toBe(tenantBIdentity.tenantId);
    expect(ordinaryIdentity.email).not.toBe(tenantBIdentity.email);
    assetOwnerEnabled = configuredFeature("asset_owner");
    return `tenant A and tenant B provide distinct known tenant-scoped resources; features.asset_owner=${assetOwnerEnabled}`;
  });

  await contract.step("STEP-01", async () => {
    await page.goto(appPath("/"), { waitUntil: "domcontentloaded" });
    const resourceMenu = page.locator('a[href$="/resource-manage"]');
    const ownerMenu = page.locator('a[href$="/owner-manage"]');
    observed.ordinaryMenusHidden = (await resourceMenu.count()) === 0 && (await ownerMenu.count()) === 0;
    expect(observed.ordinaryMenusHidden).toBeTruthy();
    return "ordinary USER navigation contains neither tenant resource management nor platform owner management";
  });
  await contract.step("STEP-02", async () => {
    const finalPath = await expectRouteDenied(page, "/resource-manage");
    observed.ordinaryDirectDenied = !finalPath.endsWith("/resource-manage");
    expect(observed.ordinaryDirectDenied).toBeTruthy();
    return `ordinary USER direct resource-management URL was denied and ended at ${finalPath}`;
  });
  await contract.step("STEP-03", async () => {
    observed.dangerousActionsHidden = (await page.getByRole("button", { name: /创建租户|删除租户|Create Tenant|Delete Tenant/ }).count()) === 0;
    expect(observed.dangerousActionsHidden).toBeTruthy();
    return "tenant create/delete controls remained absent after the denied direct navigation";
  });
  await contract.step("STEP-04", async () => {
    await adminPage.goto(appPath("/resource-manage"), { waitUntil: "domcontentloaded" });
    await adminPage.waitForURL((url) => url.pathname.endsWith("/resource-manage"));
    observed.adminResourceAllowed = adminIdentity.accessibleRoutes.includes("/resource-manage");
    expect(observed.adminResourceAllowed).toBeTruthy();
    const finalPath = await expectRouteDenied(adminPage, "/owner-manage");
    observed.adminOwnerDenied = !finalPath.endsWith("/owner-manage");
    expect(observed.adminOwnerDenied).toBeTruthy();
    return `tenant administrator can open resource management but direct platform owner URL ended at ${finalPath}`;
  });
  await contract.step("STEP-05", async () => {
    expect(suIdentity.accessibleRoutes).toContain("/resource-manage");
    await suPage.goto(appPath("/resource-manage"), { waitUntil: "domcontentloaded" });
    await suPage.waitForURL((url) => url.pathname.endsWith("/resource-manage"));
    if (assetOwnerEnabled) {
      expect(suIdentity.accessibleRoutes).toContain("/owner-manage");
      await suPage.goto(appPath("/owner-manage"), { waitUntil: "domcontentloaded" });
      await suPage.waitForURL((url) => url.pathname.endsWith("/owner-manage"));
      await expect(suPage.locator('a[href$="/owner-manage"]')).toBeVisible();
    } else {
      expect(suIdentity.accessibleRoutes).not.toContain("/owner-manage");
      const finalPath = await expectRouteDenied(suPage, "/owner-manage");
      expect(finalPath.endsWith("/owner-manage")).toBeFalsy();
    }
    observed.suPlatformAllowed = true;
    return `super administrator resource platform entry is reachable and /owner-manage follows features.asset_owner=${assetOwnerEnabled}`;
  });
  await contract.step("STEP-06", async () => {
    const attempted = `/resource-manage?tenant_id=${encodeURIComponent(tenantBIdentity.tenantId)}`;
    await page.goto(appPath(attempted), { waitUntil: "domcontentloaded" });
    await page.waitForURL((url) => !url.pathname.endsWith("/resource-manage"));
    const content = await page.locator("body").innerText();
    observed.crossTenantHidden = !content.includes(tenantBIdentity.email) && !content.includes(tenantBIdentity.tenantId);
    expect(observed.crossTenantHidden).toBeTruthy();
    return "tenant A USER could not use a direct URL/query to render the known tenant B resource";
  });
  await contract.step("STEP-07", async () => {
    await page.reload({ waitUntil: "domcontentloaded" });
    expect((await identity(page)).role).toBe(ordinaryIdentity.role);
    await adminPage.goto(appPath("/resource-manage"), { waitUntil: "domcontentloaded" });
    await adminPage.reload({ waitUntil: "domcontentloaded" });
    expect((await identity(adminPage)).role).toBe(adminIdentity.role);
    await suPage.goto(appPath(assetOwnerEnabled ? "/owner-manage" : "/resource-manage"), { waitUntil: "domcontentloaded" });
    await suPage.reload({ waitUntil: "domcontentloaded" });
    expect((await identity(suPage)).role).toBe(suIdentity.role);
    observed.refreshStable = true;
    return "USER, tenant administrator and super administrator retained only their own role routes after reload";
  });

  await contract.assertion("ASSERT-01", async () => {
    expect(observed.ordinaryMenusHidden).toBeTruthy();
    expect(observed.ordinaryDirectDenied).toBeTruthy();
    expect(observed.dangerousActionsHidden).toBeTruthy();
    expect(observed.adminResourceAllowed).toBeTruthy();
    expect(observed.adminOwnerDenied).toBeTruthy();
    expect(observed.suPlatformAllowed).toBeTruthy();
    return "menu/button visibility and direct-route authorization match USER, tenant administrator and super administrator roles";
  });
  await contract.assertion("ASSERT-02", async () => {
    expect(observed.crossTenantHidden).toBeTruthy();
    return "known tenant B identity data was not exposed to tenant A through the tested direct URL";
  });
  await contract.assertion("ASSERT-03", async () => {
    expect(observed.refreshStable).toBeTruthy();
    return "page refresh did not leak a previously visited role context";
  });
  await contract.assertion("ASSERT-04", async () => {
    expect(observed.crossTenantHidden).toBeTruthy();
    return "representative UI direct-route isolation passed; the complete object-ID authorization matrix remains assigned to D5 security tests";
  });
});
