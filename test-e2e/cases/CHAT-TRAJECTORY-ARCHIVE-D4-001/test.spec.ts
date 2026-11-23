// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import {
  archivePayload,
  installArchiveBrowser,
  persistentArchiveData,
} from "../../infra/automation/shared/trajectory_archive_browser.mjs";

journey("CHAT-TRAJECTORY-ARCHIVE-D4-001", async ({ page, contract }) => {
  const payload = archivePayload();
  const { state, raw, base, upload, close } = await installArchiveBrowser(
    page,
    payload,
  );
  contract.deferCleanup(async () => {
    state.release?.();
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await page.context().clearCookies();
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto(`${base}/zh/observability`);
  for (const id of contract.expectedIds("preconditions"))
    await contract.precondition(id, async () => {
      await expect(
        page.getByRole("heading", { name: "可观测中心" }),
      ).toBeVisible();
      await expect(
        page
          .locator(".trajectory-table-panel")
          .getByRole("button", { name: "Source Agent" }),
      ).toBeVisible();
    });
  const steps = contract.expectedIds("steps");
  await contract.step(steps[0], async () => {
    await page
      .locator(".trajectory-table-panel")
      .getByRole("button", { name: "Source Agent" })
      .click();
    await expect(
      page.getByRole("treeitem", { name: /Archive 0/ }),
    ).toBeVisible();
    const button = page
      .locator(".ant-drawer-header")
      .getByRole("button", { name: "导出", exact: true });
    const bounds = await button.boundingBox();
    expect(bounds!.x).toBeGreaterThan(1000);
    state.exportFailure = true;
    await button.click();
    await expect(
      page.getByText("查询参数无效", { exact: false }),
    ).toBeVisible();
    state.exportFailure = false;
    const event = page.waitForEvent("download");
    await button.click();
    const download = await event;
    expect(download.suggestedFilename()).toBe("trajectory-123.zip");
    const actual = readFileSync((await download.path())!);
    expect(createHash("sha256").update(actual).digest("hex")).toBe(
      createHash("sha256").update(raw).digest("hex"),
    );
    await download.delete();
    await close();
  });
  const originalReads = state.reads;
  await contract.step(steps[1], async () => {
    await expect(page.getByRole("button", { name: "导入", exact: true })).toHaveCount(0);
    await page.getByRole("link", { name: "导入列表", exact: true }).click();
    const button = page
      .locator(".trajectory-page-actions")
      .getByRole("button", { name: "导入", exact: true });
    expect((await button.boundingBox())!.x).toBeGreaterThan(800);
    const chooser = page.waitForEvent("filechooser");
    await button.click();
    await (
      await chooser
    ).setFiles({
      name: "trajectory.zip",
      mimeType: "application/zip",
      buffer: raw,
    });
    await expect(
      page.getByRole("treeitem", { name: /Archive 2/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "导出", exact: true }),
    ).toHaveCount(0);
  });
  await contract.step(steps[2], async () => {
    await page.getByRole("treeitem", { name: /TOOL/ }).last().click();
    const output = page
      .locator(".trajectory-body")
      .filter({ has: page.getByRole("button", { name: "输出", exact: true }) });
    const code = output.locator("code");
    const original = payload.data.pages[2].snapshot.nodes.find(
      (node: { id: string }) => node.id === "node-3",
    ).output.text;
    await output.getByText("文本", { exact: true }).click();
    await expect(code).toHaveText(original);
    await code.evaluate((element: HTMLElement) => {
      element.parentElement!.scrollTop = element.parentElement!.scrollHeight;
    });
    await output.getByRole("button", { name: "复制", exact: true }).click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
      original,
    );
    await page.getByRole("button", { name: "父节点", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Archive 2", exact: true, level: 2 }),
    ).toBeVisible();
    const search = page.getByRole("textbox", {
      name: "搜索名称、已加载输入 / 输出",
    });
    await search.fill("Archive 1");
    await expect(page.getByRole("treeitem", { name: /Archive 0/ })).toHaveCount(
      0,
    );
    await search.fill("");
    const kind = page.getByRole("combobox", { name: "节点类型" });
    await kind.click();
    await page.locator(".ant-select-dropdown").getByTitle("工具", { exact: true }).click();
    await expect(page.getByRole("treeitem", { name: /TOOL/ }).last()).toBeVisible();
    await kind.click();
    await page.locator(".ant-select-dropdown").getByTitle("全部类型", { exact: true }).click();
    await expect(page.getByRole("treeitem", { name: /Archive 2/ })).toBeVisible();
    await close();
    await upload();
    expect(state.imports).toBe(2);
    await close();
    await upload(true);
    await expect(page.getByRole("treeitem", { name: /Archive 0/ })).toHaveCount(
      0,
    );
    await expect(
      page.getByRole("treeitem", { name: /Replacement 2/ }),
    ).toBeVisible();
    expect(state.reads).toBe(originalReads);
    await close();
    await page.getByRole("link", { name: "返回轨迹列表" }).click();
    await expect(page.locator(".trajectory-table-panel tbody tr.ant-table-row")).toHaveCount(1);
    await page.getByRole("link", { name: "导入列表", exact: true }).click();
  });
  await contract.step(steps[3], async () => {
    await page.reload();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await upload();
    await page.goto(`${base}/zh`);
    await page.goBack();
    await expect(
      page.getByRole("heading", { name: "导入列表" }),
    ).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await upload();
    await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.evaluate(() => window.dispatchEvent(new Event("pageshow")));
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await upload();
    await page.evaluate(() => window.dispatchEvent(new Event("auth:logout")));
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });
  for (const id of contract.expectedIds("assertions"))
    await contract.assertion(id, async () => {
      const stored = await persistentArchiveData(page);
      expect(stored.local + stored.session).not.toContain("归档正文");
      expect(stored.executed).toBe(false);
      expect(state.external).toHaveLength(0);
      expect(state.writes).toHaveLength(0);
    });
});
