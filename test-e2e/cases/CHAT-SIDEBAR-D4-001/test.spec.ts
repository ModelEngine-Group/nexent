// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("CHAT-SIDEBAR-D4-001", async ({ page, contract }) => {
  await page.setViewportSize({ width: 1174, height: 1188 });
  const histories = [
    {
      conversation_id: 101,
      conversation_title: "Today notes",
      create_time: new Date().toISOString(),
    },
    {
      conversation_id: 102,
      conversation_title: "Recent review",
      create_time: new Date(Date.now() - 3 * 86400000).toISOString(),
    },
    {
      conversation_id: 103,
      conversation_title: "Older deck",
      create_time: new Date(Date.now() - 30 * 86400000).toISOString(),
    },
  ] as Array<Record<string, any>>;
  const state = await prepareWorkbench(page, 1, { histories });
  const labels = () =>
    page.locator('[data-slot="aui_thread-list-group-label"]');
  const expectRowTimes = async () => {
    await page.mouse.move(1100, 100);
    await expect(page.getByText("3天前", { exact: true })).toBeVisible();
    await expect(page.getByText("30天前", { exact: true })).toBeVisible();
  };
  const menu = async (title: string) => {
    const trigger = page.getByRole("button", {
      name: `${title} 的会话操作`,
      exact: true,
    });
    await trigger.focus();
    await trigger.press("Enter");
  };
  const pinned = async (title: string) => {
    await expect(labels().first()).toHaveText("置顶对话");
    await expect(page.locator('svg[aria-label="置顶对话"]')).toHaveCount(1);
    const firstHistoryY = (await page
      .getByText(title, { exact: true })
      .boundingBox())!.y;
    const todayY = (await page
      .getByText("Today notes", { exact: true })
      .boundingBox())!.y;
    expect(firstHistoryY).toBeLessThan(todayY);
  };
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await expect(page.getByText("Older deck", { exact: true })).toBeVisible();
      await expect(
        page.getByRole("button", { name: /的会话操作$/ }),
      ).toHaveCount(3);
      await expect(page.getByText("置顶对话", { exact: true })).toHaveCount(0);
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await expectRowTimes();
    await page.evaluate(() =>
      localStorage.setItem("chat.pinnedThreadIds", '["agent-chat-existing"]'),
    );
    await menu("Older deck");
    await page.getByRole("menuitem", { name: "置顶", exact: true }).click();
    await pinned("Older deck");
    await expectRowTimes();
    await menu("Older deck");
    await expect(
      page.getByRole("menuitem", { name: "取消置顶", exact: true }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await page.reload();
    await pinned("Older deck");
    await expectRowTimes();
    await page
      .locator("[data-workbench-header-actions]")
      .getByRole("button", {
        name: "搜索",
        exact: true,
      })
      .click();
    const search = page.getByPlaceholder("搜索历史对话");
    await search.fill("Older");
    await expect(page.getByText("Older deck", { exact: true })).toBeVisible();
    await expect(page.getByText("Today notes", { exact: true })).toHaveCount(0);
    await search.fill("Today");
    await expect(page.getByText("Older deck", { exact: true })).toHaveCount(0);
    await expect(page.getByText("置顶对话", { exact: true })).toHaveCount(0);
    await search.fill("No matching history");
    await expect(
      page.getByText("未找到匹配的对话", { exact: true }),
    ).toBeVisible();
    await search.clear();
    await pinned("Older deck");
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    await menu("Older deck");
    await page.getByRole("menuitem", { name: "重命名", exact: true }).click();
    const input = page.getByRole("textbox", { name: "重命名", exact: true });
    await input.fill("  Pinned presentation  ");
    await input.press("Enter");
    await pinned("Pinned presentation");
    await menu("Pinned presentation");
    await page.getByRole("menuitem", { name: "取消置顶", exact: true }).click();
    await expect(page.getByText("置顶对话", { exact: true })).toHaveCount(0);
    expect(
      (await page
        .getByText("Pinned presentation", { exact: true })
        .boundingBox())!.y,
    ).toBeGreaterThan(
      (await page.getByText("Recent review", { exact: true }).boundingBox())!.y,
    );
    await page.reload();
    await expect(
      page.getByText("Pinned presentation", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText("置顶对话", { exact: true })).toHaveCount(0);
    await menu("Pinned presentation");
    await expect(
      page.getByRole("menuitem", { name: "置顶", exact: true }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
  });
  await contract.step(contract.expectedIds("steps")[3], async () => {
    await menu("Pinned presentation");
    await page.getByRole("menuitem", { name: "置顶", exact: true }).click();
    await pinned("Pinned presentation");
    state.authorization.userId = "another-user";
    await page.reload();
    await expect(
      page.getByText("Pinned presentation", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText("置顶对话", { exact: true })).toHaveCount(0);
    state.authorization.userId = "workbench-fixture";
    state.authorization.tenantId = "another-tenant";
    await page.reload();
    await expect(
      page.getByText("Pinned presentation", { exact: true }),
    ).toBeVisible();
    await pinned("Pinned presentation");
    state.authorization.tenantId = "workbench-tenant";
    await page.reload();
    await pinned("Pinned presentation");
  });
  await contract.step(contract.expectedIds("steps")[4], async () => {
    for (const history of histories) {
      delete history.create_time;
      delete history.update_time;
    }
    await page.reload();
    await pinned("Pinned presentation");
    await expect(page.getByText(/^(刚刚|\d+(分钟|小时|天)前)$/)).toHaveCount(0);
    await menu("Pinned presentation");
    await page.getByRole("menuitem", { name: "取消置顶", exact: true }).click();
    // The sidebar header owns the fallback label; do not duplicate it inside the list.
    await expect(labels()).toHaveCount(0);
    await expect(page.getByText("最近对话", { exact: true })).toHaveCount(1);
    await expect(page.getByText("最近对话", { exact: true })).toBeVisible();
    await expect(
      page.getByText("Pinned presentation", { exact: true }),
    ).toBeVisible();
  });
  await contract.step(contract.expectedIds("steps")[5], async () => {
    histories[0].create_time = new Date().toISOString();
    histories.splice(
      2,
      0,
      ...Array.from({ length: 40 }, (_, index) => ({
        conversation_id: 200 + index,
        conversation_title: `Additional history ${index}`,
        create_time: new Date(
          Date.now() - (index + 1) * 86400000,
        ).toISOString(),
      })),
    );
    await menu("Pinned presentation");
    await page.getByRole("menuitem", { name: "置顶", exact: true }).click();
    await page.reload();
    await pinned("Pinned presentation");
    await page.getByText("加载更多", { exact: true }).click();
    await expect(
      page.getByText("Additional history 39", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", {
        name: "Pinned presentation 的会话操作",
        exact: true,
      }),
    ).toHaveCount(1);
    await expect(
      page.getByText("Pinned presentation", { exact: true }),
    ).toHaveCount(1);
  });
  await contract.step(contract.expectedIds("steps")[6], async () => {
    const expectOrder = async (titles: string[]) => {
      await expect(labels().first()).toHaveText("置顶对话");
      await expect(page.locator('svg[aria-label="置顶对话"]')).toHaveCount(
        titles.length,
      );
      const positions = await Promise.all(
        titles.map(
          async (title) =>
            (await page.getByText(title, { exact: true }).boundingBox())!.y,
        ),
      );
      for (let index = 1; index < positions.length; index++) {
        expect(positions[index - 1]).toBeLessThan(positions[index]);
      }
    };
    await menu("Today notes");
    await page.getByRole("menuitem", { name: "置顶", exact: true }).click();
    await expectOrder(["Today notes", "Pinned presentation"]);
    await menu("Additional history 0");
    await page.getByRole("menuitem", { name: "置顶", exact: true }).click();
    await expectOrder([
      "Additional history 0",
      "Today notes",
      "Pinned presentation",
    ]);
    await page.reload();
    await expectOrder([
      "Additional history 0",
      "Today notes",
      "Pinned presentation",
    ]);
    await menu("Pinned presentation");
    await page.getByRole("menuitem", { name: "取消置顶", exact: true }).click();
    await expectOrder(["Additional history 0", "Today notes"]);
    await menu("Pinned presentation");
    await page.getByRole("menuitem", { name: "置顶", exact: true }).click();
    await expectOrder([
      "Pinned presentation",
      "Additional history 0",
      "Today notes",
    ]);
    await page.reload();
    await expectOrder([
      "Pinned presentation",
      "Additional history 0",
      "Today notes",
    ]);
    expect(
      (await page
        .getByText("Additional history 1", { exact: true })
        .boundingBox())!.y,
    ).toBeLessThan(
      (await page
        .getByText("Additional history 2", { exact: true })
        .boundingBox())!.y,
    );
  });
  await contract.step(contract.expectedIds("steps")[7], async () => {
    const device = await page.context().browser()!.newContext();
    try {
      const second = await device.newPage();
      await prepareWorkbench(second, 1, {
        histories,
        pinServer: state.pinServer,
      });
      await expect(second.getByText("置顶对话", { exact: true })).toBeVisible();
      expect(
        await second.evaluate(() =>
          localStorage.getItem("chat.pinnedThreadIds"),
        ),
      ).toBeNull();
      const positions = await Promise.all(
        ["Pinned presentation", "Additional history 0", "Today notes"].map(
          async (title) =>
            (await second.getByText(title, { exact: true }).boundingBox())!.y,
        ),
      );
      expect(positions[0]).toBeLessThan(positions[1]);
      expect(positions[1]).toBeLessThan(positions[2]);
      await second
        .getByRole("button", {
          name: "Pinned presentation 的会话操作",
          exact: true,
        })
        .focus();
      await second
        .getByRole("button", {
          name: "Pinned presentation 的会话操作",
          exact: true,
        })
        .press("Enter");
      await second
        .getByRole("menuitem", { name: "取消置顶", exact: true })
        .click();
      await expect(second.locator('svg[aria-label="置顶对话"]')).toHaveCount(2);
      await page.reload();
      await expect(page.locator('svg[aria-label="置顶对话"]')).toHaveCount(2);
      await page.getByText("加载更多", { exact: true }).click();
      await expect(
        page.getByText("Pinned presentation", { exact: true }),
      ).toBeVisible();
      await menu("Pinned presentation");
      await expect(
        page.getByRole("menuitem", { name: "置顶", exact: true }),
      ).toBeVisible();
      state.pinServer.rejectSave = true;
      await page.getByRole("menuitem", { name: "置顶", exact: true }).click();
      await expect(
        page.getByText("读取或保存置顶失败，请稍后重试", { exact: true }),
      ).toBeVisible();
      await expect(page.locator('svg[aria-label="置顶对话"]')).toHaveCount(2);
      state.pinServer.rejectSave = false;

      // Device A reloads only its initial page before B pins an unseen older history.
      await page.reload();
      await expect(page.getByText("Additional history 39", { exact: true })).toHaveCount(0);
      const draft = page.locator("[data-workbench-composer]");
      await draft.fill("Keep this unsent draft while pins synchronize");
      const origin = await page.evaluate(() => performance.timeOrigin);
      const originalUrl = page.url();
      await second.bringToFront();
      await second.getByText("加载更多", { exact: true }).click();
      const oldMenu = second.getByRole("button", { name: "Additional history 39 的会话操作", exact: true });
      await oldMenu.focus();
      await oldMenu.press("Enter");
      await second.getByRole("menuitem", { name: "置顶", exact: true }).click();
      await expect(second.locator('svg[aria-label="置顶对话"]')).toHaveCount(3);
      await page.bringToFront();
      // Embedded pages can remain visible; a real composer interaction must revalidate pins.
      await draft.click();
      await expect(page.getByText("Additional history 39", { exact: true })).toBeVisible();
      await expect(page.locator('svg[aria-label="置顶对话"]')).toHaveCount(3);
      await expect(draft).toHaveValue("Keep this unsent draft while pins synchronize");
      // Existing visibility refresh remains supported after the interaction-only refresh.
      await page.evaluate(() => window.dispatchEvent(new Event("visibilitychange")));
      await expect(draft).toHaveValue("Keep this unsent draft while pins synchronize");
      expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
      expect(page.url()).toBe(originalUrl);
      await page.getByText("加载更多", { exact: true }).click();
      await expect(page.getByText("Additional history 39", { exact: true })).toHaveCount(1);
      await expect(page.getByRole("button", { name: "Additional history 39 的会话操作", exact: true })).toHaveCount(1);
    } finally {
      await device.close();
    }
  });
  await contract.assertion(contract.expectedIds("assertions")[0], async () => {
    await page.mouse.move(1100, 100);
    await expect(
      page.getByText(/^(刚刚|\d+(分钟|小时|天)前)$/).first(),
    ).toBeVisible();
    expect(state.writes).toContain("/api/conversation/rename");
    expect(
      state.writes
        .filter((path) => path !== "/api/conversation/rename")
        .every((path) => path.endsWith("/workbench_pin")),
    ).toBe(true);
    expect(
      await page.evaluate(() => localStorage.getItem("chat.pinnedThreadIds")),
    ).toBe('["agent-chat-existing"]');
  });
});
