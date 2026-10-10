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

journey("PW-UI-02", async (context) => {
  const { page, expect } = context;
  let trigger!: import("playwright/test").Locator;
  let dialogFocused = false;
  let focusReturned = false;
  let sent = false;
  let agentTriggerNamed = false;
  let modelTriggerNamed = false;
  await executeFixedScenario(context, {
    preconditions: [
      async () => { await loginCurrent(page, "tenant_a_admin"); return "stable tenant administrator login is ready"; },
      async () => "all navigation and activation in this case uses Playwright keyboard APIs",
    ],
    steps: [
      async () => {
        await page.goto(appPath("/agents"), { waitUntil: "domcontentloaded" });
        for (let i = 0; i < 8; i += 1) await page.keyboard.press("Tab");
        const tag = await page.locator(":focus").evaluate((node) => node.tagName);
        expect(["A", "BUTTON", "INPUT"]).toContain(tag);
        return "sequential Tab navigation reached an interactive navigation/content control";
      },
      async () => {
        trigger = page.getByRole("button", { name: "新建" });
        agentTriggerNamed = Boolean(((await trigger.getAttribute("aria-label")) || (await trigger.innerText())).trim());
        await trigger.focus();
        await page.keyboard.press("Enter");
        await expect(page.getByRole("dialog", { name: "创建智能体" })).toBeVisible();
        return "opened the safe Create Agent dialog from Agents using keyboard activation only";
      },
      async () => {
        const dialog = page.getByRole("dialog", { name: "创建智能体" });
        for (let i = 0; i < 6; i += 1) {
          await page.keyboard.press("Tab");
          const focusIsInside = await page.locator(":focus").evaluate((node) => Boolean(node.closest("[role='dialog']")));
          expect(focusIsInside).toBeTruthy();
        }
        dialogFocused = true;
        return "dialog focus cycled among its form/buttons without escaping to the background";
      },
      async () => {
        await page.keyboard.press("Escape");
        await expect(page.getByRole("dialog", { name: "创建智能体" })).toBeHidden();
        focusReturned = await trigger.evaluate((node) => node === document.activeElement);
        expect(focusReturned).toBeTruthy();
        return "Escape closed the dialog and restored focus to the New Agent trigger";
      },
      async () => {
        await page.goto(appPath("/models"), { waitUntil: "domcontentloaded" });
        const add = page.getByRole("button", { name: "添加模型", exact: true });
        modelTriggerNamed = Boolean(((await add.getAttribute("aria-label")) || (await add.innerText())).trim());
        await add.focus();
        await page.keyboard.press("Enter");
        await expect(page.getByRole("dialog", { name: "添加模型" })).toBeVisible();
        await page.keyboard.press("Escape");
        return "repeated keyboard dialog open/close on the real Models form";
      },
      async () => {
        const agent = resolveReadyAsset("agents", "d4_chat_display_name", "PW-UI-02");
        const chat = new ChatPage(page);
        await chat.openAgent(agent);
        const composer = page.getByPlaceholder("发送消息...");
        await expect(composer).toBeVisible();
        await composer.focus();
        await page.keyboard.type("只回复 OK");
        const send = page.getByRole("button", { name: "发送" });
        await expect(send).toBeEnabled();
        // The model selector and attachment controls are valid tab stops between
        // the composer and Send. Follow the real tab order instead of assuming
        // that Send is the immediately adjacent control.
        let sendFocused = false;
        for (let i = 0; i < 8; i += 1) {
          await page.keyboard.press("Tab");
          sendFocused = await send.evaluate((node) => node === document.activeElement);
          if (sendFocused) break;
        }
        expect(sendFocused).toBeTruthy();
        await page.keyboard.press("Enter");
        sent = true;
        return "focused Composer, entered text, tabbed to Send and triggered it by keyboard";
      },
      async () => {
        expect(agentTriggerNamed && modelTriggerNamed).toBeTruthy();
        return "representative critical controls expose readable accessible names";
      },
    ],
    assertions: [
      async () => "primary navigation, Agent dialog and Models dialog were keyboard reachable",
      async () => { expect(dialogFocused && focusReturned).toBeTruthy(); return "dialog focus stayed trapped and returned to its trigger after Escape"; },
      async () => { expect(sent).toBeTruthy(); return "chat Send was keyboard-triggered on a published runnable Agent"; },
    ],
  });
});
