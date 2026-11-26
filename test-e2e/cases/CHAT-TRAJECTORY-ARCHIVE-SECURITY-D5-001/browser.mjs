// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { test } from "node:test";
import assert from "node:assert/strict";
import { chromium } from "../../../frontend/node_modules/playwright/index.mjs";
import {
  archivePayload,
  installArchiveBrowser,
  persistentArchiveData,
} from "../../infra/automation/shared/trajectory_archive_browser.mjs";

test("CHAT-TRAJECTORY-ARCHIVE-SECURITY-D5-001 browser isolation", async () => {
  const browser = await chromium.launch({
    channel: "chromium",
    headless: true,
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
    });
    const payload = archivePayload();
    const { state, base, upload, close } = await installArchiveBrowser(
      page,
      payload,
    );
    try {
      await page.goto(`${base}/zh/observability`);
      await page.getByRole("heading", { name: "可观测中心" }).waitFor();
      const before = await persistentArchiveData(page);
      await upload();
      await page.getByRole("treeitem", { name: /TOOL/ }).last().click();
      assert.equal(
        await page.locator('img[src*="invalid.example"]').count(),
        0,
      );
      assert.equal(
        await page.locator(".trajectory-body code").last().textContent(),
        JSON.stringify(
          {
            content: payload.data.pages[2].snapshot.nodes.find(
              (node) => node.id === "node-3",
            ).output.text,
          },
          null,
          2,
        ),
      );
      const stored = await persistentArchiveData(page);
      assert.equal(stored.executed, false);
      assert.equal(stored.local.includes("归档正文"), false);
      assert.equal(stored.session.includes("归档正文"), false);
      assert.deepEqual(stored.databases, before.databases);
      assert.deepEqual(stored.cacheNames, before.cacheNames);
      assert.deepEqual(state.external, []);
      assert.deepEqual(state.writes, []);
      assert.equal(state.imports, 1);
      assert.equal(state.reads, 0);
      await close();
      await page.reload();
      assert.equal(await page.getByRole("dialog").count(), 0);
      state.role = "USER";
      await page.reload();
      await page.waitForFunction(
        () => !document.querySelector(".trajectory-center"),
      );
      assert.equal(
        await page.getByRole("button", { name: "导入", exact: true }).count(),
        0,
      );
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
