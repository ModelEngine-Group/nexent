// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { installTrajectoryFixture } from "./fixture";

journey("CHAT-TRAJECTORY-JOURNEY-D4-001", async ({ page, contract }) => {
  const state = await installTrajectoryFixture(page);
  const base = process.env.NEXENT_BASE_URL || "http://localhost:3000";
  contract.deferCleanup(async () => {
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await page.context().clearCookies();
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${base}/zh/observability`);
  const table = page.locator(".trajectory-panel .ant-table");
  const open = async () => {
    await table.getByRole("button", { name: "Friday", exact: true }).click();
    await expect(page.getByRole("treeitem", { name: /Friday/ })).toBeVisible();
  };
  const close = async () => {
    await page
      .locator(".ant-drawer-mask")
      .click({ position: { x: 10, y: 10 } });
    await expect(page.getByRole("dialog")).toHaveCount(0);
  };
  const preconditions = contract.expectedIds("preconditions");
  for (let index = 0; index < preconditions.length; index++) {
    await contract.precondition(preconditions[index], async () => {
      if (index === 0)
        await expect(
          page.getByRole("heading", { name: "可观测中心" }),
        ).toBeVisible();
      else if (index === 1)
        await expect(table.getByText("9223372036854775806")).toBeVisible();
      else if (index === 2)
        expect(
          state.records.some((url) => !url.searchParams.has("facet")),
        ).toBe(true);
      else expect(state.cleanups).toHaveLength(0);
    });
  }
  const steps = contract.expectedIds("steps");
  await contract.step(steps[0], async () => {
    for (const [label, option] of [
      ["用户", "Owner"],
      ["智能体", "Friday"],
      ["会话", "并行轨迹评估"],
    ]) {
      await page.getByRole("combobox", { name: label, exact: true }).click();
      await page.getByRole("option").filter({ hasText: option }).click();
    }
    await expect(
      page.locator(".trajectory-summary").getByText("20", { exact: true }),
    ).toBeVisible();
    await page.locator(".ant-pagination-item-2").click();
    await expect
      .poll(() =>
        state.records
          .filter((url) => !url.searchParams.has("facet"))
          .at(-1)
          ?.searchParams.get("query_id"),
      )
      .toBe("query-snapshot");
    await page.getByRole("button", { name: "查询", exact: true }).click();
    await expect
      .poll(() =>
        state.records
          .filter((url) => !url.searchParams.has("facet"))
          .at(-1)
          ?.searchParams.get("query_id"),
      )
      .toBeNull();
  });
  await contract.step(steps[1], async () => {
    await expect(table.getByText("V3", { exact: true })).toBeVisible();
    await open();
    await expect(
      page.getByRole("treeitem", { name: /Friday.*V3/ }),
    ).toBeVisible();
    for (const [name, version] of [
      ["存储设计", "V2"],
      ["安全审查", "草稿"],
      ["容量规划", "未知"],
    ]) {
      await page
        .getByRole("treeitem", { name: new RegExp(`${name}.*${version}`) })
        .click();
      await expect(
        page
          .locator(".trajectory-node-detail")
          .getByText(version, { exact: true }),
      ).toBeVisible();
    }
    await expect(page.locator(".trajectory-range-guide").first()).toBeVisible();
    await page.getByRole("treeitem", { name: /DeepSeek/ }).click();
    await expect(
      page.locator(".trajectory-node-detail").getByText(/智能体版本/),
    ).toHaveCount(0);
    await expect(
      page
        .locator(".trajectory-node-detail")
        .getByText("0 ms", { exact: true }),
    ).toBeVisible();
    await expect(
      page
        .locator(".trajectory-node-detail")
        .getByText("吞吐量", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText(/结束时间:/)).toBeVisible();
    await page.getByRole("treeitem", { name: /policy.check/ }).click();
    await expect(
      page.locator(".trajectory-node-detail").getByText(/智能体版本/),
    ).toHaveCount(0);
    await expect(
      page
        .locator(".trajectory-node-detail")
        .getByText("吞吐量", { exact: true }),
    ).toHaveCount(0);
    await close();
    await open();
  });
  await contract.step(steps[2], async () => {
    const search = page.getByRole("textbox", {
      name: "搜索名称、已加载输入 / 输出",
    });
    await search.fill("retention_days");
    await expect(page.getByRole("treeitem", { name: /Friday/ })).toBeVisible();
    await search.clear();
    await page
      .getByRole("button", { name: "展开全文", exact: true })
      .first()
      .click();
    await expect
      .poll(() =>
        state.reads.some(
          (url) =>
            url.pathname.includes("/contents/") &&
            url.searchParams.get("limit") === "1048576",
        ),
      )
      .toBe(true);
    await page
      .getByRole("button", { name: "读取下一块", exact: true })
      .first()
      .click();
    await expect(page.locator(".trajectory-body pre").first()).toHaveText("终");
    await page.getByRole("button", { name: "加载更多", exact: true }).click();
    await expect(
      page.getByRole("treeitem", { name: /Later tool/ }),
    ).toBeVisible();
    await expect(page.getByRole("treeitem", { name: /DeepSeek/ })).toHaveCount(
      0,
    );
    await page.getByRole("button", { name: "上一段", exact: true }).click();
    await expect(
      page.getByRole("treeitem", { name: /DeepSeek/ }),
    ).toBeVisible();
    await close();
  });
  await contract.step(steps[3], async () => {
    const count = state.records.length;
    await page.evaluate(() => {
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("online"));
    });
    await expect.poll(() => state.records.length).toBe(count);
    await page
      .getByRole("textbox", { name: "搜索会话 ID / 节点 Trace ID" })
      .fill("draft");
    await page.getByRole("combobox", { name: "用户", exact: true }).click();
    await page.getByRole("option").filter({ hasText: "Owner" }).click();
    await expect(
      page.getByRole("textbox", { name: "搜索会话 ID / 节点 Trace ID" }),
    ).toHaveValue("");
    expect(
      state.writes.filter((path) => /chat|run|tool/.test(path)),
    ).toHaveLength(0);
  });
  await contract.step(steps[4], async () => {
    await open();
    state.failure = "snapshot_reset";
    await page
      .getByRole("button", { name: "展开全文", exact: true })
      .first()
      .click();
    await expect(
      page.getByText("数据范围已变化，请重新查询", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("private preview", { exact: true }),
    ).toHaveCount(0);
    await close();
    state.failure = "";
    for (const role of ["USER", "DEV"]) {
      state.role = role;
      const before = state.records.length;
      await page.reload();
      await expect(
        page.getByRole("heading", { name: "可观测中心" }),
      ).toHaveCount(0);
      expect(state.records.length).toBe(before);
    }
    state.role = "ADMIN";
    await page.goto(`${base}/zh/observability`);
  });
  await contract.step(steps[5], async () => {
    await page.getByRole("button", { name: "清理轨迹", exact: true }).click();
    expect(state.cleanups).toHaveLength(0);
    await page.getByRole("spinbutton").fill("7");
    await page.getByRole("button", { name: "确认清理", exact: true }).click();
    await expect(
      page.getByText("存在待处理或失败项，尚未全部完成，可再次清理", {
        exact: true,
      }),
    ).toBeVisible();
    expect(state.cleanups).toEqual([
      { before_days: 7 },
      { before_days: 7, cursor: "cleanup-next" },
    ]);
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "关闭", exact: true })
      .last()
      .click();
    state.cleanupPaused = true;
    await page.getByRole("button", { name: "清理轨迹", exact: true }).click();
    await page.getByRole("button", { name: "确认清理", exact: true }).click();
    await expect.poll(() => state.cleanups.length).toBe(3);
    await page
      .getByRole("button", { name: "停止后续批次", exact: true })
      .click();
    await page.goto("about:blank");
    expect(state.cleanups).toHaveLength(3);
  });
  await contract.step(steps[6], async () => {
    state.multiRound = true;
    await page.goto(`${base}/zh/observability`);
    await expect(
      table.getByRole("columnheader", { name: "轮数" }),
    ).toBeVisible();
    expect(
      state.records
        .filter((url) => !url.searchParams.has("facet"))
        .at(-1)
        ?.searchParams.get("view"),
    ).toBe("conversation");
    await open();
    // The product may prefetch the next segment when the end sentinel enters the viewport.
    for (
      let index = 0;
      index < 3 &&
      (await page.getByRole("treeitem", { name: /重试成功/ }).count()) === 0;
      index++
    ) {
      await page.getByRole("button", { name: "加载更多", exact: true }).click();
    }
    await expect(
      page.getByRole("treeitem", { name: /重试成功/ }),
    ).toBeVisible();
    await expect(page.getByRole("treeitem", { name: /Friday/ })).toBeVisible();
    expect(
      await page
        .locator(".trajectory-time-cell[data-round='2'] .trajectory-time-bar")
        .evaluate((element) => (element as HTMLElement).style.left),
    ).toBe("0%");
    await page.getByRole("treeitem", { name: /Friday/ }).click();
    await expect(page.locator(".trajectory-node-detail h2")).toHaveText(
      "Friday",
    );
    await page
      .getByRole("textbox", { name: "搜索名称、已加载输入 / 输出" })
      .fill("重试成功");
    await expect(page.getByRole("treeitem", { name: /Friday/ })).toHaveCount(0);
    await expect(
      page.getByRole("treeitem", { name: /重试成功/ }),
    ).toBeVisible();
    await close();
  });
  for (const id of contract.expectedIds("assertions")) {
    await contract.assertion(id, async () => {
      expect(
        state.cleanups.every((payload) =>
          Object.keys(payload).every((key) =>
            ["before_days", "cursor"].includes(key),
          ),
        ),
      ).toBe(true);
      expect(
        state.writes.filter((path) => /chat|run|tool/.test(path)),
      ).toHaveLength(0);
    });
  }
});
