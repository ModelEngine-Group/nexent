// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { test } from "node:test";
import assert from "node:assert/strict";
import { chromium } from "../../../frontend/node_modules/playwright/index.mjs";
import {
  archivePayload,
  installArchiveBrowser,
} from "../../infra/automation/shared/trajectory_archive_browser.mjs";

test("CHAT-TRAJECTORY-ARCHIVE-RECOVERY-D5-001 lifecycle and late responses", async () => {
  const browser = await chromium.launch({
    channel: "chromium",
    headless: true,
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
    });
    const { state, raw, base, upload, close } = await installArchiveBrowser(
      page,
      archivePayload(),
    );
    try {
      await page.goto(`${base}/zh/observability`);
      await page.getByRole("heading", { name: "可观测中心" }).waitFor();
      await page.getByRole("link", { name: "导入列表", exact: true }).click();
      state.delayImport = true;
      const response = new Promise((resolve) => page.once("request", resolve));
      await page
        .locator('input[type="file"]')
        .setInputFiles({
          name: "trajectory.zip",
          mimeType: "application/zip",
          buffer: raw,
        });
      await response;
      await page.waitForFunction(() =>
        document.querySelector(".trajectory-page-actions .ant-btn-loading"),
      );
      await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
      state.delayImport = false;
      state.release?.();
      await page.evaluate(() => window.dispatchEvent(new Event("pageshow")));
      assert.equal(await page.getByRole("dialog").count(), 0);
      await upload();
      await close();
      await upload();
      await page.reload();
      await page.getByRole("heading", { name: "导入列表" }).waitFor();
      assert.equal(await page.getByRole("dialog").count(), 0);
      await upload();
      await page.goto(`${base}/zh`);
      await page.goBack();
      await page.getByRole("heading", { name: "导入列表" }).waitFor();
      assert.equal(await page.getByRole("dialog").count(), 0);
      await upload();
      await page.evaluate(() => window.dispatchEvent(new Event("auth:logout")));
      await page.getByRole("dialog").waitFor({ state: "detached" });
      assert.deepEqual(state.writes, []);
      assert.equal(state.reads, 0);
    } finally {
      state.release?.();
      await page.unrouteAll({ behavior: "ignoreErrors" });
      await page.context().clearCookies();
      await page.close();
    }
  } finally {
    await browser.close();
  }
});
