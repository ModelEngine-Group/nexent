// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import {
  bodyChunkBytes,
  installTrajectoryFixture,
  modelInput,
  modelOutput,
} from "./fixture";

journey("CHAT-TRAJECTORY-JOURNEY-D4-001", async ({ page, contract }) => {
  const state = await installTrajectoryFixture(page, (request, status) =>
    contract.expectMock5xx(request, status),
  );
  const base = process.env.NEXENT_BASE_URL || "http://localhost:3000";
  contract.deferCleanup(async () => {
    state.cleanupPaused = false;
    state.releaseCleanup?.();
    state.delayedList?.release();
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await page.context().clearCookies();
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${base}/zh/observability`);
  const table = page.locator(".trajectory-table-panel .ant-table");
  const selectVisibleOption = async (name: string) => {
    await page
      .locator(".ant-select-dropdown:visible .ant-select-item-option")
      .filter({ has: page.getByText(name, { exact: true }) })
      .click();
  };
  const open = async () => {
    await table.getByRole("button", { name: "Friday", exact: true }).click();
    await expect(page.getByRole("treeitem", { name: /Friday/ })).toBeVisible();
  };
  const close = async () => {
    await page
      .locator(".ant-drawer-mask")
      .click({ position: { x: 10, y: 10 } });
    await expect(page.getByRole("dialog")).toHaveCount(0);
    // Move off the left edge so the hover sidebar does not cover row controls.
    await page.getByRole("button", { name: "清理轨迹", exact: true }).hover();
  };
  const openCleanup = async (kind: "manual" | "schedule") => {
    await page.getByRole("button", { name: "清理轨迹", exact: true }).click();
    await page
      .getByRole("menuitem", {
        name: kind === "manual" ? "手动清理" : "定时清理",
        exact: true,
      })
      .click();
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
    await expect(
      page.getByText("完整轨迹保留 30 天", { exact: true }),
    ).toHaveCount(0);
    await expect(page.getByText("当前租户统计", { exact: true })).toBeVisible();
    const statisticsTime = page.getByText(/^统计时间：/);
    const originalStatisticsTime = await statisticsTime.innerText();

    for (const [label, option] of [
      ["用户", "Owner"],
      ["智能体", "Friday"],
      ["会话", "并行轨迹评估"],
    ]) {
      await page.getByRole("combobox", { name: label, exact: true }).click();
      await selectVisibleOption(option);
    }
    await expect(
      page.locator(".trajectory-summary").getByText("20", { exact: true }),
    ).toBeVisible();
    await expect(statisticsTime).toHaveText(originalStatisticsTime);
    const timeHeader = table.getByRole("columnheader", {
      name: /最后执行时间/,
    });
    await page.getByRole("button", { name: "筛选开始时间" }).click();
    await page.getByPlaceholder("开始日期").click();
    const startDay = page.locator(".ant-picker-cell-in-view[title]").first();
    const startDate = await startDay.getAttribute("title");
    await startDay.click();
    const confirmTime = page.getByRole("button", { name: /确\s*定/ });
    await expect(confirmTime).toBeEnabled();
    await confirmTime.click();
    await page.getByPlaceholder("结束日期").click();
    const endDay = page.locator(".ant-picker-cell-in-view[title]").nth(3);
    const endDate = await endDay.getAttribute("title");
    await endDay.click();
    await confirmTime.click();
    await expect
      .poll(() => state.records.at(-1)?.searchParams.get("started_from"))
      .toBe(new Date(`${startDate}T00:00:00+08:00`).toISOString());
    await expect
      .poll(() => state.records.at(-1)?.searchParams.get("started_to"))
      .toBe(new Date(`${endDate}T00:00:00+08:00`).toISOString());
    await expect(timeHeader).toHaveAttribute("aria-sort", "descending");
    await page
      .locator(".ant-popover")
      .getByRole("button", { name: "清除筛选", exact: true })
      .click();
    await expect
      .poll(() => state.records.at(-1)?.searchParams.get("started_from"))
      .toBeNull();
    await expect(timeHeader).toHaveAttribute("aria-sort", "descending");
    await page.getByRole("button", { name: "筛选开始时间" }).click();
    await page.locator(".ant-pagination-item-2").click();
    await expect
      .poll(() =>
        state.records
          .filter((url) => !url.searchParams.has("facet"))
          .at(-1)
          ?.searchParams.get("query_id"),
      )
      .toBe("query-snapshot");
    await expect(statisticsTime).toHaveText(originalStatisticsTime);
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await expect
      .poll(() =>
        state.records
          .filter((url) => !url.searchParams.has("facet"))
          .at(-1)
          ?.searchParams.get("query_id"),
      )
      .toBeNull();
    expect(
      state.records
        .filter((url) => !url.searchParams.has("facet"))
        .at(-1)
        ?.searchParams.get("page"),
    ).toBe("1");
  });
  await contract.step(steps[1], async () => {
    await expect(table.getByText("V3", { exact: true })).toBeVisible();
    const row = table.getByRole("row").filter({ hasText: "并行轨迹评估" });
    await row.press("Enter");
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
    await expect(page.getByText(/结束时间/)).toBeVisible();
    const input = page
      .locator(".trajectory-node-detail .trajectory-body")
      .filter({ has: page.getByRole("button", { name: "输入", exact: true }) });
    const modelRequest = input.getByRole("table", {
      name: "模型输入",
      exact: true,
    });
    await expect(input.locator(":scope > .ant-table-wrapper")).toHaveCount(1);
    await expect(
      input.locator(".trajectory-code-card, .trajectory-body-preview"),
    ).toHaveCount(0);
    await expect(modelRequest.locator(":scope > thead")).toHaveCount(0);
    const requestRows = modelRequest.locator(":scope > tbody > tr");
    const messagesRow = requestRows.filter({
      has: page.getByRole("rowheader", { name: "messages", exact: true }),
    });
    const modelMessages = messagesRow.getByRole("table", {
      name: "模型输入消息",
      exact: true,
    });
    await expect(modelMessages.locator(":scope > thead")).toHaveCount(0);
    const systemRow = modelMessages.getByRole("row").filter({
      has: page.getByRole("rowheader", { name: "system", exact: true }),
    });
    await expect(systemRow.locator(":scope > :is(th, td)")).toHaveCount(2);
    for (const [name, value] of [
      ["enable_thinking", "false"],
      ["temperature", "0"],
    ]) {
      const parameterRow = requestRows.filter({
        has: page.getByRole("rowheader", { name, exact: true }),
      });
      await expect(
        parameterRow.getByRole("cell", { name: value, exact: true }),
      ).toBeVisible();
    }
    await expect(
      modelMessages.getByRole("heading", { name: "Storage instructions" }),
    ).toBeVisible();
    await expect(
      modelMessages.getByRole("table").getByRole("cell", { name: "Retention" }),
    ).toBeVisible();
    const modes = input.getByRole("radiogroup");
    await modes.getByText("文本", { exact: true }).click();
    await expect(input.locator("pre code")).toHaveText(modelInput);
    await modes.getByText("表格", { exact: true }).click();
    await expect(modelMessages).toBeVisible();
    const nodeDetail = page.locator(".trajectory-node-detail");
    const reasoning = nodeDetail.getByRole("table", {
      name: "模型思考",
      exact: true,
    });
    await expect(reasoning.locator("strong")).toHaveText(
      "Compare retention policies",
    );
    const output = nodeDetail.locator(".trajectory-body").filter({
      has: page.getByRole("button", { name: "输出", exact: true }),
    });
    const response = output.getByRole("table", { name: "输出", exact: true });
    await expect(
      response
        .getByRole("table", { name: "choices", exact: true })
        .getByRole("heading", { name: "Storage recommendation" }),
    ).toBeVisible();
    const outputModes = output.getByRole("radiogroup");
    await nodeDetail.evaluate((detail) => {
      detail.scrollTop = detail.scrollHeight;
    });
    await outputModes.scrollIntoViewIfNeeded();
    const scrollTop = () => nodeDetail.evaluate((detail) => detail.scrollTop);
    const before = await scrollTop();
    expect(before).toBeGreaterThan(0);
    await outputModes.getByText("文本", { exact: true }).click();
    await expect(output.locator("pre code")).toHaveText(modelOutput);
    await expect.poll(scrollTop).toBe(before);
    await outputModes.getByText("JSON", { exact: true }).click();
    await expect(
      outputModes.getByRole("radio", { name: "JSON" }),
    ).toBeChecked();
    await expect.poll(scrollTop).toBe(before);
    await outputModes.getByText("表格", { exact: true }).click();
    await expect(response).toBeVisible();
    await expect.poll(scrollTop).toBe(before);
    await page.getByRole("treeitem", { name: /policy.check/ }).click();
    await expect(output.getByRole("radio")).toHaveCount(2);
    await expect(output.getByRole("table")).toHaveCount(0);
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
    await page.getByRole("combobox", { name: "节点类型" }).click();
    await selectVisibleOption("阶段");
    await expect(page.getByRole("treeitem", { name: /Friday/ })).toBeVisible();
    await expect(page.getByRole("treeitem", { name: /DeepSeek/ })).toHaveCount(
      0,
    );
    const phaseLabel = page
      .getByRole("treeitem", { name: /记忆预检索/ })
      .locator("..");
    const labelBounds = await phaseLabel.boundingBox();
    expect(labelBounds).not.toBeNull();
    await phaseLabel.click({
      position: { x: labelBounds!.width - 30, y: labelBounds!.height / 2 },
    });
    const phaseDetail = page.locator(".trajectory-node-detail");
    await expect(
      phaseDetail.getByRole("heading", { name: "记忆预检索" }),
    ).toBeVisible();
    await expect(phaseDetail.locator(".trajectory-node-times")).toContainText(
      "结束时间",
    );
    await expect(phaseDetail.locator(".trajectory-node-metrics")).toContainText(
      "耗时",
    );
    await expect(
      phaseDetail.locator(".trajectory-node-metrics"),
    ).not.toContainText("Token");
    await expect(
      phaseDetail.locator(".trajectory-node-metrics"),
    ).not.toContainText("吞吐量");
    await expect(
      phaseDetail.locator(".trajectory-node-metrics"),
    ).not.toContainText("TTFT");
    await expect(phaseDetail).not.toContainText("智能体版本");
    await page.getByRole("treeitem", { name: /沙箱初始化/ }).click();
    await expect(
      phaseDetail.getByRole("heading", { name: "沙箱初始化" }),
    ).toBeVisible();
    await page.getByRole("combobox", { name: "节点类型" }).click();
    await selectVisibleOption("全部类型");
    await page.getByRole("treeitem", { name: "代码执行", exact: true }).click();
    await expect(
      phaseDetail.getByRole("heading", { name: "代码执行", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("treeitem", { name: "Python 调用", exact: true })
      .click();
    await expect(
      phaseDetail.getByRole("heading", { name: "Python 调用", exact: true }),
    ).toBeVisible();
    await expect(phaseDetail).toContainText("125 ms");
    await phaseDetail
      .getByRole("button", { name: "父节点", exact: true })
      .click();
    await expect(
      phaseDetail.getByRole("heading", { name: "代码执行", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("treeitem", { name: "read_skill_md", exact: true })
      .click();
    await expect(
      phaseDetail.getByRole("heading", { name: "read_skill_md", exact: true }),
    ).toBeVisible();
    await expect(phaseDetail).toContainText("17.09 ms");
    await page.getByRole("treeitem", { name: /Friday/ }).click();
    const search = page.getByRole("textbox", {
      name: "搜索名称、已加载输入 / 输出",
    });
    await search.fill("retention_days");
    await expect(page.getByRole("treeitem", { name: /Friday/ })).toBeVisible();
    await search.clear();
    await expect
      .poll(() =>
        state.reads.some(
          (url) =>
            url.pathname.includes("/contents/") &&
            url.searchParams.get("offset") === "0" &&
            Number(url.searchParams.get("limit")) === bodyChunkBytes,
        ),
      )
      .toBe(true);
    await expect(
      page.getByRole("button", { name: "读取下一块", exact: true }),
    ).toHaveCount(0);
    const body = page.locator(".trajectory-body pre").first();
    await expect(body.locator("code")).toContainText("aaaa");
    const inputSection = page.locator(".trajectory-body").first();
    const outputSection = page.locator(".trajectory-body").nth(1);
    await outputSection
      .getByRole("radiogroup")
      .getByText("JSON", { exact: true })
      .click();
    const originalBody = await body.locator("code").textContent();
    await inputSection
      .getByRole("button", { name: "自动换行", exact: true })
      .click();
    await expect(
      inputSection.getByRole("button", { name: "取消自动换行", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      outputSection.getByRole("button", { name: "自动换行", exact: true }),
    ).toHaveAttribute("aria-pressed", "false");
    await expect(body).toHaveCSS("white-space", "pre-wrap");
    await expect(body).toHaveCSS("overflow-wrap", "anywhere");
    expect(await body.locator("code").textContent()).toBe(originalBody);
    expect(
      await body.evaluate(
        (element) => element.scrollWidth <= element.clientWidth,
      ),
    ).toBe(true);
    await inputSection
      .getByRole("button", { name: "取消自动换行", exact: true })
      .click();
    await expect(body).toHaveCSS("white-space", "pre");
    const readStart = state.reads.length;
    await body.hover();
    await page.mouse.wheel(0, 600);
    await expect(body.locator("code")).toContainText("终");
    await expect(body.locator("code")).toContainText("aaaa");
    expect(
      state.reads
        .slice(readStart)
        .some(
          (url) => url.searchParams.get("offset") === String(bodyChunkBytes),
        ),
    ).toBe(true);
    await close();
    await page.setViewportSize({ width: 1440, height: 700 });
    state.segmentCount = 4;
    const segmentReadStart = state.reads.length;
    await open();
    const retainedNodes = page.locator(".trajectory-segment-navigation small");
    await expect(retainedNodes).toHaveText("已加载范围 · 500 个节点");
    const loadMore = page.getByRole("button", { name: /加载更多$/ });
    for (let segment = 1; segment <= state.segmentCount; segment++) {
      const requested = () =>
        state.reads
          .slice(segmentReadStart)
          .some(
            (url) => url.searchParams.get("cursor") === `segment-${segment}`,
          );
      if (!requested()) {
        await expect(loadMore).not.toHaveClass(/ant-btn-loading/);
        await loadMore.click();
      }
      await expect.poll(requested).toBe(true);
    }
    await expect(
      page.getByRole("treeitem", { name: /Later tool 4/ }),
    ).toBeVisible();
    await expect(retainedNodes).toHaveText("已加载范围 · 5 个节点");
    await expect(page.getByRole("treeitem", { name: /DeepSeek/ })).toHaveCount(
      0,
    );
    await page
      .getByRole("button", { name: "加载较早轮次", exact: true })
      .click();
    await expect(
      page.getByRole("treeitem", { name: /DeepSeek/ }),
    ).toBeVisible();
    const snapshots = state.reads
      .slice(segmentReadStart)
      .filter((url) => url.pathname.endsWith("/snapshot"));
    expect(snapshots.length).toBeGreaterThanOrEqual(6);
    expect(
      new Set(snapshots.map((url) => url.searchParams.get("limit"))),
    ).toEqual(new Set(["500"]));
    state.segmentCount = 1;
    await close();
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await contract.step(steps[3], async () => {
    const search = page.getByRole("textbox", { name: "会话 ID" });
    const oldId = "9223372036854775805";
    const newId = "9223372036854775804";
    state.queriedTitles.set(oldId, "Delayed query result");
    state.queriedTitles.set(newId, "Current query result");
    const pending = Promise.withResolvers<void>();
    state.delayedList = {
      id: oldId,
      wait: pending.promise,
      release: pending.resolve,
    };
    await search.fill(oldId);
    await search.press("Enter");
    await expect
      .poll(() =>
        state.records.some((url) => url.searchParams.get("id_query") === oldId),
      )
      .toBe(true);
    const staleRequest = page.waitForEvent(
      "requestfailed",
      (request) =>
        new URL(request.url()).searchParams.get("id_query") === oldId,
    );
    await search.fill(newId);
    await search.press("Enter");
    await expect(table.getByText("Current query result")).toBeVisible();
    expect((await staleRequest).failure()?.errorText).toBe("net::ERR_ABORTED");
    pending.resolve();
    state.delayedList = null;
    await expect(table.getByText("Delayed query result")).toHaveCount(0);

    await search.fill("");
    await search.press("Enter");
    await expect(table.getByText("并行轨迹评估")).toBeVisible();
    state.archived = true;
    const newArchive = table.getByText("Newly archived execution");
    await page.clock.install();
    const count = state.records.length;
    await page.evaluate(() => {
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("online"));
    });
    await page.clock.fastForward(60_000);
    await expect(newArchive).toHaveCount(0);
    expect(state.records).toHaveLength(count);
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await expect(newArchive).toBeVisible();
    state.archived = false;
    state.queriedTitles.clear();

    await search.fill("draft");
    await page.getByRole("combobox", { name: "用户", exact: true }).click();
    await selectVisibleOption("Alternate Owner");
    await expect(page.getByRole("textbox", { name: "会话 ID" })).toHaveValue(
      "",
    );
    const currentQuery = () =>
      state.records.filter((url) => !url.searchParams.has("facet")).at(-1)
        ?.searchParams;
    await expect
      .poll(() => currentQuery()?.get("target_user_id"))
      .toBe("alternate-owner");
    expect(currentQuery()?.has("agent_id")).toBe(false);
    expect(currentQuery()?.has("conversation_id")).toBe(false);
    expect(
      state.writes.filter((path) => /chat|run|tool/.test(path)),
    ).toHaveLength(0);
  });
  await contract.step(steps[4], async () => {
    for (const [availability, label] of [
      ["unarchived", "未归档"],
      ["not_captured", "未采集"],
      ["expired", "已清理"],
      ["corrupt", "轨迹文件损坏"],
    ]) {
      state.availability = availability;
      await page.getByRole("button", { name: "刷新", exact: true }).click();
      await expect(table.getByText(label, { exact: true })).toBeVisible();
      const snapshots = state.reads.filter((url) =>
        url.pathname.endsWith("/snapshot"),
      ).length;
      await table.getByRole("button", { name: "Friday", exact: true }).click();
      const drawer = page.getByRole("dialog");
      await expect(drawer.getByText(label, { exact: true })).toBeVisible();
      await expect(drawer.locator(".trajectory-viewer-identity")).toContainText(
        "— Tokens",
      );
      await expect(drawer.getByRole("treeitem")).toHaveCount(0);
      expect(
        state.reads.filter((url) => url.pathname.endsWith("/snapshot")),
      ).toHaveLength(snapshots);
      await close();
    }

    state.availability = "available";
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    state.failure = "snapshot_reset";
    await table.getByRole("button", { name: "Friday", exact: true }).click();
    await expect(
      page.getByText("数据范围已变化，请重新查询", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("private preview", { exact: true }),
    ).toHaveCount(0);
    await close();
    state.failure = "";
    await page.goto(`${base}/en/observability`);
    await expect(
      page.getByRole("heading", { name: "Observability center" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Conversation trajectories" }),
    ).toBeVisible();
    await page.goto(`${base}/zh/observability`);
    await expect(
      page.getByRole("heading", { name: "可观测中心" }),
    ).toBeVisible();
    for (const role of ["USER", "DEV"]) {
      state.role = role;
      const before = state.trajectoryRequests.length;
      await page.goto(`${base}/zh/observability`);
      await expect(page).not.toHaveURL(/\/observability\/?$/);
      await expect(
        page
          .getByRole("navigation")
          .getByRole("button", { name: "可观测中心" }),
      ).toHaveCount(0);
      await expect(
        page.getByRole("heading", { name: "可观测中心" }),
      ).toHaveCount(0);
      await expect(page.getByText("并行轨迹评估")).toHaveCount(0);
      await expect(page.getByText("private preview")).toHaveCount(0);
      expect(state.trajectoryRequests.length).toBe(before);
    }
    state.role = "OPS";
    await page.goto(`${base}/zh/observability`);
  });
  await contract.step(steps[5], async () => {
    await openCleanup("manual");
    expect(state.cleanups).toHaveLength(0);
    await page.getByRole("spinbutton").fill("7");
    await page.getByRole("button", { name: "确认清理", exact: true }).click();
    await expect(
      page.getByText("存在待处理或失败项，尚未全部完成，可再次清理", {
        exact: true,
      }),
    ).toBeVisible();
    expect(state.cleanups).toEqual([
      { before_days: 7, tenant_id: "tenant" },
      { before_days: 7, cursor: "cleanup-next", tenant_id: "tenant" },
    ]);
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "关闭", exact: true })
      .last()
      .click();
    state.cleanupPartial = false;
    const refreshed = state.records.length;
    await openCleanup("manual");
    await page.getByRole("button", { name: "确认清理", exact: true }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect.poll(() => state.cleanups.length).toBe(4);
    await expect.poll(() => state.records.length).toBeGreaterThan(refreshed);
    state.cleanupPaused = true;
    await openCleanup("manual");
    await page.getByRole("button", { name: "确认清理", exact: true }).click();
    await expect.poll(() => state.cleanups.length).toBe(5);
    const runningDialog = page.getByRole("dialog");
    await expect(
      runningDialog.getByRole("button", { name: "关闭", exact: true }),
    ).toHaveCount(0);
    await expect(
      runningDialog.getByRole("button", { name: "停止后续批次", exact: true }),
    ).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(runningDialog).toBeVisible();
    state.cleanupPaused = false;
    state.releaseCleanup?.();
    await expect.poll(() => state.cleanups.length).toBe(6);
    await expect(runningDialog).toHaveCount(0);
    state.cleanupPaused = false;
    state.cleanupPartial = true;
    await page.goto("about:blank");
    expect(state.cleanups).toHaveLength(6);
  });
  await contract.step(steps[6], async () => {
    state.multiRound = true;
    await page.goto(`${base}/zh/observability`);
    await expect(
      table.getByRole("columnheader", { name: "对话轮次" }),
    ).toBeVisible();
    expect(
      state.records
        .filter((url) => !url.searchParams.has("facet"))
        .at(-1)
        ?.searchParams.get("view"),
    ).toBe("conversation");
    await open();
    // This compact fixture puts the end sentinel in view for automatic advance.
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
  await contract.step(steps[7], async () => {
    const deleted = state.cleanups.length;
    await openCleanup("schedule");
    const dialog = page.getByRole("dialog");
    const input = dialog.getByRole("spinbutton");
    await expect(input).toHaveValue("30");
    await expect(dialog.getByText("每天 00:00 执行")).toBeVisible();
    await input.fill("31");
    await expect(
      dialog.getByRole("button", { name: "保存设置", exact: true }),
    ).toBeDisabled();
    await input.fill("7");
    state.scheduleFailure = true;
    await dialog.getByRole("button", { name: "保存设置", exact: true }).click();
    await expect(
      dialog.getByText("查询暂不可用，请重试或缩小租户/时间范围", {
        exact: false,
      }),
    ).toBeVisible();
    await expect(input).toHaveValue("7");
    state.scheduleFailure = false;
    await dialog.getByRole("button", { name: "重试", exact: true }).click();
    await expect(dialog.getByText("设置已保存")).toBeVisible();
    expect(state.scheduleSaves.at(-1)).toEqual({
      tenant_id: "tenant",
      enabled: true,
      retention_days: 7,
    });
    await dialog
      .getByRole("button", { name: "关闭", exact: true })
      .last()
      .click();
    await openCleanup("schedule");
    await expect(page.getByRole("spinbutton")).toHaveValue("7");
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "关闭", exact: true })
      .last()
      .click();
    state.role = "SU";
    await page.goto(`${base}/zh/observability`);
    await expect(
      page.getByRole("button", { name: "清理轨迹", exact: true }),
    ).toBeEnabled();
    await openCleanup("schedule");
    const reopened = page.getByRole("dialog");
    await expect(
      reopened.getByText(
        "各租户的设置不同，当前显示默认值；保存后将统一所有租户。",
      ),
    ).toBeVisible();
    await reopened.getByRole("spinbutton").fill("7");
    await expect(reopened.getByRole("switch")).toBeChecked();
    await reopened.getByRole("switch").click();
    await expect(reopened.getByRole("spinbutton")).toBeDisabled();
    await expect(reopened.getByText("每天 00:00 执行")).toBeVisible();
    await reopened
      .getByRole("button", { name: "保存设置", exact: true })
      .click();
    const writesBeforeConfirm = state.scheduleSaves.length;
    await page.getByRole("button", { name: "取消", exact: true }).click();
    expect(state.scheduleSaves).toHaveLength(writesBeforeConfirm);
    await reopened
      .getByRole("button", { name: "保存设置", exact: true })
      .click();
    await page.getByRole("button", { name: "确认并同步", exact: true }).click();
    await expect(reopened.getByText("已同步到 2 个租户")).toBeVisible();
    expect(state.scheduleSaves.at(-1)).toEqual({
      all_tenants: true,
      enabled: false,
      retention_days: 7,
    });
    await reopened
      .getByRole("button", { name: "关闭", exact: true })
      .last()
      .click();
    await openCleanup("schedule");
    await expect(page.getByRole("switch")).not.toBeChecked();
    await expect(page.getByRole("spinbutton")).toHaveValue("7");
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "关闭", exact: true })
      .last()
      .click();
    expect(state.cleanups).toHaveLength(deleted);
    await openCleanup("manual");
    const manual = page.getByRole("dialog");
    await expect(
      manual.getByRole("button", { name: "确认清理", exact: true }),
    ).toBeDisabled();
    await manual.getByRole("combobox", { name: "租户", exact: true }).click();
    await selectVisibleOption("Fixture Tenant");
    await manual.getByRole("button", { name: "确认清理", exact: true }).click();
    await expect.poll(() => state.cleanups.length).toBeGreaterThan(deleted);
    await expect(
      manual.getByRole("combobox", { name: "租户", exact: true }),
    ).toHaveCount(0);
    expect(
      state.cleanups
        .slice(deleted)
        .every((payload) => payload.tenant_id === "tenant"),
    ).toBe(true);
    await manual
      .getByRole("button", { name: "关闭", exact: true })
      .last()
      .click();
  });
  for (const id of contract.expectedIds("assertions")) {
    await contract.assertion(id, async () => {
      expect(
        state.cleanups.every((payload) =>
          Object.keys(payload).every((key) =>
            ["before_days", "cursor", "tenant_id"].includes(key),
          ),
        ),
      ).toBe(true);
      expect(
        state.writes.filter((path) => /chat|run|tool/.test(path)),
      ).toHaveLength(0);
    });
  }
});
