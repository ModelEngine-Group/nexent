// @ts-nocheck
import fs from "node:fs";
import path from "node:path";
import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
const scenarios: Array<{ name: string; run: (fixture: any) => Promise<void> }> = [];
const scenario = (name: string, run: (fixture: any) => Promise<void>) => scenarios.push({ name, run });

const baseUrl = process.env.NEXENT_BASE_URL ?? "http://localhost:3000";
const labels = JSON.parse(fs.readFileSync(path.join(process.env.NEXENT_REPO, "frontend/public/locales/zh/common.json"), "utf8"));

scenario("[NAV-MENU-D4-001] permitted children retain actual navigation without inert controls", async ({ page }) => {
  const writes = [];
  const json = (route, body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/**", (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (request.method() !== "GET" && pathname !== "/api/groups/list") writes.push(pathname);
    return json(route, {});
  });
  await page.route("**/api/tenant_config/deployment_version", (route) => json(route, { deployment_version: "speed", app_version: "test", status: "success", enable_agent_workbench: false }));
  await page.route("**/api/user/current_user_info", (route) => json(route, { data: { user: { user_id: "navigation-fixture", tenant_id: "navigation-tenant", user_email: "navigation@nexent.test", user_role: "SPEED", auth_provider: "local", groupIds: [], permissions: [], accessibleRoutes: ["/agents", "/newchat", "/agent-space"] } } }));
  await page.route("**/api/memory/config/load", (route) => json(route, { MEMORY_SWITCH: "N" }));
  await page.route("**/api/groups/list", (route) => json(route, { data: [], total: 0 }));
  await page.route("**/api/agent/list/page?*", (route) => json(route, { items: [], pagination: { page: 1, page_size: 10, total: 0, total_pages: 0 } }));
  await page.goto(`${baseUrl}/zh/agents`);
  const nav = page.getByRole("navigation");
  const agents = nav.getByRole("button", { name: labels["sidebar.agentConfig"], exact: true });
  await expect(agents).toBeVisible();
  await expect(agents).toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("button", { name: labels["sidebar.agentDev"], exact: true })).toHaveCount(0);
  await expect(nav.getByRole("button", { name: labels["sidebar.resourceSpace"], exact: true })).toHaveCount(0);
  await expect(nav.getByRole("button", { name: labels["sidebar.modelConfig"], exact: true })).toHaveCount(0);
  await expect(nav.getByRole("button", { name: labels["sidebar.agentSpace"], exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: labels["notifications.bell.label"], exact: true })).toHaveCount(0);
  const footer = nav.locator("xpath=following-sibling::div");
  await expect(footer.locator(".ant-dropdown-trigger")).toBeVisible();
  await nav.getByRole("button", { name: labels["sidebar.startChat"], exact: true }).click();
  await expect(page).toHaveURL(/\/zh\/newchat$/);
  await expect(nav.getByRole("button", { name: labels["sidebar.startChat"], exact: true })).toHaveAttribute("aria-current", "page");
  await agents.click();
  await expect(page).toHaveURL(/\/zh\/agents$/);
  await expect(agents).toHaveAttribute("aria-current", "page");
  expect(writes).toEqual([]);
});

for (const locale of ["zh", "en"]) {
  scenario(`[NAV-MENU-D4-001] ${locale} Workbench follows Home and preserves its route`, async ({ page }) => {
    const text = JSON.parse(fs.readFileSync(path.join(process.env.NEXENT_REPO, `frontend/public/locales/${locale}/common.json`), "utf8"));
    const json = (route, body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    await page.route("**/api/**", (route) => json(route, {}));
    await page.route("**/api/tenant_config/deployment_version", (route) => json(route, { deployment_version: "speed", app_version: "test", status: "success", enable_agent_workbench: true }));
    await page.route("**/api/user/current_user_info", (route) => json(route, { data: { user: { user_id: "navigation-fixture", tenant_id: "navigation-tenant", user_email: "navigation@nexent.test", user_role: "SPEED", auth_provider: "local", groupIds: [], permissions: [], accessibleRoutes: ["/", "/agents", "/newchat", "/workbench"] } } }));
    await page.route("**/api/memory/config/load", (route) => json(route, { MEMORY_SWITCH: "N" }));
  await page.route("**/api/groups/list", (route) => json(route, { data: [], total: 0 }));
    await page.route("**/api/agent/list/page?*", (route) => json(route, { items: [], pagination: { page: 1, page_size: 10, total: 0, total_pages: 0 } }));
    await page.goto(`${baseUrl}/${locale}/agents`);
    const nav = page.getByRole("navigation");
    const workbenchLabel = locale === "zh" ? "工作台" : "Workbench";
    await nav.hover();
    await expect(nav.getByRole("button").nth(0)).toHaveText(text["sidebar.homePage"]);
    await expect(nav.getByRole("button").nth(1)).toHaveText(workbenchLabel);
    await expect(nav.getByRole("button").nth(2)).toHaveText(text["sidebar.startChat"]);
    await nav.getByRole("button", { name: workbenchLabel, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/${locale}/workbench$`));
    await expect(nav.getByRole("button", { name: workbenchLabel, exact: true })).toHaveAttribute("aria-current", "page");
  });
}

scenario("[NAV-MENU-D4-001] account menu replaces bars and switches language on another page", async ({ page }) => {
  const text = JSON.parse(fs.readFileSync(path.join(process.env.NEXENT_REPO, "frontend/public/locales/zh/common.json"), "utf8"));
  const writes = [];
  const json = (route, body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/**", (route) => {
    if (route.request().method() !== "GET" && !route.request().url().includes("/groups/list")) writes.push(new URL(route.request().url()).pathname);
    return json(route, {});
  });
  await page.route("**/locales/*/custom.json", async (route) => {
    const response = await route.fetch();
    return json(route, { ...await response.json(), aboutConfig: "open" });
  });
  await page.route("**/api/tenant_config/deployment_version", (route) => json(route, { deployment_version: "speed", app_version: "v2.6.0", status: "success", enable_agent_workbench: false }));
  await page.route("**/api/user/current_user_info", (route) => json(route, { data: { user: { user_id: "navigation-fixture", tenant_id: "navigation-tenant", user_email: "navigation@nexent.test", user_role: "SPEED", auth_provider: "local", groupIds: [], permissions: [], accessibleRoutes: ["/agents", "/newchat", "/agent-space"] } } }));
  await page.route("**/api/memory/config/load", (route) => json(route, { MEMORY_SWITCH: "N" }));
  await page.route("**/api/groups/list", (route) => json(route, { data: [], total: 0 }));
  await page.route("**/api/monitoring/status", (route) => json(route, { code: 0, data: { telemetry_enabled: true, dashboard_url: "https://monitoring.nexent.test", dashboard_allowed_roles: ["SPEED"] } }));
  await page.route("**/api/repository/**", (route) => json(route, { items: [], pagination: { page: 1, page_size: 10, total: 0, total_pages: 0 } }));
  await page.route("**/api/tag-libraries**", (route) => json(route, []));
  await page.route("**/api/agent/list/page?*", (route) => json(route, { items: [], pagination: { page: 1, page_size: 10, total: 0, total_pages: 0 } }));
  await page.goto(`${baseUrl}/zh/agent-space`);
  await expect(page.locator(".ant-layout-header, .ant-layout-footer")).toHaveCount(0);
  const button = page.getByRole("button", { name: text["accountMenu.open"], exact: true });
  await button.click();
  const menu = page.getByRole("menu").first();
  await expect(menu).toBeVisible();
  await expect(menu.getByText("v2.6.0", { exact: true })).toBeVisible();
  await expect(menu.getByText("navigation@nexent.test", { exact: true })).toBeVisible();
  await expect(menu.getByRole("link", { name: text["profile.title"], exact: true })).toHaveAttribute("href", "/zh/users");
  await expect(menu.getByRole("link", { name: "ModelEngine", exact: true })).toHaveAttribute("href", "http://modelengine-ai.net");
  await expect(menu.getByRole("link", { name: text["accountMenu.github"], exact: true })).toHaveAttribute("href", "https://github.com/ModelEngine-Group/nexent");
  await expect(menu.getByRole("link", { name: text["page.termsOfUse"], exact: true })).toBeVisible();
  await expect(menu.getByText(new RegExp(`©.*${new Date().getFullYear()}`))).toBeVisible();
  await expect(menu.getByText("外观设置", { exact: true })).toHaveCount(0);
  const readGeometry = () => menu.evaluate((element) => {
    const style = getComputedStyle(element);
    const identity = element.querySelector('.account-menu-identity');
    const row = element.querySelector('[data-menu-id$="profile"]');
    return { width: element.getBoundingClientRect().width, radius: style.borderRadius, padding: style.paddingTop, shadow: style.boxShadow, identityHeight: identity.getBoundingClientRect().height, rowHeight: row.getBoundingClientRect().height, rowWidth: row.getBoundingClientRect().width, font: getComputedStyle(row.querySelector('.ant-dropdown-menu-title-content')).fontSize };
  });
  await expect.poll(readGeometry).toMatchObject({ width: 280, radius: "12px", padding: "4px", identityHeight: 68, rowHeight: 40, rowWidth: 272, font: "16px" });
  const geometry = await readGeometry();
  expect(geometry.shadow).toContain("24px");
  const badge = menu.locator(".ant-tag");
  await expect(badge).toHaveCSS("color", "rgb(31, 85, 181)");
  await expect(badge).toHaveCSS("background-color", "rgba(208, 216, 253, 0.5)");
  await expect(badge).toHaveCSS("height", "24px");
  await menu.getByText(text["accountMenu.language"], { exact: true }).hover();
  const english = page.getByText("English", { exact: true });
  await expect(english).toBeVisible();
  await expect(page.getByLabel(text["accountMenu.selectedLanguage"])).toBeVisible();
  await expect.poll(() => english.locator("xpath=ancestor::li[1]").evaluate(el => el.getBoundingClientRect().width)).toBe(217);
  await english.click();
  await expect(page).toHaveURL(/\/en\/agent-space$/);
  expect((await page.context().cookies()).find(cookie => cookie.name === "NEXT_LOCALE")?.value).toBe("en");
  await expect(page.locator(".ant-layout-header, .ant-layout-footer")).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 720 });
  const englishText = JSON.parse(fs.readFileSync(path.join(process.env.NEXENT_REPO, "frontend/public/locales/en/common.json"), "utf8"));
  await page.getByRole("button", { name: englishText["accountMenu.open"], exact: true }).click();
  const bounds = await page.getByRole("menu").first().boundingBox();
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(390);
  expect(writes).toEqual([]);
});

scenario("[NAV-MENU-D4-001] hover rail overlays content and holds account popup", async ({ page }) => {
  const text = JSON.parse(fs.readFileSync(path.join(process.env.NEXENT_REPO, "frontend/public/locales/en/common.json"), "utf8"));
  const longLabel = "Knowledge base configuration and document indexing";
  let monitoringRequests = 0;
  let profileRequests = 0;
  page.on('request', request => { if (new URL(request.url()).pathname.endsWith('/users')) profileRequests += 1; });
  const json = (route, body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.route("**/api/**", (route) => json(route, {}));
  await page.route("**/locales/en/common.json", (route) => json(route, { ...text, "sidebar.knowledgeBaseConfig": longLabel }));
  await page.route("**/api/tenant_config/deployment_version", (route) => json(route, { deployment_version: "speed", app_version: "v2.6.0", status: "success" }));
  await page.route("**/api/user/current_user_info", (route) => json(route, { data: { user: { user_id: "hover-fixture", tenant_id: "hover-tenant", user_email: "hover@nexent.test", user_role: "SPEED", role: "SPEED", auth_provider: "local", groupIds: [], permissions: [], accessibleRoutes: ["/agents", "/models", "/knowledges", "/agent-space"] } } }));
  await page.route("**/api/groups/list", (route) => json(route, { data: [], total: 0 }));
  await page.route("**/api/tag-libraries**", (route) => json(route, []));
  await page.route("**/api/monitoring/status", (route) => {
    monitoringRequests += 1;
    return json(route, { code: 0, data: { telemetry_enabled: true, dashboard_url: "https://monitoring.nexent.test", dashboard_allowed_roles: ["SPEED"] } });
  });
  await page.route("**/api/repository/**", (route) => json(route, { items: [], pagination: { total: 0, page: 1, page_size: 10, total_pages: 0 } }));
  await page.route("**/api/agent/list/page?*", (route) => json(route, { items: [], pagination: { total: 0, page: 1, page_size: 10, total_pages: 0 } }));
  await page.goto(`${baseUrl}/en/agent-space`);
  const rail = page.locator('[data-sidebar-expanded]');
  await expect(rail).toHaveAttribute('data-sidebar-expanded', 'false');
  const item = page.getByRole('navigation').getByRole('button', { name: longLabel, exact: true });
  await expect(item).toHaveText('');
  const contentX = await page.locator('.ant-layout-content').evaluate(el => el.getBoundingClientRect().left);
  await expect.poll(() => rail.evaluate(el => el.getBoundingClientRect().width)).toBe(64);
  await rail.hover({ position: { x: 30, y: 100 } });
  await expect.poll(() => rail.evaluate(el => el.getBoundingClientRect().width)).toBe(240);
  expect(await page.locator('.ant-layout-content').evaluate(el => el.getBoundingClientRect().left)).toBe(contentX);
  await expect(item).toHaveText(longLabel);
  const positions = await item.evaluate(el => { const icon=el.querySelector('svg').getBoundingClientRect(); const label=el.querySelector('.ant-typography').getBoundingClientRect(); return { iconY:icon.y+icon.height/2, labelY:label.y+label.height/2 }; });
  expect(Math.abs(positions.iconY-positions.labelY)).toBeLessThanOrEqual(1);
  await item.locator('.ant-typography').hover();
  await expect(page.getByRole('tooltip').filter({ hasText: longLabel })).toBeVisible();
  await page.mouse.move(650, 200);
  await expect.poll(() => rail.evaluate(el => el.getBoundingClientRect().width)).toBe(64);
  await rail.hover({ position: { x: 30, y: 100 } });
  await expect.poll(() => monitoringRequests).toBeGreaterThan(0);
  const requestBaseline = monitoringRequests;
  await page.getByRole('button', { name: text['accountMenu.open'], exact: true }).click();
  await page.mouse.move(650, 200);
  await expect(page.getByRole('menu').first()).toBeVisible();
  await expect(page.getByRole('link', { name: text['profile.title'], exact: true })).toHaveAttribute('href', '/en/users');
  await expect.poll(() => rail.evaluate(el => el.getBoundingClientRect().width)).toBe(240);
  await page.locator('.ant-layout-content').click({ position: { x: 650, y: 100 } });
  await expect.poll(() => rail.evaluate(el => el.getBoundingClientRect().width)).toBe(64);
  for (let repeat = 0; repeat < 2; repeat += 1) {
    await rail.hover({ position: { x: 30, y: 100 } });
    await page.getByRole('button', { name: text['accountMenu.open'], exact: true }).click();
    await expect(page.getByRole('menu').first()).toBeVisible();
    await page.locator('.ant-layout-content').click({ position: { x: 650, y: 100 } });
    await expect.poll(() => rail.evaluate(el => el.getBoundingClientRect().width)).toBe(64);
  }
  expect(monitoringRequests).toBe(requestBaseline);
  expect(profileRequests).toBe(0);
  await rail.hover({ position: { x: 30, y: 100 } });
  await page.getByRole('button', { name: text['accountMenu.open'], exact: true }).click();
  await page.getByRole('link', { name: text['profile.title'], exact: true }).click();
  await expect(page).toHaveURL(`${baseUrl}/en/users`);
  expect(profileRequests).toBeGreaterThan(0);
});

journey("NAV-MENU-D4-001", async ({ page, contract }) => {
  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    const response = await page.request.get(baseUrl);
    expect(response.ok()).toBe(true);
  });
  expect(scenarios).toHaveLength(5);
  for (const [index, scenario] of scenarios.entries()) {
    if (page.url().startsWith(baseUrl)) await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
    await page.goto("about:blank");
    await page.unrouteAll({ behavior: "wait" });
    await page.context().clearCookies();
    // The audited assertion executes the complete scenario, including its boundary guards.
    await contract.step(contract.expectedIds("steps")[index], async () => {
      await contract.assertion(contract.expectedIds("assertions")[index], async () => {
        await scenario.run({ page });
        return scenario.name;
      });
      return scenario.name;
    });
  }
});
