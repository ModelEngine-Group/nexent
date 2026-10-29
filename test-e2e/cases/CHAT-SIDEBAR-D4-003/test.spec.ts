// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("CHAT-SIDEBAR-D4-003", async ({ page, contract }) => {
  const root = process.env.NEXENT_BASE_URL ?? "http://localhost:3031";
  const agentName = "Agent Seven";
  const offsets: number[] = [];
  let failedOffsetTen = false;
  let observedInitialSkeleton = false;
  let releaseFirstPage!: () => void;
  const firstPageGate = new Promise<void>((resolve) => {
    releaseFirstPage = resolve;
  });
  let globalConversationListCalls = 0;
  await page.setViewportSize({ width: 1600, height: 1000 });
  await prepareWorkbench(page, 1, { histories: [] });
  await page.route("**/api/agent/published_list", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          agent_id: 7,
          name: agentName,
          display_name: agentName,
          description: "101 history fixture",
          current_version_no: 1,
          is_available: true,
          is_main_agent: true,
          model_ids: [1],
        },
        {
          agent_id: 8,
          name: "Agent Eight",
          display_name: "Agent Eight",
          description: "Unrelated discovery Agent",
          current_version_no: 1,
          is_available: true,
          is_main_agent: true,
          model_ids: [1],
        },
      ]),
    }),
  );
  await page.route("**/api/conversation/list**", async (route) => {
    globalConversationListCalls += 1;
    await route.fallback();
  });
  await page.route("**/api/conversation/agent_groups**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        code: 0,
        message: "success",
        data: {
          items: [],
          pinned_items: [],
          included_items: [],
          next_cursor: null,
        },
      }),
    }),
  );
  await page.route(
    /\/api\/conversation\/agent_groups\/agent(?::|%3[Aa])7\/conversations(?:\?|$)/,
    async (route) => {
      const url = new URL(route.request().url());
      const cursor = url.searchParams.get("cursor");
      const offset = cursor ? Number(cursor) : 0;
      offsets.push(offset);
      if (offset === 0) await firstPageGate;
      if (offset === 10 && !failedOffsetTen) {
        failedOffsetTen = true;
        await route.abort("failed");
        return;
      }
      const count = Math.min(10, 101 - offset);
      const items = Array.from({ length: count }, (_, index) => {
        const id = 101 - offset - index;
        return {
          conversation_id: id,
          conversation_title: `Session ${String(id).padStart(3, "0")}`,
          agent_id: 7,
          create_time: Date.now() - (101 - id) * 1000,
          update_time: Date.now() - (101 - id) * 1000,
          last_activity_time: Date.now() - (101 - id) * 1000,
          pinned_at: null,
        };
      });
      const nextOffset = offset + count;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          code: 0,
          message: "success",
          data: {
            items,
            pinned_items: [],
            next_cursor: nextOffset < 101 ? String(nextOffset) : null,
          },
        }),
      });
    },
  );
  await page.goto(`${root}/zh/newchat`);

  const conversationViewport = page.getByTestId(
    "agent-history-conversation-viewport",
  );
  const agentCard = () =>
    page.getByRole("button").filter({ hasText: agentName }).last();
  const scrollNearBottom = () =>
    conversationViewport.evaluate((element) => {
      element.scrollTop = 0;
      element.dispatchEvent(new Event("scroll", { bubbles: true }));
      element.scrollTop = Math.max(
        0,
        element.scrollHeight - element.clientHeight - 80,
      );
      element.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
  const rowTitle = (id: number) =>
    page.getByText(`Session ${String(id).padStart(3, "0")}`, { exact: true });

  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await expect(agentCard()).toBeVisible();
      expect(globalConversationListCalls).toBe(0);
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await agentCard().click();
    const skeleton = page.locator("[role='status']").filter({
      has: page.locator(".animate-pulse"),
    });
    await expect(skeleton.first()).toBeVisible();
    observedInitialSkeleton = true;
    releaseFirstPage();
    await expect(page.getByText("正在加载对话", { exact: true })).toHaveCount(
      0,
    );
    await expect(rowTitle(101)).toBeVisible();
    await expect(rowTitle(92)).toBeVisible();
    await expect(rowTitle(91)).toHaveCount(0);
    await expect(conversationViewport).toHaveCSS("max-height", "none");
    expect(
      await conversationViewport.evaluate((element) => element.clientHeight),
    ).toBeGreaterThan(320);
    await expect(conversationViewport).toHaveAttribute(
      "aria-label",
      "对话历史滚动区域",
    );
    await expect(
      page.getByTestId("agent-history-scroll-shadow-top"),
    ).toHaveCount(0);
    await expect(
      page.getByTestId("agent-history-scroll-shadow-bottom"),
    ).toHaveCount(0);
    await expect(
      conversationViewport.getByRole("button", { name: "加载更多" }),
    ).toHaveCount(0);
  });
  await contract.assertion(contract.expectedIds("assertions")[0], async () => {
    expect(observedInitialSkeleton).toBe(true);
    expect(offsets[0]).toBe(0);
    expect(globalConversationListCalls).toBe(0);
    await expect(rowTitle(101)).toBeVisible();
    await expect(conversationViewport).toHaveCSS("max-height", "none");
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await scrollNearBottom();
    await expect(
      conversationViewport.getByRole("button", { name: "重试", exact: true }),
    ).toBeVisible();
    await expect(rowTitle(101)).toBeVisible();
    await conversationViewport
      .getByRole("button", { name: "重试", exact: true })
      .click();
    await expect(rowTitle(91)).toBeVisible();
    await expect
      .poll(() =>
        conversationViewport.evaluate(
          (element) => element.scrollHeight > element.clientHeight,
        ),
      )
      .toBe(true);
    await conversationViewport.evaluate((element) => {
      element.scrollTop = 20;
      element.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await expect(
      page.getByTestId("agent-history-scroll-shadow-top"),
    ).toBeVisible();
    await expect(
      page.getByTestId("agent-history-scroll-shadow-bottom"),
    ).toBeVisible();
    let loadedCount = await page.getByText(/^Session \d{3}$/).count();
    while (loadedCount < 101) {
      await scrollNearBottom();
      await expect
        .poll(() => page.getByText(/^Session \d{3}$/).count())
        .toBeGreaterThan(loadedCount);
      loadedCount = await page.getByText(/^Session \d{3}$/).count();
    }
    await scrollNearBottom();
    await expect(
      conversationViewport.getByText("没有更多了", { exact: true }),
    ).toBeVisible();
    await expect(
      conversationViewport.getByText("没有更多了", { exact: true }),
    ).toHaveCount(0, { timeout: 1500 });
    await expect(page.getByText(/^Session \d{3}$/)).toHaveCount(101);
    await expect(rowTitle(1)).toBeVisible();
    expect(offsets.slice(0, 3)).toEqual([0, 10, 10]);
    expect(offsets.slice(3)).toEqual([20, 30, 40, 50, 60, 70, 80, 90, 100]);
    expect(globalConversationListCalls).toBe(0);
  });
  await contract.assertion(contract.expectedIds("assertions")[1], async () => {
    const titles = await page.getByText(/^Session \d{3}$/).allTextContents();
    expect(titles).toHaveLength(101);
    expect(new Set(titles).size).toBe(101);
    await expect(
      conversationViewport.getByRole("button", { name: "重试", exact: true }),
    ).toHaveCount(0);
    await expect(
      conversationViewport.getByText("没有更多了", { exact: true }),
    ).toHaveCount(0);
    await expect(page.getByTestId("agent-history-group-viewport")).toHaveCount(
      0,
    );
    expect(globalConversationListCalls).toBe(0);
  });
});
