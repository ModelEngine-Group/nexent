// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("WB-PIN-DELETE-D4-001", async ({ page, contract }) => {
  const histories = [
    {
      conversation_id: 101,
      conversation_title: "Keep this history",
      create_time: new Date().toISOString(),
    },
    {
      conversation_id: 102,
      conversation_title: "Delete pinned history",
      create_time: new Date(Date.now() - 86400000 * 30).toISOString(),
    },
  ];
  const state = await prepareWorkbench(page, 1, { histories });
  const deletions: number[][] = [];
  await page.route("**/api/conversation/batch-delete", async (route) => {
    const ids = route.request().postDataJSON().conversation_ids as number[];
    deletions.push(ids);
    for (let i = histories.length - 1; i >= 0; i--) {
      if (ids.includes(histories[i].conversation_id)) histories.splice(i, 1);
    }
    await route.fulfill({
      json: { code: 0, data: { deleted_count: ids.length, failed_ids: [] } },
    });
  });
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await expect(
        page.getByText("Delete pinned history", { exact: true }),
      ).toBeVisible();
      await expect(
        page.getByText("Keep this history", { exact: true }),
      ).toBeVisible();
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    const menu = page.getByRole("button", {
      name: "Delete pinned history 的会话操作",
      exact: true,
    });
    await menu.focus();
    await menu.press("Enter");
    await page.getByRole("menuitem", { name: "置顶", exact: true }).click();
    await expect(page.locator('svg[aria-label="置顶对话"]')).toHaveCount(1);
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await page.getByRole("button", { name: "管理", exact: true }).click();
    await page.getByText("Delete pinned history", { exact: true }).click();
    await page.getByRole("button", { name: "删除", exact: true }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: /确.*定|删.*除/ })
      .click();
    await expect(
      page.getByText("Delete pinned history", { exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByText("Keep this history", { exact: true }),
    ).toBeVisible();
    expect(deletions).toEqual([[102]]);
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    await page.reload();
    await expect(
      page.getByText("Keep this history", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Delete pinned history", { exact: true }),
    ).toHaveCount(0);
  });
  await contract.assertion(contract.expectedIds("assertions")[0], async () => {
    expect(histories.map((history) => history.conversation_id)).toEqual([101]);
    expect(deletions).toEqual([[102]]);
    expect(state.writes.every((path) => path.endsWith("/workbench_pin"))).toBe(
      true,
    );
  });
});
