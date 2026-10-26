// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

// @ts-nocheck
import fs from "node:fs";
import path from "node:path";
import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
const scenarios: Array<{ name: string; run: (fixture: any) => Promise<void> }> = [];
const scenario = (name: string, run: (fixture: any) => Promise<void>) => scenarios.push({ name, run });

const baseUrl = process.env.NEXENT_BASE_URL ?? "http://localhost:3000";
const labels = JSON.parse(fs.readFileSync(path.join(process.env.NEXENT_REPO, "frontend/public/locales/zh/common.json"), "utf8"));

function defaultApiBody(route) {
  // listLibraries has an array wire contract; an object crashes real pages.
  return new URL(route.request().url()).pathname === "/api/tag-libraries" ? [] : {};
}

async function expectReferenceColor(locator, property, reference) {
  await expect.poll(() => locator.evaluate((element, args) => {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 1;
    const context = canvas.getContext('2d');
    const sample = color => {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = color;
      context.fillRect(0, 0, 1, 1);
      return [...context.getImageData(0, 0, 1, 1).data];
    };
    const actual = sample(getComputedStyle(element).getPropertyValue(args.property));
    const expected = sample(args.reference);
    return Math.max(...actual.map((channel, index) => Math.abs(channel - expected[index])));
  }, { property, reference })).toBeLessThanOrEqual(1);
}

scenario("[NAV-MENU-D4-001] permitted children retain actual navigation without inert controls", async ({ page }) => {
  const writes = [];
  const json = (route, body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/**", (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (request.method() !== "GET" && pathname !== "/api/groups/list") writes.push(pathname);
    return json(route, defaultApiBody(route));
  });
  await page.route("**/api/tenant_config/deployment_version", (route) => json(route, { deployment_version: "speed", app_version: "test", status: "success", enable_agent_workbench: false }));
  await page.route("**/api/user/current_user_info", (route) => json(route, { data: { user: { user_id: "navigation-fixture", tenant_id: "navigation-tenant", user_email: "navigation@nexent.test", user_role: "SPEED", auth_provider: "local", group_ids: [], permissions: [], accessibleRoutes: ["/agents", "/newchat", "/agent-space"] } } }));
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
    await page.route("**/api/**", (route) => json(route, defaultApiBody(route)));
    await page.route("**/api/tenant_config/deployment_version", (route) => json(route, { deployment_version: "speed", app_version: "test", status: "success", enable_agent_workbench: true }));
    await page.route("**/api/user/current_user_info", (route) => json(route, { data: { user: { user_id: "navigation-fixture", tenant_id: "navigation-tenant", user_email: "navigation@nexent.test", user_role: "SPEED", auth_provider: "local", group_ids: [], permissions: [], accessibleRoutes: ["/", "/agents", "/newchat", "/workbench"] } } }));
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
    return json(route, defaultApiBody(route));
  });
  await page.route("**/locales/*/custom.json", async (route) => {
    const response = await route.fetch();
    return json(route, { ...await response.json(), aboutConfig: "open" });
  });
  await page.route("**/api/tenant_config/deployment_version", (route) => json(route, { deployment_version: "speed", app_version: "v2.6.0", status: "success", enable_agent_workbench: false }));
  await page.route("**/api/user/current_user_info", (route) => json(route, { data: { user: { user_id: "navigation-fixture", tenant_id: "navigation-tenant", user_email: "navigation@nexent.test", user_role: "SPEED", auth_provider: "local", group_ids: [], permissions: [], accessibleRoutes: ["/agents", "/newchat", "/agent-space"] } } }));
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
  await expect(menu.getByText(new RegExp(`©.*${new Date().getFullYear()}`))).toHaveCount(0);
  await expect(menu.getByText("外观设置", { exact: true })).toHaveCount(0);
  const profile = menu.getByRole('link', { name: text['profile.title'], exact: true });
  await profile.hover();
  await expectReferenceColor(profile.locator('xpath=ancestor::li[1]'), 'background-color', 'lab(94.1288% -2.23359 -10.9012)');
  const aboutRow = menu.locator('.account-menu-version');
  await aboutRow.hover();
  await expectReferenceColor(aboutRow, 'background-color', 'transparent');
  const logout = menu.getByRole('menuitem', { name: text['auth.logout'], exact: true });
  await expect(logout).toHaveClass(/ant-dropdown-menu-item-danger/);
  await expect(logout).toHaveCSS('color', 'lab(48.4493 77.4328 61.5452)');
  await expect(logout.locator('svg')).toHaveCSS('color', 'lab(48.4493 77.4328 61.5452)');
  await logout.hover();
  await expectReferenceColor(logout, 'background-color', 'color-mix(in oklab, lab(48.4493% 77.4328 61.5452) 10%, transparent)');
  const readGeometry = () => menu.evaluate((element) => {
    const style = getComputedStyle(element);
    const identity = element.querySelector('.account-menu-identity');
    const row = element.querySelector('[data-menu-id$="profile"]');
    return { width: element.getBoundingClientRect().width, radius: style.borderRadius, padding: style.paddingTop, shadow: style.boxShadow, identityHeight: identity.getBoundingClientRect().height, rowHeight: row.getBoundingClientRect().height, rowWidth: row.getBoundingClientRect().width, font: getComputedStyle(row.querySelector('.ant-dropdown-menu-title-content')).fontSize };
  });
  await expect.poll(readGeometry).toMatchObject({ width: 256, radius: "8px", padding: "6px", identityHeight: 60, rowHeight: 28, rowWidth: 244, font: "14px" });
  const geometry = await readGeometry();
  expect(geometry.shadow).toContain("6px");
  const languageAlignment = await menu.locator('.ant-dropdown-menu-submenu-title').evaluate(el => {
    const arrow = el.querySelector('.lucide-chevron-right').getBoundingClientRect();
    const row = el.getBoundingClientRect();
    return Math.abs(row.right - 6 - arrow.right);
  });
  expect(languageAlignment).toBeLessThanOrEqual(1);
  const languageRow = menu.locator('.ant-dropdown-menu-submenu-title');
  const defaultFont = await menu.evaluate(el => ({ family: getComputedStyle(el).fontFamily, size: getComputedStyle(el).fontSize }));
  for (const item of [profile, languageRow, logout]) {
    await expect(item).toHaveCSS('font-family', defaultFont.family);
    await expect(item).toHaveCSS('font-size', defaultFont.size);
  }

  const centered = await languageRow.evaluate(el => {
    const bounds = el.getBoundingClientRect();
    const center = bounds.y + bounds.height / 2;
    return [el.querySelector('.lucide-globe'), ...el.querySelector('span').children, el.querySelector('.lucide-chevron-right')].map(item => {
      const box = item.getBoundingClientRect();
      return Math.abs(box.y + box.height / 2 - center);
    });
  });
  for (const offset of centered) expect(offset).toBeLessThanOrEqual(1);
  const profileTextLeft = await menu.getByRole('link', { name: text['profile.title'], exact: true }).evaluate(el => el.getBoundingClientRect().left);
  const languageTextLeft = await languageRow.locator('span > span').first().evaluate(el => el.getBoundingClientRect().left);
  expect(languageTextLeft).toBe(profileTextLeft);
  await expect(menu.getByText(text['accountMenu.about'], { exact: true })).toBeVisible();

  const badge = menu.locator(".ant-tag");
  await expect(badge).toHaveCSS("color", "lab(46.9268 13.7028 -69.7937)");
  await expectReferenceColor(badge, "background-color", 'color-mix(in oklab, lab(46.9268% 13.7028 -69.7937) 10%, transparent)');
  await expect(badge).toHaveCSS("height", "15px");
  await expect(menu.locator(".account-menu-identity .ant-avatar")).toHaveCSS("width", "36px");
  await menu.getByText(text["accountMenu.language"], { exact: true }).hover();
  await expectReferenceColor(languageRow, 'background-color', 'lab(94.1288% -2.23359 -10.9012)');
  const english = page.getByText("English", { exact: true });
  await expect(english).toBeVisible();
  await expect(page.getByLabel(text["accountMenu.selectedLanguage"])).toBeVisible();
  await expect.poll(() => english.locator("xpath=ancestor::li[1]").evaluate(el => el.getBoundingClientRect().width)).toBe(213);
  await english.hover();
  await expectReferenceColor(english.locator('xpath=ancestor::li[1]'), 'background-color', 'lab(94.1288% -2.23359 -10.9012)');
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
  const longBrand = "Nexent enterprise intelligent collaboration platform";
  const brandConfig = JSON.parse(fs.readFileSync(path.join(process.env.NEXENT_REPO, "frontend/public/locales/en/custom.json"), "utf8"));
  let monitoringRequests = 0;
  let profileRequests = 0;
  page.on('request', request => { if (new URL(request.url()).pathname.endsWith('/users')) profileRequests += 1; });
  const json = (route, body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.route("**/api/**", (route) => json(route, defaultApiBody(route)));
  await page.route("**/locales/en/common.json", (route) => json(route, { ...text, "sidebar.knowledgeBaseConfig": longLabel }));
  await page.route("**/locales/*/custom.json", (route) => json(route, { ...brandConfig, productName: longBrand }));
  await page.route("**/api/tenant_config/deployment_version", (route) => json(route, { deployment_version: "speed", app_version: "v2.6.0", status: "success" }));
  await page.route("**/api/user/current_user_info", (route) => json(route, { data: { user: { user_id: "hover-fixture", tenant_id: "hover-tenant", user_email: "hover@nexent.test", user_role: "SPEED", role: "SPEED", auth_provider: "local", group_ids: [], permissions: [], accessibleRoutes: ["/agents", "/models", "/knowledges", "/agent-space", "/skill-space", "/resource-manage"] } } }));
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
  const divider = rail.locator('[data-sidebar-divider]');
  const checkDivider = async () => {
    await expect(divider).toBeVisible();
    await expect(divider).toHaveCSS('background-color', 'rgba(25, 25, 25, 0.15)');
    const lineBounds = await divider.boundingBox();
    const bounds = await rail.boundingBox();
    expect(lineBounds.width).toBe(0.5);
    expect(lineBounds.height).toBe(bounds.height);
    expect(lineBounds.x + lineBounds.width).toBe(bounds.x + bounds.width);
  };
  await expectReferenceColor(rail, 'background-color', 'lab(97.0939% -0.108689 -0.749958)');
  await expect(rail).toHaveAttribute('data-sidebar-expanded', 'false');
  await expect(rail.getByRole('button', { name: text['sidebar.pin'], exact: true })).toHaveCount(0);
  const item = page.getByRole('navigation').getByRole('button', { name: longLabel, exact: true });
  await expect(item).toHaveText('');
  const contentX = await page.locator('.ant-layout-content').evaluate(el => el.getBoundingClientRect().left);
  await expect.poll(() => rail.evaluate(el => el.getBoundingClientRect().width)).toBe(64);
  await checkDivider();
  await expect(rail.locator('[aria-current="page"] svg')).toHaveCSS('color', 'rgb(38, 115, 229)');
  await rail.hover({ position: { x: 30, y: 100 } });
  await expect.poll(() => rail.evaluate(el => el.getBoundingClientRect().width)).toBe(240);
  await checkDivider();
  expect(await page.locator('.ant-layout-content').evaluate(el => el.getBoundingClientRect().left)).toBe(contentX);
  const brand = rail.getByRole('link', { name: text['sidebar.homePage'], exact: true }).locator('.ant-typography');
  await item.hover();
  await expectReferenceColor(item, 'background-color', 'color-mix(in oklab, lab(92.4476% -0.214785 -1.49835) 70%, transparent)');
  const selectedItem = rail.locator('[aria-current="page"]');
  await expectReferenceColor(selectedItem, 'background-color', 'lab(92.4476% -0.214785 -1.49835)');
  await selectedItem.hover();
  await expectReferenceColor(selectedItem, 'background-color', 'lab(92.4476% -0.214785 -1.49835)');
  await expect(brand).toHaveText(longBrand);
  await expect(brand).toHaveCSS('font-size', '18px');
  await expect(brand.locator('xpath=ancestor::a[1]/..')).toHaveCSS('margin-bottom', '8px');
  await expect(brand).toHaveCSS('font-weight', '700');
  await expect(brand).toHaveCSS('margin-left', '0px');
  const logoGap = await brand.evaluate(el => el.getBoundingClientRect().left - el.parentElement.querySelector('img').getBoundingClientRect().right);
  expect(logoGap).toBe(4);
  await expect(rail.locator("img")).toHaveCSS("width", "40px");
  await expect(rail.locator("img")).toHaveCSS("height", "40px");
  await expect(brand).toHaveCSS('white-space', 'nowrap');
  await expect(brand).toHaveCSS('overflow', 'hidden');
  await expect(brand).toHaveCSS('text-overflow', 'ellipsis');
  expect(await brand.evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true);
  const brandBounds = await brand.boundingBox();
  const railBounds = await rail.boundingBox();
  expect(brandBounds.x + brandBounds.width).toBeLessThanOrEqual(railBounds.x + railBounds.width - 8);
  await brand.hover();
  await expect(page.getByRole('tooltip').filter({ hasText: longBrand })).toBeVisible();
  await expect(item).toHaveText(longLabel);
  await expect(item).toHaveCSS('cursor', 'pointer');
  await expect(item.locator('svg')).toHaveCSS('cursor', 'pointer');
  await expect(item.locator('svg')).toHaveCSS('width', '20px');
  await expect(item.locator('.ant-typography')).toHaveCSS('font-size', '14px');
  await expect(item.locator('.ant-typography')).toHaveCSS('cursor', 'pointer');
  const labelGap = await item.evaluate(el => el.querySelector('.ant-typography').getBoundingClientRect().left - el.querySelector('svg').getBoundingClientRect().right);
  expect(labelGap).toBe(8);
  for (const navItem of await page.getByRole('navigation').getByRole('button').all()) {
    const gap = await navItem.evaluate(el => el.querySelector('.ant-typography').getBoundingClientRect().left - el.querySelector('svg').getBoundingClientRect().right);
    expect(gap).toBe(8);
  }
  await expect(rail.locator('[aria-current="page"] svg')).toHaveCSS('color', 'rgb(38, 115, 229)');
  await expect(rail.getByRole('button', { name: text['sidebar.skillSpace'], exact: true }).locator('svg')).toHaveClass(/lucide-sparkles/);
  await expect(rail.getByRole('button', { name: text['sidebar.resourceManage'], exact: true }).locator('svg')).toHaveClass(/lucide-folder-cog/);
  const account = page.getByRole('button', { name: text['accountMenu.open'], exact: true });
  await expect(account).toHaveCSS('cursor', 'pointer');
  await expect(account.locator('.ant-typography')).toHaveCSS('margin-left', '-6px');
  const accountGap = await account.evaluate(el => el.querySelector('.ant-typography').getBoundingClientRect().left - el.querySelector('.ant-avatar').getBoundingClientRect().right);
  expect(accountGap).toBe(8);
  const positions = await item.evaluate(el => { const icon=el.querySelector('svg').getBoundingClientRect(); const label=el.querySelector('.ant-typography').getBoundingClientRect(); return { iconY:icon.y+icon.height/2, labelY:label.y+label.height/2 }; });
  expect(Math.abs(positions.iconY-positions.labelY)).toBeLessThanOrEqual(1);
  await item.locator('.ant-typography').hover();
  await expect(page.getByRole('tooltip').filter({ hasText: longLabel })).toBeVisible();
  await page.mouse.move(650, 200);
  await expect.poll(() => rail.evaluate(el => el.getBoundingClientRect().width)).toBe(64);
  await checkDivider();
  await rail.hover({ position: { x: 30, y: 100 } });
  const content = page.locator('.ant-layout-content');
  const originalWidth = await content.evaluate(el => el.getBoundingClientRect().width);
  const pin = rail.getByRole('button', { name: text['sidebar.pin'], exact: true });
  await expect(pin).toBeVisible();
  await expect(pin.locator('svg')).toHaveClass(/lucide-pin/);
  const headerAlignment = await pin.evaluate(el => { const button=el.getBoundingClientRect(); const logo=el.parentElement.parentElement.querySelector('img').getBoundingClientRect(); return Math.abs(button.y+button.height/2-logo.y-logo.height/2); });
  expect(headerAlignment).toBeLessThanOrEqual(1);
  await pin.click();
  await expect(rail).toHaveAttribute('data-sidebar-pinned', 'true');
  const pinnedToggle = rail.getByRole('button', { name: text['sidebar.unpin'], exact: true });
  await expect(pinnedToggle.locator('svg')).toHaveClass(/lucide-pin-off/);
  await expect(pinnedToggle).toHaveCSS('color', 'rgb(38, 115, 229)');
  await expect(pinnedToggle).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await expect(rail.locator('[aria-current="page"] svg')).toHaveCSS('color', 'rgb(38, 115, 229)');
  await checkDivider();
  await expect(rail).toHaveCSS('box-shadow', 'none');
  await expect.poll(() => content.evaluate(el => el.getBoundingClientRect().left)).toBe(240);
  expect(await content.evaluate(el => el.getBoundingClientRect().width)).toBe(originalWidth-176);
  await page.mouse.move(650, 200);
  await page.waitForTimeout(250);
  await expect(rail).toHaveAttribute('data-sidebar-expanded', 'true');
  await rail.getByRole('button', { name: text['sidebar.unpin'], exact: true }).click();
  await expect.poll(() => rail.evaluate(el => el.getBoundingClientRect().width)).toBe(64);
  await expect.poll(() => content.evaluate(el => el.getBoundingClientRect().left)).toBe(contentX);
  await page.waitForTimeout(250);
  await expect(rail).toHaveAttribute('data-sidebar-expanded', 'false');
  await expect(pin).toHaveCount(0);
  await page.mouse.move(650, 200);
  await rail.hover({ position: { x: 30, y: 100 } });
  await expect.poll(() => rail.evaluate(el => el.getBoundingClientRect().width)).toBe(240);
  expect(await content.evaluate(el => el.getBoundingClientRect().left)).toBe(contentX);
  await expect.poll(() => monitoringRequests).toBeGreaterThan(0);
  const requestBaseline = monitoringRequests;
  await page.getByRole('button', { name: text['accountMenu.open'], exact: true }).click();
  await page.mouse.move(650, 200);
  await expect(page.getByRole('menu').first()).toBeVisible();
  await expectReferenceColor(account, 'background-color', 'lab(92.4476% -0.214785 -1.49835)');
  await expect(page.getByRole('link', { name: text['profile.title'], exact: true })).toHaveAttribute('href', '/en/users');
  const supplemental = page.getByRole('menu').first().locator('.account-menu-secondary');
  expect(await supplemental.count()).toBeGreaterThanOrEqual(4);
  for (const entry of await supplemental.all()) {
    const isAbout = await entry.evaluate(el => el.classList.contains('account-menu-version'));
    await expectReferenceColor(entry, 'color', isAbout ? 'color-mix(in oklab, lab(47.7049% -1.02875 -9.20491) 60%, transparent)' : 'lab(47.7049% -1.02875 -9.20491)');
    await expect(entry).toHaveCSS('height', isAbout ? '22.5px' : '24px');
    await expect(entry.locator('.ant-dropdown-menu-title-content')).toHaveCSS('font-size', '11px');
    await expect(entry.locator('.ant-dropdown-menu-title-content')).toHaveCSS('line-height', '16.5px');
    for (const arrow of await entry.locator('.lucide-arrow-up-right').all()) await expect(arrow).toHaveCSS('width', '12px');
  }
  await expect(page.getByRole('menu').first().locator('.account-menu-version .font-mono')).toHaveCSS('font-family', 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace');

  await expect(page.getByRole('link', { name: text['profile.title'], exact: true }).locator('xpath=..')).toHaveCSS('font-size', '14px');
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
