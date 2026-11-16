// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, type Page } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

type ControlledWindow = Window & {
  statusRequests: Array<Record<string, unknown>>;
  finishStatusRun: () => void;
};

const HISTORY_TITLE =
  "Long history title for consistent truncation and tooltip across Workbench and Agent chat";

async function prepare(page: Page, agentChat: boolean) {
  const id = agentChat ? 1304 : 1303;
  const histories: Array<Record<string, any>> = [];
  await page.exposeFunction("persistStatusHistory", () => {
    if (histories.length === 0)
      histories.push({
        conversation_id: id,
        conversation_title: HISTORY_TITLE,
        agent_id: 7,
        create_time: Date.now(),
        update_time: Date.now(),
        last_activity_time: Date.now(),
      });
  });
  await page.context().addCookies([
    {
      name: "nexent_token_expires_at",
      value: String(Math.floor(Date.now() / 1000) + 3600),
      url: process.env.NEXENT_BASE_URL ?? "http://localhost:3331",
    },
  ]);
  await page.addInitScript(
    ({ id }) => {
      const target = window as ControlledWindow;
      const original = window.fetch.bind(window);
      target.statusRequests = [];
      window.fetch = async (input, init) => {
        const url = new URL(
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.href
              : input.url,
          location.href,
        );
        if (url.pathname !== "/api/agent/run") return original(input, init);
        target.statusRequests.push(JSON.parse(String(init?.body)));
        await (
          window as Window & { persistStatusHistory: () => Promise<void> }
        ).persistStatusHistory();
        const encoder = new TextEncoder();
        const stream = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                'data: {"type":"model_output_thinking","content":"Working"}\n\n',
              ),
            );
            target.finishStatusRun = () => {
              controller.enqueue(
                encoder.encode(
                  'data: {"type":"final_answer","content":"Controlled status answer"}\n\n',
                ),
              );
              controller.close();
            };
          },
        });
        return new Response(stream, {
          headers: {
            "Content-Type": "text/event-stream",
            conversation_id: String(id),
            "X-Workbench-Config-Version": "1",
            "X-User-Message-Id": String(id * 10),
            "X-User-Message-Index": "0",
          },
        });
      };
    },
    { id },
  );
  await prepareWorkbench(page, 1, { histories });
  await page.route("**/api/conversation/generate_title", (route) =>
    route.fulfill({ json: { code: 0, data: HISTORY_TITLE } }),
  );
  if (agentChat) {
    await page.route(/\/api\/conversation\/agent_groups(?:\?|$)/, (route) =>
      route.fulfill({
        json: {
          code: 0,
          data: {
            items: [],
            pinned_items: [],
            included_items: [],
            next_cursor: null,
          },
        },
      }),
    );
    await page.route(
      /\/api\/conversation\/agent_groups\/agent(?::|%3[Aa])7\/conversations/,
      (route) =>
        route.fulfill({
          json: {
            code: 0,
            data: { items: histories, pinned_items: [], next_cursor: null },
          },
        }),
    );
    await page.goto(
      `${process.env.NEXENT_BASE_URL ?? "http://localhost:3331"}/zh/newchat?agent_id=7`,
    );
  }
  return { id, row: page.locator(`[data-conversation-id="${id}"]`) };
}

journey("CHAT-RUN-STATUS-D4-001", async ({ page, contract }) => {
  const agentPage = await page.context().newPage();
  contract.deferCleanup(async () => agentPage.close());
  const pages = [page, agentPage];
  const rows = pages.map((entry, index) =>
    entry.locator(`[data-conversation-id="${1303 + index}"]`),
  );
  const requests = (entry: Page) =>
    entry.evaluate(() => (window as ControlledWindow).statusRequests);
  const finish = (entry: Page) =>
    entry.evaluate(() => (window as ControlledWindow).finishStatusRun());
  const exercised = new Set<string>();
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      for (const [index, entry] of pages.entries()) {
        await entry.setViewportSize({ width: 1500, height: 1000 });
        await prepare(entry, index === 1);
        await expect(
          entry.getByRole("textbox", { name: "对话输入", exact: true }),
        ).toBeVisible();
      }
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    for (const [index, entry] of pages.entries()) {
      const row = rows[index];
      const input = entry.getByRole("textbox", {
        name: "对话输入",
        exact: true,
      });
      await input.fill("Controlled status question");
      await input.press("Enter");
      await expect(row.locator('[role="status"].animate-spin')).toBeVisible();
      expect(await requests(entry)).toHaveLength(1);
      expect((await requests(entry))[0].conversation_id).toBeUndefined();
      await finish(entry);
      await expect(row.locator('span[role="status"]')).toBeVisible();
      await entry.screenshot({
        path: `${contract.caseDir}/${index ? "agent" : "workbench"}-completed.png`,
      });
      exercised.add(index ? "agent-new" : "workbench-new");
    }
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    for (const [index, entry] of pages.entries()) {
      const row = rows[index];
      const status = row.locator('span[role="status"]');
      const menu = row.getByRole("button").last();
      await row.hover();
      await expect(status).toBeHidden();
      await expect(menu).toHaveCSS("opacity", "1");
      await entry.screenshot({
        path: `${contract.caseDir}/${index ? "agent" : "workbench"}-hover.png`,
      });
      await menu.focus();
      await expect(status).toBeHidden();
      await entry.mouse.move(1400, 20);
      await menu.evaluate((element) => element.blur());
      await expect(status).toBeVisible();
      await entry
        .getByRole("textbox", { name: "对话输入", exact: true })
        .click();
      await expect(status).toHaveCount(0);
      expect(await requests(entry)).toHaveLength(1);
      exercised.add(index ? "agent-read" : "workbench-read");
    }
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    for (const [index, entry] of pages.entries()) {
      const row = rows[index];
      await entry
        .locator('[data-slot="aui_assistant-message-root"]')
        .last()
        .hover();
      await entry
        .getByRole("button", { name: "刷新", exact: true })
        .last()
        .click();
      await expect(row.locator('[role="status"].animate-spin')).toBeVisible();
      expect(await requests(entry)).toHaveLength(2);
      await finish(entry);
      await expect(row.locator('span[role="status"]')).toBeVisible();
      await row.getByRole("button").first().click();
      await expect(row.locator('span[role="status"]')).toHaveCount(0);
      expect(await requests(entry)).toHaveLength(2);
      exercised.add(index ? "agent-retry" : "workbench-retry");
    }
  });
  await contract.step(contract.expectedIds("steps")[3], async () => {
    for (const [index, entry] of pages.entries()) {
      const row = rows[index];
      const title = row.locator("[data-history-title]");
      const time = row.locator("[data-history-time]");
      const menu = row.getByRole("button").last();
      await entry.mouse.move(1400, 20);
      await entry.evaluate(() => {
        if (document.activeElement instanceof HTMLElement)
          document.activeElement.blur();
      });
      await expect(title).toHaveText(HISTORY_TITLE);
      await expect(time).toBeVisible();
      expect(
        await title.evaluate(
          (element) => element.scrollWidth > element.clientWidth,
        ),
      ).toBe(true);
      const width = (await title.boundingBox())!.width;
      const timeBounds = (await time.boundingBox())!;
      const menuBounds = (await menu.boundingBox())!;
      await expect(menu).toHaveCSS("position", "absolute");
      expect(timeBounds.x + timeBounds.width).toBeCloseTo(
        menuBounds.x + menuBounds.width,
        0,
      );
      expect(timeBounds.y + timeBounds.height / 2).toBeCloseTo(
        menuBounds.y + menuBounds.height / 2,
        0,
      );
      await title.hover();
      await expect(entry.getByRole("tooltip")).toHaveText(HISTORY_TITLE);
      await expect(time).toBeHidden();
      await expect(menu).toHaveCSS("opacity", "1");
      expect((await title.boundingBox())!.width).toBe(width);
      await entry.screenshot({
        path: `${contract.caseDir}/${index ? "agent" : "workbench"}-title-tooltip.png`,
      });
      await menu.focus();
      await entry.mouse.move(1400, 20);
      await expect(time).toBeHidden();
      expect((await title.boundingBox())!.width).toBe(width);
      await menu.evaluate((element) => element.blur());
      await expect(time).toBeVisible();
      await expect(menu).toHaveCSS("opacity", "0");
      expect((await title.boundingBox())!.width).toBe(width);
    }
  });
  await contract.assertion(contract.expectedIds("assertions")[0], async () => {
    expect([...exercised].sort()).toEqual([
      "agent-new",
      "agent-read",
      "agent-retry",
      "workbench-new",
      "workbench-read",
      "workbench-retry",
    ]);
  });
  await contract.assertion(contract.expectedIds("assertions")[1], async () => {
    for (const entry of pages) {
      expect(await requests(entry)).toHaveLength(2);
      await expect(
        entry.locator('[data-conversation-id] span[role="status"]'),
      ).toHaveCount(0);
    }
  });
  await contract.assertion(contract.expectedIds("assertions")[2], async () => {
    for (const [index, entry] of pages.entries()) {
      expect(await requests(entry)).toHaveLength(2);
      await expect(rows[index].locator("[data-history-time]")).toBeVisible();
    }
  });
});
