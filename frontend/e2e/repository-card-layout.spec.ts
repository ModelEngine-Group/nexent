// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, test, type Page, type Route } from "@playwright/test";

const baseUrl = process.env.NEXENT_E2E_BASE_URL ?? "http://localhost:3000";
type ResourceKind = "agent" | "skill" | "mcp";
type ListingRequest = { size: number; page: number };
const json = (route: Route, data: unknown) =>
  route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(data),
  });

async function mockRepository(page: Page, kind: ResourceKind) {
  const requests: ListingRequest[] = [];
  const writes: string[] = [];
  const endpoint =
    kind === "mcp" ? "/mcp-tools/community/list" : `/repository/${kind}`;
  const items = Array.from({ length: 14 }, (_, index) => ({
    agent_repository_id: index + 1,
    skill_repository_id: index + 1,
    agent_id: index + 1,
    communityId: index + 1,
    name: `Layout ${kind} ${index + 1} ${"LongName".repeat(8)}`,
    display_name: `Layout ${kind} ${index + 1} ${"LongName".repeat(8)}`,
    author: `${"long-author-".repeat(10)}@example.test`,
    authorDisplayName: `${"long-author-".repeat(10)}@example.test`,
    description: "Description ".repeat(50),
    tags: ["tag".repeat(40), "database"],
    version_label: "version".repeat(40),
    is_main_agent: true,
    status: kind === "mcp" ? "active" : "shared",
    transportType: "sse",
    deploymentType: "remote",
    remotes: [],
    packages: [],
  }));
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^.*\/api/, "");
    if (
      !["GET", "HEAD"].includes(route.request().method()) &&
      path !== "/groups/list"
    )
      writes.push(`${route.request().method()} ${path}`);
    if (path === "/tenant_config/deployment_version")
      return json(route, {
        deployment_version: "speed",
        app_version: "test",
        status: "success",
      });
    if (path === "/user/current_user_info")
      return json(route, {
        data: {
          user: {
            user_id: "layout-test",
            tenant_id: "layout-test",
            user_email: "layout@test",
            user_role: "SPEED",
            auth_provider: "local",
            group_ids: [],
            permissions: [],
            accessibleRoutes: ["/agent-space", "/skill-space", "/mcp-space"],
          },
        },
      });
    if (path === "/tag-libraries") return json(route, []);
    if (path === "/groups/list")
      return json(route, { data: [], total: 0, message: "ok" });
    if (path === endpoint) {
      const size = Number(
        url.searchParams.get(kind === "mcp" ? "limit" : "page_size")
      );
      const currentPage = Number(url.searchParams.get("page") ?? 1);
      // Tab counters request one item separately from the visible listing.
      if (size !== 1) requests.push({ size, page: currentPage });
      const pageItems = items.slice(
        (currentPage - 1) * size,
        currentPage * size
      );
      if (kind === "mcp") {
        // Exercise the uncached-page transition that previously reset the page.
        if (currentPage > 1)
          await new Promise((resolve) => setTimeout(resolve, 150));
        return json(route, {
          status: "success",
          data: {
            items: pageItems,
            total: items.length,
            nextCursor: null,
          },
        });
      }
      return json(route, {
        items: pageItems,
        pagination: {
          page: currentPage,
          page_size: size,
          total: items.length,
          total_pages: Math.ceil(items.length / size),
        },
      });
    }
    if (path.includes("tags/stats"))
      return json(route, { status: "success", data: [] });
    if (path.includes("mcp"))
      return json(route, {
        status: "success",
        data: { items: [], services: [], total: 0 },
      });
    if (path.includes("mine") || path.includes("/agent/list"))
      return json(route, {
        items: [],
        pagination: { page: 1, page_size: 12, total: 0, total_pages: 0 },
      });
    return json(route, {});
  });
  return { requests, writes };
}

for (const kind of ["agent", "skill", "mcp"] as const) {
  test(`${kind} repository keeps twelve cards, contains long text and scrolls to page two`, async ({
    page,
  }) => {
    test.setTimeout(90_000);
    const fixture = await mockRepository(page, kind);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${baseUrl}/zh/${kind}-space`);
    const headings = page
      .getByRole("heading", { level: 2 })
      .filter({ hasText: `Layout ${kind}` });
    await expect(headings).toHaveCount(12);
    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 1024, height: 480 },
    ]) {
      await page.setViewportSize(viewport);
      await expect(headings).toHaveCount(12);
      await expect
        .poll(() =>
          headings.evaluateAll((nodes) =>
            nodes.flatMap((heading) => {
              const card = heading.closest(".group")!;
              const box = card.getBoundingClientRect();
              return [...card.querySelectorAll("span,button")]
                .filter((element) => {
                  const bounds = element.getBoundingClientRect();
                  return (
                    bounds.width > 0 &&
                    bounds.height > 0 &&
                    (bounds.bottom > box.bottom + 1 ||
                      bounds.right > box.right + 1 ||
                      bounds.left < box.left - 1)
                  );
                })
                .map((element) => element.textContent);
            })
          )
        )
        .toEqual([]);
    }
    const pagination = page.locator(".ant-pagination-item-2").last();
    await expect(pagination).not.toBeInViewport();
    await pagination.scrollIntoViewIfNeeded();
    await expect(pagination).toBeInViewport();
    await pagination.click();
    await expect(headings.first()).toContainText(`Layout ${kind} 13`);
    await expect(headings).toHaveCount(2);
    expect(fixture.requests.length).toBeGreaterThanOrEqual(2);
    expect(fixture.requests.every((request) => request.size === 12)).toBe(true);
    expect(fixture.requests.some((request) => request.page === 2)).toBe(true);
    expect(fixture.writes).toEqual([]);
  });
}
