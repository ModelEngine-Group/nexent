// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("CHAT-ROUTE-D4-001", async ({ page, contract }) => {
  const now = Date.now();
  const histories = [
    { conversation_id: 100, conversation_title: "Route saved A", create_time: now, update_time: now },
    { conversation_id: 101, conversation_title: "Route saved C", create_time: now - 1000, update_time: now - 1000 },
  ];
  let state!: Awaited<ReturnType<typeof prepareWorkbench>>;
  let origin = 0;
  const results = [false, false, false];
  const draft = page.getByRole("textbox", { name: "对话输入", exact: true });
  const a = page.locator("button[data-radix-collection-item]").filter({ hasText: "Route saved A" });
  const c = page.locator("button[data-radix-collection-item]").filter({ hasText: "Route saved C" });
  const selected = (row: typeof a) => expect(row.locator("..")).toHaveAttribute("data-active", "true");
  const expectUrl = async (id: string | null) => {
    await expect.poll(() => new URL(page.url()).searchParams.get("conversation_id")).toBe(id);
    const url = new URL(page.url());
    expect(url.searchParams.has("thread_id")).toBe(false);
    expect(url.searchParams.get("qa_route")).toBe("keep");
    expect(url.hash).toBe("#messages");
  };

  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    await page.setViewportSize({ width: 1200, height: 900 });
    state = await prepareWorkbench(page, 1, { histories });
    const url = new URL(page.url());
    url.search = "?thread_id=100&qa_route=keep";
    url.hash = "messages";
    await page.goto(url.toString());
    await selected(a);
    await expect(draft).toBeVisible();
    origin = await page.evaluate(() => performance.timeOrigin);
  });
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await draft.fill("Keep the A composer while switching");
    await c.click();
    await selected(c);
    await expectUrl("101");
    await draft.fill("Keep the C composer while switching");
    await a.click();
    await selected(a);
    await expectUrl("100");
    await expect(draft).toHaveValue("Keep the A composer while switching");
    expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
    results[0] = true;
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await c.click();
    await expectUrl("101");
    await expect(draft).toHaveValue("Keep the C composer while switching");
    await page.reload();
    await selected(c);
    await expectUrl("101");
    await expect(draft).toBeVisible();
    expect(await page.evaluate(() => performance.timeOrigin)).not.toBe(origin);
    results[1] = true;
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    await page.getByRole("button", { name: "新对话", exact: true }).click();
    await expectUrl(null);
    await page.reload();
    await expectUrl(null);
    await expect(draft).toBeVisible();
    await expect(page.locator('[data-active="true"]')).toHaveCount(0);
    results[2] = true;
  });
  for (const [index, id] of contract.expectedIds("assertions").entries()) {
    await contract.assertion(id, async () => {
      expect(results[index]).toBe(true);
      expect(state.writes).toEqual([]);
    });
  }
});
