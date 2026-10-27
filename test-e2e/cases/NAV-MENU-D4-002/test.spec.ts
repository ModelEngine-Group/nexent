// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import fs from "node:fs";
import path from "node:path";
import { expect, type Page, type Route } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";

const baseUrl = process.env.NEXENT_BASE_URL ?? "http://localhost:3000";
const repository = process.env.NEXENT_REPO ?? process.cwd();

journey("NAV-MENU-D4-002", async ({ page, contract }) => {
  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    expect((await page.request.get(baseUrl)).ok()).toBe(true);
  });

  const writes: string[] = [];
  const releases: Array<() => void> = [];
  const pages: Page[] = [];
  contract.deferCleanup(async () => {
    releases.forEach((release) => release());
    await Promise.all(pages.map((tab) => tab.close()));
  });

  await contract.step(contract.expectedIds("steps")[0], async () => {
    await contract.assertion(contract.expectedIds("assertions")[0], async () => {
      for (const locale of ["zh", "en"]) {
        const context = await page.context().browser()!.newContext();
        contract.deferCleanup(() => context.close());
        const tab = await context.newPage();
        pages.push(tab);
        const labels = JSON.parse(fs.readFileSync(path.join(repository, `frontend/public/locales/${locale}/common.json`), "utf8"));
        const json = (route: Route, body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
        await tab.route("**/api/**", (route) => {
          const pathname = new URL(route.request().url()).pathname;
          const isReadOnlyPost = ["/api/groups/list", "/api/tenants/tenant-list"].includes(pathname) && route.request().method() === "POST";
          if (route.request().method() !== "GET" && !isReadOnlyPost) writes.push(pathname);
          return json(route, {});
        });
        await tab.route("**/api/tenant_config/deployment_version", (route) => json(route, { deployment_version: "speed", status: "success" }));
        await tab.route("**/api/user/current_user_info", (route) => json(route, { data: { user: { user_id: "loading-fixture", tenant_id: "loading-tenant", user_role: "SPEED", user_email: "loading@nexent.test", permissions: [], accessibleRoutes: ["/agents", "/models", "/resource-manage"], groupIds: [] } } }));
        await tab.route("**/api/groups/list", (route) => json(route, { data: [], total: 0 }));
        await tab.route("**/api/tag-libraries", (route) => json(route, []));
        await tab.route("**/api/agent/list/page?*", (route) => json(route, { items: [], pagination: { page: 1, page_size: 10, total: 0, total_pages: 0 } }));
        await tab.goto(`${baseUrl}/${locale}/agents`);
        const nav = tab.getByRole("navigation");
        await expect(nav.getByRole("button", { name: labels["sidebar.modelConfig"], exact: true })).toBeVisible();
        let release!: () => void;
        const held = new Promise<void>((resolve) => { release = resolve; });
        releases.push(release);
        await tab.route((url) => url.pathname === `/${locale}/models` || url.pathname === `/${locale}/resource-manage`, async (route) => {
          await held;
          await route.continue();
        });
        await nav.getByRole("button", { name: labels["sidebar.modelConfig"], exact: true }).press("Enter");
        const skeleton = tab.locator(".route-loading-skeleton:visible");
        await expect(skeleton).toBeVisible();
        await expect(skeleton.getByRole("heading")).toHaveText(labels["sidebar.modelConfig"]);
        await expect(skeleton.locator("h1 .route-skeleton-title")).toBeVisible();
        await expect(skeleton.locator("h1 .sr-only")).toHaveCSS("position", "absolute");
        await expect(skeleton).toHaveText(labels["sidebar.modelConfig"]);
        expect(await skeleton.locator(".route-skeleton-bone").count()).toBeGreaterThan(5);
        await expect(skeleton.locator("button, input, select")).toHaveCount(0);
        const shimmer = await skeleton.locator(".route-skeleton-bone").first().evaluate((element) => ({ name: getComputedStyle(element, "::after").animationName, state: getComputedStyle(element, "::after").animationPlayState }));
        expect(shimmer).toEqual({ name: "route-skeleton-shimmer", state: "running" });
        await expect(nav.getByRole("button", { name: labels["sidebar.resourceManage"], exact: true })).toBeEnabled();
        await tab.setViewportSize({ width: 320, height: 720 });
        expect(await skeleton.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
        await tab.emulateMedia({ reducedMotion: "reduce" });
        expect(await skeleton.locator(".route-skeleton-bone").first().evaluate((element) => getComputedStyle(element, "::after").animationName)).toBe("none");
        await tab.emulateMedia({ reducedMotion: "no-preference" });
        await tab.setViewportSize({ width: 1280, height: 720 });
      }
      expect(writes).toEqual([]);
    });
  });

  await contract.step(contract.expectedIds("steps")[1], async () => {
    await contract.assertion(contract.expectedIds("assertions")[1], async () => {
      for (const [index, tab] of pages.entries()) {
        const locale = index === 0 ? "zh" : "en";
        const labels = JSON.parse(fs.readFileSync(path.join(repository, `frontend/public/locales/${locale}/common.json`), "utf8"));
        await tab.getByRole("navigation").getByRole("button", { name: labels["sidebar.resourceManage"], exact: true }).press("Enter");
        await expect(tab.locator(".route-loading-skeleton:visible").getByRole("heading")).toHaveText(labels["sidebar.resourceManage"]);
        releases[index]();
        await expect(tab).toHaveURL(new RegExp(`/${locale}/resource-manage$`));
        await expect(tab.locator(".route-loading-skeleton")).toHaveCount(0);
        await expect(tab.getByRole("main").getByRole("heading").first()).toBeVisible();
      }
      expect(writes).toEqual([]);
    });
  });

  await contract.step(contract.expectedIds("steps")[2], async () => {
    await contract.assertion(contract.expectedIds("assertions")[2], async () => {
      for (const [index, tab] of pages.entries()) {
        const locale = index === 0 ? "zh" : "en";
        const labels = JSON.parse(fs.readFileSync(path.join(repository, `frontend/public/locales/${locale}/common.json`), "utf8"));
        let release!: () => void;
        const held = new Promise<void>((resolve) => { release = resolve; });
        releases.push(release);
        await tab.route((url) => url.pathname === `/${locale}/users`, async (route) => { await held; await route.continue(); });
        await tab.getByRole("button", { name: labels["accountMenu.open"], exact: true }).click();
        await tab.getByRole("link", { name: labels["profile.title"], exact: true }).click();
        const skeleton = tab.locator(".route-loading-skeleton:visible");
        await expect(skeleton).toHaveAttribute("data-layout", "table");
        await expect(skeleton.locator(".route-skeleton-title")).toBeVisible();
        await expect(skeleton.getByRole("heading")).toHaveCount(0);
        await expect(skeleton).toHaveText("");
        release();
        await expect(tab).toHaveURL(new RegExp(`/${locale}/users$`));
        await expect(tab.locator(".route-loading-skeleton")).toHaveCount(0);
      }
      expect(writes).toEqual([]);
    });
  });
});
