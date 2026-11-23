// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("CHAT-SIDEBAR-D4-002", async ({ page, contract }) => {
  const base = process.env.NEXENT_BASE_URL ?? "http://localhost:3031";
  const histories = [
    {
      conversation_id: 101,
      conversation_title: "Sidebar history",
      agent_id: 7,
      create_time: new Date().toISOString(),
    },
  ];
  const agentName =
    "Sidebar acceptance agent with a deliberately long name for overflow verification";
  await page.setViewportSize({ width: 2064, height: 1000 });
  const state = await prepareWorkbench(page, 1, { histories });
  await page.route("**/api/agent/published_list", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          agent_id: 7,
          name: agentName,
          display_name: agentName,
          description: "Sidebar acceptance fixture",
          current_version_no: 3,
          is_available: true,
          is_main_agent: true,
          model_ids: [1],
        },
      ]),
    }),
  );
  await page.reload();
  const canvas = () => page.locator("[data-agent-chat-page]");
  const floating = () => page.locator("[data-floating-sidebar-trigger]");
  const collapse = () =>
    page.getByRole("button", { name: "收起侧边栏", exact: true }).click();
  const expand = () =>
    page.getByRole("button", { name: "展开", exact: true }).click();
  const input = () =>
    page.getByRole("textbox", { name: "对话输入", exact: true });
  const navigate = async (name: string, path: string) => {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/zh/${path}(?:\\?|$)`));
    await page.mouse.move(1800, 900);
    await expect(
      page.getByRole("button", { name: "收起侧边栏", exact: true }),
    ).toBeVisible();
  };
  const selectAgent = async () => {
    await page
      .getByRole("button")
      .filter({ hasText: "Sidebar acceptance fixture" })
      .click();
    await expect(input()).toBeVisible();
    await expect(
      page.getByRole("button", { name: "发现智能体", exact: true }),
    ).toBeVisible();
  };
  const noWrites = () => expect(state.writes).toEqual([]);

  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await expect(input()).toBeVisible();
      await expect(
        page.getByText("Sidebar history", { exact: true }),
      ).toBeVisible();
      noWrites();
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    const before = await input().boundingBox();
    await collapse();
    await expect(floating().getByRole("button")).toHaveCount(2);
    await expect(
      page.getByText("Sidebar history", { exact: true }),
    ).toHaveCount(0);
    expect((await input().boundingBox())!.x).toBeLessThan(before!.x);
    await expect(canvas().locator("header")).toHaveCount(0);
    await expand();
    await navigate("智能体对话", "newchat");
    await expect(
      page.getByRole("heading", { name: "发现智能体" }),
    ).toBeVisible();
    await collapse();
    await expect(floating().getByRole("button")).toHaveCount(1);
    await expect(input()).toHaveCount(0);
    await expand();
    await selectAgent();
    await collapse();
    await expect(floating().getByRole("button")).toHaveCount(3);
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await input().fill("Unsent sidebar acceptance draft");
    await expand();
    await expect(
      page.getByRole("button", { name: "搜索", exact: true }),
    ).toBeVisible();
    await expect(input()).toHaveText("Unsent sidebar acceptance draft");
    await collapse();
    await expect(input()).toHaveText("Unsent sidebar acceptance draft");
    await expect(canvas().locator("header")).toHaveCount(0);
    noWrites();
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    await navigate("工作台", "workbench");
    await collapse();
    await floating()
      .getByRole("button", { name: "新对话", exact: true })
      .click();
    await expect(input()).toBeVisible();
    await expect(floating()).toBeVisible();
    await expect(input()).toBeEmpty();
    await expand();
    await page.getByRole("button", { name: "新对话", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "收起侧边栏", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Sidebar history", { exact: true }),
    ).toBeVisible();
    noWrites();
  });
  await contract.step(contract.expectedIds("steps")[3], async () => {
    await page.setViewportSize({ width: 500, height: 900 });
    await expect(floating()).toBeVisible();
    for (let attempt = 0; attempt < 2; attempt++) {
      await expand();
      const sheet = page.getByRole("dialog");
      await expect(sheet).toBeVisible();
      await expect(
        sheet.getByText("Sidebar history", { exact: true }),
      ).toBeVisible();
      await sheet
        .getByRole("button", { name: "收起侧边栏", exact: true })
        .click();
      await expect(sheet).toHaveCount(0);
      await expect(floating()).toBeVisible();
    }
    await page.setViewportSize({ width: 2064, height: 1000 });
  });
  await contract.step(contract.expectedIds("steps")[4], async () => {
    if (await floating().isVisible()) await expand();
    await collapse();
    await navigate("智能体对话", "newchat");
    await collapse();
    await navigate("工作台", "workbench");
    await collapse();
    await page.reload();
    await expect(
      page.getByRole("button", { name: "收起侧边栏", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Sidebar history", { exact: true }),
    ).toBeVisible();
    await navigate("智能体对话", "newchat");
    await collapse();
    const heading = (await page
      .getByRole("heading", { name: "发现智能体" })
      .boundingBox())!;
    const trigger = (await floating().getByRole("button").boundingBox())!;
    expect(
      Math.abs(heading.y + heading.height / 2 - trigger.y - trigger.height / 2),
    ).toBeLessThanOrEqual(8);
    await expand();
  });
  await contract.step(contract.expectedIds("steps")[5], async () => {
    await expect(page.getByText("最近使用", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "新对话", exact: true }),
    ).toHaveCount(0);
    await expect(input()).toHaveCount(0);
    await selectAgent();
    await page.getByRole("button", { name: "发现智能体", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "发现智能体" }),
    ).toBeVisible();
    await expect(input()).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "新对话", exact: true }),
    ).toHaveCount(0);
    await selectAgent();
    await collapse();
  });
  await contract.step(contract.expectedIds("steps")[6], async () => {
    await input().fill("Responsive unsent draft");
    for (const width of [1900, 1500, 1340, 1188, 1106, 1034, 400, 1900]) {
      await page.setViewportSize({ width: width + 64, height: 1000 });
      const toolbar = floating();
      const expandButton = toolbar.getByRole("button", {
        name: "展开",
        exact: true,
      });
      await expect(expandButton).toBeVisible();
      const title = toolbar.locator(".ant-typography");
      if (width > 1340) await expect(title).toBeVisible();
      else await expect(title).toBeHidden();
      const back = toolbar.getByRole("button", {
        name: "发现智能体",
        exact: true,
      });
      if (width > 1188) await expect(back).toBeVisible();
      else await expect(back).toBeHidden();
      const compose = toolbar.getByRole("button", {
        name: "新对话",
        exact: true,
      });
      if (width > 1106) await expect(compose).toBeVisible();
      else await expect(compose).toBeHidden();
      const geometry = await canvas().evaluate((element) => {
        const button = element.querySelector(
          "[data-floating-sidebar-trigger] button",
        )!;
        const style = getComputedStyle(element);
        const box = element.getBoundingClientRect();
        const target = button.getBoundingClientRect();
        return {
          left: target.left - box.left,
          top: target.top - box.top,
          width: target.width,
          leftPadding: style.paddingLeft,
          rightPadding: style.paddingRight,
        };
      });
      expect(geometry.left).toBe(12);
      expect(geometry.top).toBe(12);
      expect(geometry.width).toBe(32);
      expect(geometry.leftPadding).toBe(geometry.rightPadding);
      if (width <= 1034) {
        await expect(canvas()).toHaveCSS("padding-left", "32px");
        expect((await input().boundingBox())!.x).toBeGreaterThan(
          (await expandButton.boundingBox())!.x + 32,
        );
      }
      await expect(input()).toHaveText("Responsive unsent draft");
      for (const button of await toolbar.getByRole("button").all()) {
        const box = (await button.boundingBox())!;
        expect(box.width).toBeGreaterThanOrEqual(32);
        expect(box.x + box.width).toBeLessThanOrEqual(
          (await canvas().boundingBox())!.x +
            (await canvas().boundingBox())!.width,
        );
      }
    }
    await page.getByRole("button", { name: "智能体对话", exact: true }).focus();
    const menu = page.locator("[data-sidebar-expanded=true]");
    await expect(menu).toBeVisible();
    expect(
      await menu.evaluate((element) =>
        Number(getComputedStyle(element.closest(".ant-layout-sider")!).zIndex),
      ),
    ).toBeGreaterThan(20);
    await page.screenshot({
      path: join(contract.caseDir, "responsive-sidebar.png"),
    });
  });
  await contract.assertion(contract.expectedIds("assertions")[0], async () => {
    await expect(input()).toHaveText("Responsive unsent draft");
    noWrites();
  });
});
