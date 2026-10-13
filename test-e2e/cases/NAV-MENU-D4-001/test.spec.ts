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
  await page.route("**/api/user/current_user_info", (route) => json(route, { data: { user: { user_id: "navigation-fixture", tenant_id: "navigation-tenant", user_email: "navigation@nexent.test", user_role: "SPEED", auth_provider: "local", groupIds: [], permissions: [], accessibleRoutes: ["/agents", "/chat", "/agent-space"] } } }));
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
    await page.route("**/api/user/current_user_info", (route) => json(route, { data: { user: { user_id: "navigation-fixture", tenant_id: "navigation-tenant", user_email: "navigation@nexent.test", user_role: "SPEED", auth_provider: "local", groupIds: [], permissions: [], accessibleRoutes: ["/", "/agents", "/chat"] } } }));
    await page.route("**/api/groups/list", (route) => json(route, { data: [], total: 0 }));
    await page.route("**/api/agent/list/page?*", (route) => json(route, { items: [], pagination: { page: 1, page_size: 10, total: 0, total_pages: 0 } }));
    await page.goto(`${baseUrl}/${locale}/agents`);
    const nav = page.getByRole("navigation");
    const workbenchLabel = locale === "zh" ? "工作台" : "Workbench";
    await expect(nav.getByRole("button").nth(0)).toHaveText(text["sidebar.homePage"]);
    await expect(nav.getByRole("button").nth(1)).toHaveText(workbenchLabel);
    await expect(nav.getByRole("button").nth(2)).toHaveText(text["sidebar.startChat"]);
    await nav.getByRole("button", { name: workbenchLabel, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/${locale}/workbench$`));
    await expect(nav.getByRole("button", { name: workbenchLabel, exact: true })).toHaveAttribute("aria-current", "page");
  });
}

journey("NAV-MENU-D4-001", async ({ page, contract }) => {
  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    const response = await page.request.get(baseUrl);
    expect(response.ok()).toBe(true);
  });
  expect(scenarios).toHaveLength(3);
  for (const [index, scenario] of scenarios.entries()) {
    await page.unrouteAll({ behavior: "wait" });
    await page.context().clearCookies();
    if (page.url().startsWith(baseUrl)) await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
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
