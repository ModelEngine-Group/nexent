// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("CHAT-ACTIVITY-D4-001", async ({ page, contract }) => {
  await page.setViewportSize({ width: 1200, height: 900 });
  const now = Date.now();
  const histories = Array.from({ length: 40 }, (_, index) => ({
    conversation_id: 100 + index,
    conversation_title: `Activity control ${index}`,
    create_time: now - (index + 1) * 86_400_000,
    update_time: now - (index + 1) * 86_400_000,
    last_activity_time: now - (index + 1) * 86_400_000,
  }));
  const automated = {
    conversation_id: 999,
    conversation_title: "Old automation history",
    create_time: now - 90 * 86_400_000,
    update_time: now - 90 * 86_400_000,
    last_activity_time: now - 90 * 86_400_000,
  };
  histories.push(automated);
  let state!: Awaited<ReturnType<typeof prepareWorkbench>>;
  let originalUrl = "";
  let origin = 0;
  let foregroundObserved = false;
  let listReads = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/conversation/list")
      listReads++;
  });
  const draft = page.getByRole("textbox", { name: "对话输入", exact: true });
  let draftNode: Awaited<ReturnType<typeof draft.elementHandle>> = null;
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      state = await prepareWorkbench(page, 1, { histories });
      await expect(draft).toBeVisible();
      draftNode = await draft.elementHandle();
      await expect(
        page.getByText("Activity control 0", { exact: true }),
      ).toBeVisible();
      await expect(
        page.getByText(automated.conversation_title, { exact: true }),
      ).toHaveCount(0);
      originalUrl = page.url();
      origin = await page.evaluate(() => performance.timeOrigin);
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await draft.fill(
      "Keep this draft while automation updates another history",
    );
    automated.last_activity_time = Date.now();
    histories.pop();
    histories.unshift(automated);
    // An idle page must not discover external changes until a foreground event.
    const idleReads = listReads;
    await page.waitForTimeout(60_000);
    expect(listReads).toBe(idleReads);
    await expect(
      page.getByText(automated.conversation_title, { exact: true }),
    ).toHaveCount(0);
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await expect(
      page.getByText(automated.conversation_title, { exact: true }),
    ).toBeVisible({ timeout: 15_000 });
    await expect
      .poll(async () => {
        const oldPosition = await page
          .getByText(automated.conversation_title, { exact: true })
          .boundingBox();
        const controlPosition = await page
          .getByText("Activity control 0", { exact: true })
          .boundingBox();
        return Boolean(
          oldPosition && controlPosition && oldPosition.y < controlPosition.y,
        );
      })
      .toBe(true);
    await expect(draft).toHaveValue(
      "Keep this draft while automation updates another history",
    );
    foregroundObserved = true;
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    const control = histories.find((item) => item.conversation_id === 100)!;
    control.last_activity_time = Date.now() + 1_000;
    histories.splice(histories.indexOf(control), 1);
    histories.unshift(control);
    const row = await page
      .getByText(automated.conversation_title, { exact: true })
      .elementHandle();
    const scroll = await row!.evaluateHandle((node) =>
      node.closest('[data-sidebar="content"]'),
    );
    await scroll.evaluate((node) => {
      if (node instanceof HTMLElement) node.scrollTop = 80;
    });
    const beforeScroll = await scroll.evaluate((node) =>
      node instanceof HTMLElement ? node.scrollTop : -1,
    );
    expect(beforeScroll).toBeGreaterThan(0);
    let release!: () => void;
    const hold = new Promise<void>((resolve) => {
      release = resolve;
    });
    let arrived!: () => void;
    const started = new Promise<void>((resolve) => {
      arrived = resolve;
    });
    const beforeReads = listReads;
    const routePattern = "**/api/conversation/list?**";
    await page.route(routePattern, async (route) => {
      arrived();
      await hold;
      await route.fallback();
    });
    try {
      await page.evaluate(() => {
        window.dispatchEvent(new Event("focus"));
        window.dispatchEvent(new Event("online"));
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await started;
      await expect(
        page.locator('[data-slot="aui_thread-list-skeleton"]'),
      ).toHaveCount(0);
      await expect(
        page.getByText(automated.conversation_title, { exact: true }),
      ).toBeVisible();
      expect(await row!.evaluate((node) => node.isConnected)).toBe(true);
      expect(
        await scroll.evaluate((node) =>
          node instanceof HTMLElement ? node.scrollTop : -1,
        ),
      ).toBe(beforeScroll);
      expect(listReads).toBe(beforeReads + 1);
      release();
      await expect
        .poll(async () => {
          const controlPosition = await page
            .getByText(control.conversation_title, { exact: true })
            .boundingBox();
          const oldPosition = await page
            .getByText(automated.conversation_title, { exact: true })
            .boundingBox();
          return Boolean(
            controlPosition && oldPosition && controlPosition.y < oldPosition.y,
          );
        })
        .toBe(true);
      await expect(
        page.getByText(automated.conversation_title, { exact: true }),
      ).toHaveCount(1);
      expect(await row!.evaluate((node) => node.isConnected)).toBe(true);
      expect(
        await scroll.evaluate((node) =>
          node instanceof HTMLElement ? node.scrollTop : -1,
        ),
        "completed metadata reorder retains scroll offset",
      ).toBe(beforeScroll);
      await expect(draft).toHaveValue(
        "Keep this draft while automation updates another history",
      );
    } finally {
      release();
      await page.unroute(routePattern);
    }
  });
  for (const id of contract.expectedIds("assertions").slice(0, 2)) {
    await contract.assertion(id, async () => {
      expect(foregroundObserved).toBe(true);
      expect(page.url()).toBe(originalUrl);
      expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
      expect(await draftNode!.evaluate((node) => node.isConnected)).toBe(true);
      await expect(draft).toHaveValue(
        "Keep this draft while automation updates another history",
      );
      await expect(
        page.getByText(automated.conversation_title, { exact: true }),
      ).toHaveCount(1);
      expect(
        state.writes.some(
          (path) => path.includes("/agent/run") || path.includes("/delete"),
        ),
      ).toBe(false);
    });
  }
  const firstQuestion = "First persistence must retain this chat";
  const firstAnswer = "Controlled first-run response";
  const firstTitle = "First persisted Workbench history";
  let runs = 0;
  await contract.step(contract.expectedIds("steps")[2], async () => {
    let releaseTitle!: () => void;
    const titleReady = new Promise<void>((resolve) => {
      releaseTitle = resolve;
    });
    await page.route("**/api/conversation/generate_title", async (route) => {
      await titleReady;
      histories.find(
        (item) => item.conversation_id === 1303,
      )!.conversation_title = firstTitle;
      await route.fulfill({ json: { code: 0, data: firstTitle } });
    });
    await page.route("**/api/conversation/1303", (route) =>
      route.fulfill({
        json: {
          code: 0,
          data: [
            {
              conversation_id: 1303,
              message: [],
              workbench_config_version: 1,
              workbench_config: {
                schema_version: 3,
                mode: "generic_chat",
                model_id: 1,
                generation_config: { deep_thinking: false },
                agent_mounts: [],
                skill_mounts: [],
              },
            },
          ],
        },
      }),
    );
    await page.route("**/api/agent/run", async (route) => {
      runs++;
      const request = route.request().postDataJSON();
      expect(request.query).toBe(firstQuestion);
      expect(request.conversation_id).toBeUndefined();
      histories.unshift({
        conversation_id: 1303,
        conversation_title: "New conversation",
        create_time: Date.now(),
        update_time: Date.now(),
        last_activity_time: Date.now(),
      });
      await route.fulfill({
        contentType: "text/event-stream",
        headers: { conversation_id: "1303", "X-Workbench-Config-Version": "1" },
        body: `data: ${JSON.stringify({ type: "final_answer", content: firstAnswer })}\n\n`,
      });
    });
    await draft.fill(firstQuestion);
    await draft.press("Enter");
    await expect(page.getByText(firstAnswer, { exact: true })).toBeVisible();
    // Release the asynchronous title only after the reply is already visible.
    await page.waitForTimeout(200);
    releaseTitle();
    await expect(
      page.getByText(firstTitle, { exact: true }).first(),
    ).toBeVisible({ timeout: 15_000 });
  });
  await contract.assertion(contract.expectedIds("assertions")[2], async () => {
    expect(runs).toBe(1);
    expect(await draftNode!.evaluate((node) => node.isConnected)).toBe(true);
    expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
    await expect(page.getByText(firstQuestion, { exact: true })).toBeVisible();
    await expect(page.getByText(firstAnswer, { exact: true })).toBeVisible();
    await expect(
      page.getByRole("button", { name: new RegExp(firstTitle) }).first(),
    ).toBeVisible();
  });
});
