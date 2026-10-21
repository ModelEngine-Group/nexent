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
  let pollObserved = false;
  const draft = page.getByRole("textbox", { name: "对话输入", exact: true });
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      state = await prepareWorkbench(page, 1, { histories });
      await expect(draft).toBeVisible();
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
    // No reload, navigation or focus event: the visible-page poll must discover it.
    await expect(
      page.getByText(automated.conversation_title, { exact: true }),
    ).toBeVisible({ timeout: 15_000 });
    const oldPosition = await page
      .getByText(automated.conversation_title, { exact: true })
      .boundingBox();
    const controlPosition = await page
      .getByText("Activity control 0", { exact: true })
      .boundingBox();
    expect(oldPosition!.y).toBeLessThan(controlPosition!.y);
    await expect(draft).toHaveValue(
      "Keep this draft while automation updates another history",
    );
    pollObserved = true;
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    const control = histories.find((item) => item.conversation_id === 100)!;
    control.last_activity_time = Date.now() + 1_000;
    histories.splice(histories.indexOf(control), 1);
    histories.unshift(control);
    await page.evaluate(() => {
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("online"));
    });
    await expect
      .poll(async () => {
        const controlPosition = await page
          .getByText(control.conversation_title, { exact: true })
          .boundingBox();
        const oldPosition = await page
          .getByText(automated.conversation_title, { exact: true })
          .boundingBox();
        return controlPosition!.y < oldPosition!.y;
      })
      .toBe(true);
    await expect(
      page.getByText(automated.conversation_title, { exact: true }),
    ).toHaveCount(1);
    await expect(draft).toHaveValue(
      "Keep this draft while automation updates another history",
    );
  });
  for (const id of contract.expectedIds("assertions")) {
    await contract.assertion(id, async () => {
      expect(pollObserved).toBe(true);
      expect(page.url()).toBe(originalUrl);
      expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
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
});
