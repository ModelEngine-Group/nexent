import { expect, test } from "@playwright/test";

test("shows each MCP card's latest connectivity result below its name", async ({
  page,
  context,
}) => {
  await context.addCookies([
    {
      name: "nexent_token_expires_at",
      value: String(Math.floor(Date.now() / 1000) + 3600),
      url: "http://localhost:3000",
    },
  ]);

  let firstCheck = true;
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    let body: unknown = {};
    if (url.pathname.endsWith("/user/current_user_info")) {
      body = {
        data: {
          user: {
            user_id: "mcp-status-test-user",
            tenant_id: "mcp-status-test-tenant",
            user_email: "mcp@nexent.test",
            user_role: "SPEED",
            auth_provider: "local",
            group_ids: [],
            permissions: [],
            accessibleRoutes: ["/mcp-space"],
          },
        },
      };
    } else if (url.pathname.endsWith("/mcp/list")) {
      body = {
        status: "success",
        remote_mcp_server_list: [
          {
            mcp_id: 101,
            remote_mcp_server_name: "First MCP",
            remote_mcp_server: "https://first.example/mcp",
            enabled: false,
            permission: "EDIT",
            source: "self",
            tags: [],
          },
          {
            mcp_id: 202,
            remote_mcp_server_name: "Second MCP",
            remote_mcp_server: "https://second.example/mcp",
            enabled: false,
            permission: "EDIT",
            source: "self",
            tags: [],
          },
        ],
      };
    } else if (url.pathname.endsWith("/mcp-tools/community/mine")) {
      body = { status: "success", data: { count: 0, items: [] } };
    } else if (url.pathname.endsWith("/mcp/healthcheck")) {
      const id = url.searchParams.get("mcp_id");
      body = { status: id === "101" && firstCheck ? "success" : "error" };
      if (id === "101") firstCheck = false;
    } else if (url.pathname.endsWith("/groups/list")) {
      body = { data: [] };
    } else if (url.pathname.endsWith("/tag-libraries")) {
      body = [];
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });

  await page.goto("http://localhost:3000/zh/mcp-space?tab=mine");
  const firstCard = page
    .getByRole("heading", { name: "First MCP" })
    .locator("xpath=ancestor::div[contains(@class, 'group')][1]");
  const secondCard = page
    .getByRole("heading", { name: "Second MCP" })
    .locator("xpath=ancestor::div[contains(@class, 'group')][1]");

  await expect(page.getByRole("heading", { name: "First MCP" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Second MCP" })).toBeVisible();
  await expect(firstCard.getByText("未连接", { exact: true })).toBeVisible();
  await expect(secondCard.getByText("未连接", { exact: true })).toBeVisible();
  await expect(
    firstCard
      .getByText("未连接", { exact: true })
      .locator("span[aria-hidden='true']")
  ).toHaveClass(/bg-slate-400/);

  await firstCard.getByRole("button", { name: "连通性校验" }).click();
  await expect(firstCard.getByText("连接成功", { exact: true })).toBeVisible();
  await expect(
    firstCard
      .getByText("连接成功", { exact: true })
      .locator("span[aria-hidden='true']")
  ).toHaveClass(/bg-green-500/);
  await expect(secondCard.getByText("未连接", { exact: true })).toBeVisible();

  await firstCard.getByRole("button", { name: "连通性校验" }).click();
  await expect(firstCard.getByText("连接失败", { exact: true })).toBeVisible();
  await expect(
    firstCard
      .getByText("连接失败", { exact: true })
      .locator("span[aria-hidden='true']")
  ).toHaveClass(/bg-red-500/);

  await secondCard.getByRole("button", { name: "连通性校验" }).click();
  await expect(secondCard.getByText("连接失败", { exact: true })).toBeVisible();

  await page.reload();
  await expect(firstCard.getByText("未连接", { exact: true })).toBeVisible();
  await expect(secondCard.getByText("未连接", { exact: true })).toBeVisible();
});
