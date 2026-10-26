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
