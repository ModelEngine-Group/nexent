import { expect, test } from "@playwright/test";

test("shows the pending review count before opening Review Center", async ({
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
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    let body: unknown = {};

    if (url.pathname.endsWith("/user/current_user_info")) {
      body = {
        data: {
          user: {
            user_id: "review-test-admin",
            tenant_id: "review-test-tenant",
            user_email: "admin@nexent.test",
            user_role: "ADMIN",
            auth_provider: "local",
            group_ids: [],
            permissions: [],
            accessibleRoutes: ["/agent-space"],
          },
        },
      };
    } else if (url.pathname.endsWith("/repository/agent")) {
      body = {
        items: [],
        pagination: {
          page: 1,
          page_size: 1,
          total: url.searchParams.get("status") === "pending_review" ? 2 : 0,
        },
      };
    } else if (url.pathname.endsWith("/tag-libraries")) {
      body = [];
    } else if (url.pathname.endsWith("/agent/list/page")) {
      body = {
        items: [],
        pagination: { page: 1, page_size: 1, total: 0, total_pages: 0 },
      };
    } else if (url.pathname.endsWith("/groups/list")) {
      body = { data: [] };
    }

    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });

  await page.goto("http://localhost:3000/en/agent-space");

  await expect(page.getByRole("tab", { name: /Repository/ })).toHaveAttribute(
    "data-state",
    "active"
  );
  await expect(page.getByRole("tab", { name: /Review Center/ })).toContainText(
    "2"
  );
});
