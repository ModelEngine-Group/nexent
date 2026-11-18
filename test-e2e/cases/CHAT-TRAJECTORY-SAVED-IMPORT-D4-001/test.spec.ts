// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import {
  archivePayload,
  installArchiveBrowser,
  persistentArchiveData,
} from "../../infra/automation/shared/trajectory_archive_browser.mjs";

journey("CHAT-TRAJECTORY-SAVED-IMPORT-D4-001", async ({ page, contract }) => {
  const payload = archivePayload();
  const { state, base, upload, close } = await installArchiveBrowser(
    page,
    payload,
  );
  contract.deferCleanup(async () => {
    state.release?.();
    state.saved = [];
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await page.context().clearCookies();
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${base}/zh/observability`);
  for (const id of contract.expectedIds("preconditions"))
    await contract.precondition(id, async () => {
      await expect(
        page.getByRole("heading", { name: "可观测中心" }),
      ).toBeVisible();
    });
  const steps = contract.expectedIds("steps");
  const rows = () => page.locator("tbody tr.ant-table-row");
  await contract.step(steps[0], async () => {
    await upload();
    await expect(
      page.getByRole("treeitem", { name: /Archive 2/ }),
    ).toBeVisible();
    await close();
    await page.getByRole("link", { name: "导入列表", exact: true }).click();
    await expect(page).toHaveURL(/\/observability\/imports$/);
    await expect(page.getByRole("heading", { name: "导入列表" })).toBeVisible();
    await expect(
      page.getByText("trajectory.zip", { exact: true }),
    ).toBeVisible();
    for (const label of [
      "文件名",
      "智能体 / 会话",
      "会话 ID",
      "对话轮次",
      "文件大小",
      "导入时间",
    ])
      await expect(
        page.getByRole("columnheader", { name: label, exact: true }),
      ).toBeVisible();
  });
  await contract.step(steps[1], async () => {
    await page.reload();
    await expect(rows()).toHaveCount(1);
    const uploads = state.imports;
    await page.getByRole("button", { name: "查看", exact: true }).click();
    await expect(
      page.getByRole("treeitem", { name: /Archive 2/ }),
    ).toBeVisible();
    await page.getByRole("treeitem", { name: /TOOL/ }).last().click();
    const output = page
      .locator(".trajectory-body")
      .filter({ has: page.getByRole("button", { name: "输出", exact: true }) });
    await output.getByText("文本", { exact: true }).click();
    await expect(output.locator("code")).toHaveText(
      payload.data.pages[2].snapshot.nodes.find(
        (node: { id: string }) => node.id === "node-3",
      ).output.text,
    );
    expect(state.imports).toBe(uploads);
    await close();
    await upload();
    await close();
    await expect(rows()).toHaveCount(2);
    expect(
      new Set(
        state.saved.map(
          (entry: { item: { import_id: string } }) => entry.item.import_id,
        ),
      ).size,
    ).toBe(2);
  });
  await contract.step(steps[2], async () => {
    await rows()
      .first()
      .getByRole("button", { name: "删除", exact: true })
      .click();
    await page.getByRole("button", { name: "取消", exact: true }).click();
    await expect(rows()).toHaveCount(2);
    for (let count = 1; count >= 0; count--) {
      await rows()
        .first()
        .getByRole("button", { name: "删除", exact: true })
        .click();
      await page.getByRole("button", { name: "确定", exact: true }).click();
      await expect(rows()).toHaveCount(count);
    }
    await page.reload();
    await expect(page.getByText("暂无导入轨迹", { exact: true })).toBeVisible();
    await page.getByRole("link", { name: "返回轨迹列表" }).click();
    await expect(
      page
        .locator(".trajectory-table-panel")
        .getByRole("button", { name: "Source Agent" }),
    ).toBeVisible();
    expect(state.writes).toHaveLength(0);
    expect(state.saved).toHaveLength(0);
  });
  for (const id of contract.expectedIds("assertions"))
    await contract.assertion(id, async () => {
      const stored = await persistentArchiveData(page);
      expect(stored.local + stored.session).not.toContain("归档正文");
      expect(stored.executed).toBe(false);
      expect(state.external).toHaveLength(0);
      expect(state.reads).toBe(0);
    });
});
