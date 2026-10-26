// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  test,
  expect,
  loadSourceChat,
  sourceJourney,
  saveSourceResults,
} from "../../infra/automation/d4/helpers/source-performance";

test("PW-SOURCES-300 source inspection retains both entry points and metadata hover", async ({
  page,
}) => {
  const context = await loadSourceChat(page);
  const samples = await sourceJourney(page);
  await page.locator(".aui-source-group-button").click();
  const panel = page.locator('[data-slot="sources-panel"]');
  await expect(panel.getByRole("heading")).toContainText("300");
  await panel
    .getByRole("button", { name: "关闭来源面板", exact: true })
    .click();
  const lastCitation = page.locator("[data-citation-marker]").last();
  await expect(lastCitation).toHaveAttribute(
    "data-citation-display-index",
    "101",
  );
  await lastCitation.click();
  await expect(panel).toHaveAttribute("data-source-page", "15");
  await panel.getByTitle("1", { exact: true }).click();
  await expect(panel).toHaveAttribute("data-source-page", "1");
  await lastCitation.click();
  await expect(panel).toHaveAttribute("data-source-page", "15");
  await expect(panel.locator('[data-citation-key="j300"]')).toHaveAttribute(
    "data-citation-selected",
    "true",
  );
  await panel.getByTitle("1", { exact: true }).click();
  const metadata = page.locator("[data-source-metadata]").first();
  await expect(metadata.getByText(/^\+\d+$/)).toHaveCount(0);
  await page.setViewportSize({ width: 1000, height: 900 });
  expect(
    await metadata
      .locator("button > span")
      .evaluate((element) => element.getBoundingClientRect().height),
  ).toBeLessThanOrEqual(44);
  await metadata.getByRole("button").hover();
  await expect(
    page.getByRole("dialog", { name: "来源属性", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await page.mouse.move(5, 5);
  await metadata.getByRole("button").hover();
  const dialog = page.getByRole("dialog", { name: "来源属性", exact: true });
  await expect(dialog).toBeVisible();
  await page.mouse.click(5, 5);
  await expect(dialog).toBeHidden();
  expect(context.errors).toEqual([]);
  saveSourceResults("source-functional", { ...context, samples });
});

test("PW-SOURCES-300 ES-shaped frontend retains source preview controls", async ({
  page,
}) => {
  const context = await loadSourceChat(page, "es");
  const samples = await sourceJourney(page);
  await page.locator(".aui-source-group-button").click();
  await expect(
    page
      .locator('[data-slot="sources-panel"]')
      .getByRole("button", { name: "预览 source-1.pdf", exact: true }),
  ).toBeEnabled();
  expect(context.errors).toEqual([]);
  saveSourceResults("source-es-shaped-frontend", {
    ...context,
    samples,
    scope:
      "Frontend fixture only; no real ES, MinIO, embedding or retrieval acceptance",
  });
});

test("PW-SOURCES-300 image pages and shorter message lists keep correct bounds", async ({
  page,
}) => {
  const context = await loadSourceChat(page, "aidp", {
    images: 45,
    shortMessage: true,
  });
  const panel = page.locator('[data-slot="sources-panel"]');
  await page.locator('[data-citekey="b45"]').click();
  await expect(panel).toHaveAttribute("data-source-page", "3");
  await expect(panel.getByRole("tab", { name: /图片/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(panel.getByRole("img", { name: /^Image / })).toHaveCount(5);
  await expect(
    panel.getByRole("img", { name: "Image 45", exact: true }),
  ).toBeVisible();
  await panel.getByTitle("1", { exact: true }).click();
  await expect(panel.getByRole("img", { name: /^Image / })).toHaveCount(20);
  await page.locator('[data-citekey="b45"]').click();
  await expect(panel).toHaveAttribute("data-source-page", "3");
  await panel.getByRole("tab", { name: /来源/ }).click();
  await expect(panel).toHaveAttribute("data-source-page", "1");
  await panel.getByTitle("15", { exact: true }).click();
  await page.locator('[data-citekey="k3"]').click();
  await expect(panel).toHaveAttribute("data-source-page", "1");
  await expect(panel.locator("[data-source-metadata]")).toHaveCount(3);
  await expect(panel.getByRole("navigation")).toHaveCount(0);
  await expect(panel.locator('[data-citation-key="k3"]')).toHaveAttribute(
    "data-citation-selected",
    "true",
  );
  expect(context.errors).toEqual([]);
  saveSourceResults("source-pagination-variants", context);
});
