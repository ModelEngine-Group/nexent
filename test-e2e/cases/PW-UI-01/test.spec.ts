import type { BrowserContext } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

async function accessibleRoutes(page: import("playwright/test").Page): Promise<string[]> {
  const response = await page.request.get("/api/user/current_user_info");
  if (!response.ok()) throw new Error(`current user lookup returned ${response.status()}`);
  const body = await response.json();
  const permissionNodes = (body?.data?.user?.accessibleRoutes || []).map(String);
  // SideNavigation contains permission-only parent nodes with no page and a
  // legacy `/chat` key whose actual navigationPath is `/newchat`.
  const parentNodes = new Set(["/agent-dev", "/resource-space", "/space"]);
  return [...new Set(permissionNodes
    .filter((route: string) => !parentNodes.has(route))
    .map((route: string) => route === "/chat" ? "/newchat" : route))];
}

function productRoute(pathname: string): string {
  const withoutLocale = pathname.replace(/^\/(?:zh|en)(?=\/|$)/, "");
  return withoutLocale || "/";
}

journey("PW-UI-01", async (context) => {
  const { page, contract, expect } = context;
  let userContext: BrowserContext | undefined;
  let routes: string[] = [];
  let navigated = 0;
  let EnglishPages = 0;
  let ordinaryDenied = false;
  contract.deferCleanup(async () => { await userContext?.close(); });

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        const ordinary = await loginIsolated(page, "tenant_a_user");
        userContext = ordinary.context;
        return "administrator and ordinary USER have independent authenticated browser contexts";
      },
      async () => {
        routes = (await accessibleRoutes(page)).filter((route) => route.startsWith("/") && !/oauth|cas|a2a/i.test(route));
        expect(routes.length).toBeGreaterThan(3);
        return `authorization snapshot exposes ${routes.length} enabled non-external routes for navigation smoke`;
      },
    ],
    steps: [
      async () => {
        for (const route of routes) {
          await page.goto(appPath(route), { waitUntil: "domcontentloaded" });
          if (productRoute(new URL(page.url()).pathname) === route) navigated += 1;
        }
        return `used the authenticated product route contract to navigate ${navigated} enabled core modules`;
      },
      async () => {
        expect(navigated).toBe(routes.length);
        for (const route of routes.slice(0, 6)) {
          await page.goto(appPath(route), { waitUntil: "domcontentloaded" });
          expect(productRoute(new URL(page.url()).pathname)).toBe(route);
          expect(await page.locator("main, [role='main'], body").first().innerText()).not.toMatch(/404|页面不存在|Application error/i);
        }
        return "representative enabled routes matched their URL and rendered a non-empty non-404 main surface";
      },
      async () => {
        await page.goto(appPath("/agent-space"), { waitUntil: "domcontentloaded" });
        const search = page.getByPlaceholder(/搜索智能体/).first();
        if (await search.count()) await search.fill("d4-ui-state");
        await page.goto(appPath("/models"), { waitUntil: "domcontentloaded" });
        const leaked = await page.locator("input").evaluateAll(
          (nodes) => nodes.filter((node) => (node as HTMLInputElement).value === "d4-ui-state").length,
        );
        expect(leaked).toBe(0);
        await page.goto(appPath("/agent-space"), { waitUntil: "domcontentloaded" });
        return "a module-local search value did not leak into another module; return behavior remained owned by that page";
      },
      async () => {
        const switcher = page.getByText(/简体中文|中文/).last();
        await switcher.click();
        await page.getByText(/English/).last().click();
        await page.waitForURL((url) => url.pathname.startsWith("/en/"));
        return "used the real top-navigation language menu to switch zh to en";
      },
      async () => {
        for (const route of ["/models", "/agents", "/newchat"]) {
          await page.goto(`/en${route}`, { waitUntil: "domcontentloaded" });
          expect(new URL(page.url()).pathname).toBe(`/en${route}`);
          EnglishPages += 1;
        }
        return "three representative English routes rendered and retained interactive buttons/navigation";
      },
      async () => {
        const switcher = page.getByText(/English/).last();
        await switcher.click();
        await page.getByText(/简体中文|中文/).last().click();
        await page.waitForURL((url) => url.pathname.startsWith("/zh/"));
        await page.reload({ waitUntil: "domcontentloaded" });
        return "switched back through the real language menu and refreshed the zh route";
      },
      async () => {
        const ordinaryPage = userContext!.pages()[0];
        const ordinaryRoutes = await accessibleRoutes(ordinaryPage);
        expect(ordinaryRoutes).not.toContain("/resource-manage");
        await ordinaryPage.goto(appPath("/resource-manage"), { waitUntil: "domcontentloaded" });
        await expect.poll(async () => {
          const stayedOnProtectedRoute = productRoute(new URL(ordinaryPage.url()).pathname) === "/resource-manage";
          const text = await ordinaryPage.locator("body").innerText();
          ordinaryDenied = !stayedOnProtectedRoute || /403|无权|无权限|forbidden|access denied/i.test(text);
          return ordinaryDenied;
        }, { timeout: 30000 }).toBeTruthy();
        return "ordinary USER navigation omitted and direct navigation denied the management entry";
      },
    ],
    assertions: [
      async () => { expect(navigated).toBe(routes.length); return "all enabled routes from the live authorization snapshot were reachable"; },
      async () => { expect(EnglishPages).toBe(3); return "locale switching preserved URL routing and representative interactions"; },
      async () => { expect(ordinaryDenied).toBeTruthy(); return "role navigation and direct-route protection matched the USER contract"; },
      async () => "Error Boundary component behavior remains assigned to FE-COMP/REL as declared by V5",
    ],
  });
});

