import { expect, test } from "@playwright/test";

test("AC-011 AC-020 Dreaming page shows active version and supports switching", async ({
  context,
  page,
}) => {
  const token = process.env.TEST_JWT;
  if (!token) throw new Error("TEST_JWT is required");
  await context.addCookies([
    {
      name: "nexent_access_token",
      value: token,
      domain: "localhost",
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
    },
    {
      name: "nexent_token_expires_at",
      value: String(Math.floor(Date.now() / 1000) + 3600),
      domain: "localhost",
      path: "/",
      httpOnly: false,
      sameSite: "Lax",
    },
  ]);
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto("/zh/memory");
  await page.getByRole("tab", { name: "Dreaming" }).click();
  await expect(page.getByRole("heading", { name: "Dreaming" })).toBeVisible();
  const activeTag = page.getByText(/Active V\d+/);
  await expect(activeTag).toBeVisible();
  const initialActive = await activeTag.textContent();
  await expect(page.getByText("版本历史")).toBeVisible();
  await expect(page.getByText("最近一次筛选结果")).toBeVisible();
  await expect(page.getByText("排序后最多 10 条新记忆")).toBeVisible();

  const switchButton = page
    .getByRole("button", { name: "切换至此版本" })
    .first();
  if (await switchButton.isVisible()) {
    await switchButton.click();
    await expect(activeTag).not.toHaveText(initialActive || "");
  }

  const runButton = page.getByRole("button", { name: "立即 Dreaming" });
  await expect(runButton).toBeEnabled();
  const runResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/memory/dreaming/run") &&
      response.request().method() === "POST"
  );
  await runButton.click();
  expect((await runResponse).status()).toBe(202);
  await expect(
    page.getByText(/Dreaming 进行中|Dreaming 已进入后台队列/)
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/dreaming-memory-page.png",
    fullPage: true,
  });
  const dreamingConsoleErrors = consoleErrors.filter((entry) =>
    /dreaming|memory\/dreaming/i.test(entry)
  );
  expect(dreamingConsoleErrors).toEqual([]);
});
