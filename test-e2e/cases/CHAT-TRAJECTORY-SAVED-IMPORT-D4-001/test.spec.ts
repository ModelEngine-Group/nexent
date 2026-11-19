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
  const selectedIds: string[] = [];
  const batch = () =>
    page.getByRole("button", { name: "删除所选", exact: true });
  await contract.step(steps[0], async () => {
    await expect(
      page.getByRole("button", { name: "导入", exact: true }),
    ).toHaveCount(0);
    await page.getByRole("link", { name: "导入列表", exact: true }).click();
    await expect(page).toHaveURL(/\/observability\/imports$/);
    await expect(page.getByRole("heading", { name: "导入列表" })).toBeVisible();
    await upload();
    await expect(
      page.getByRole("treeitem", { name: /Archive 2/ }),
    ).toBeVisible();
    await close();
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
    state.saved[0].item.filename = "a.zip";
    state.saved[0].item.imported_at = "2026-11-18T00:00:00Z";
    state.saved[1].item.filename = "z.zip";
    state.saved[1].item.imported_at = "2026-11-17T00:00:00Z";
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await expect(rows().first()).toContainText("a.zip");
    const filename = page.getByRole("columnheader", {
      name: "文件名",
      exact: true,
    });
    await filename.click();
    await expect(filename).toHaveAttribute("aria-sort", "ascending");
    await expect(rows().first()).toContainText("a.zip");
    await filename.click();
    await expect(filename).toHaveAttribute("aria-sort", "descending");
    await expect(rows().first()).toContainText("z.zip");
    const importedAt = page.getByRole("columnheader", {
      name: "导入时间",
      exact: true,
    });
    await importedAt.click();
    await expect(importedAt).toHaveAttribute("aria-sort", "ascending");
    await expect(rows().first()).toContainText("z.zip");
    await importedAt.click();
    await expect(importedAt).toHaveAttribute("aria-sort", "descending");
    await expect(rows().first()).toContainText("a.zip");
    const template = state.saved[0];
    for (let index = 0; index < 19; index++)
      state.saved.push({
        ...template,
        item: {
          ...template.item,
          import_id: `00000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`,
          filename: `extra-${index}.zip`,
          imported_at: "2026-11-16T00:00:00Z",
        },
      });
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await expect(rows()).toHaveCount(20);
    await expect(batch()).toBeDisabled();
    selectedIds.push(
      (await rows().first().getAttribute("data-row-key")) as string,
    );
    await rows().first().getByRole("checkbox").check();
    await page.getByTitle("2", { exact: true }).click();
    await expect(rows()).toHaveCount(1);
    selectedIds.push(
      (await rows().first().getAttribute("data-row-key")) as string,
    );
    await rows().first().getByRole("checkbox").check();
    await expect(page.getByText("已选择 2 条", { exact: true })).toBeVisible();
    // Sorting from a later page returns to page one without losing selection.
    await filename.click();
    await expect(page.locator(".ant-pagination-item-active")).toHaveAttribute(
      "title",
      "1",
    );
    await expect(page.getByText("已选择 2 条", { exact: true })).toBeVisible();
    await page.getByTitle("2", { exact: true }).click();
    await expect(rows()).toHaveCount(1);
  });
  await contract.step(steps[2], async () => {
    await batch().click();
    await expect(page.getByRole("dialog")).toContainText("2 条");
    await page.getByRole("button", { name: "取消", exact: true }).click();
    expect(state.deleteRequests).toHaveLength(0);
    expect(state.saved).toHaveLength(21);
    state.deleteFailures.push(selectedIds[0]);
    await batch().click();
    await page.getByRole("button", { name: "确定", exact: true }).click();
    await expect(
      page.getByText("已删除 1 条，1 条删除失败，请重试。", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText("已选择 1 条", { exact: true })).toBeVisible();
    await expect(page.locator(".ant-pagination-item-active")).toHaveAttribute(
      "title",
      "1",
    );
    expect(state.deleteRequests).toEqual(selectedIds);
    expect(state.saved).toHaveLength(20);
    state.deleteFailures = [];
    await page.getByRole("button", { name: "重试", exact: true }).click();
    await page.getByRole("button", { name: "确定", exact: true }).click();
    await expect(page.getByText("已选择 0 条", { exact: true })).toBeVisible();
    expect(state.deleteRequests).toEqual([...selectedIds, selectedIds[0]]);
    await expect(rows()).toHaveCount(19);
    await page.locator("thead").getByRole("checkbox").check();
    await batch().click();
    await expect(page.getByRole("dialog")).toContainText("19 条");
    await page.getByRole("button", { name: "确定", exact: true }).click();
    await expect(rows()).toHaveCount(0);
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
