import { expect, test, type Page, type Route } from "@playwright/test";

const baseUrl = process.env.NEXENT_E2E_BASE_URL ?? "http://127.0.0.1:3000";

const agents = Array.from({ length: 8 }, (_, index) => ({
  agent_id: index + 1,
  name: `health_agent_${index + 1}`,
  display_name: index === 0 ? "健康小助手" : `智能体${index + 1}`,
  description:
    "一个专业、全面的健康咨询智能体，致力于为用户提供可靠、实用的健康信息。",
  tags: index === 0 ? ["医疗"] : [],
  author: index === 0 ? "刘晨" : undefined,
  create_time: "2026-01-23T12:00:00",
  update_time: index === 1 ? "2026-02-04T09:30:00" : undefined,
  current_version_no: null,
  permission: "EDIT",
}));

const json = (route: Route, body: unknown) =>
  route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });

async function mockAgentListApis(page: Page, listItems = agents) {
  await page.route("**/api/**", (route) => json(route, {}));
  await page.route("**/api/tenant_config/deployment_version", (route) =>
    json(route, {
      deployment_version: "speed",
      app_version: "test",
      status: "success",
    })
  );
  await page.route("**/api/user/current_user_info", (route) =>
    json(route, {
      data: {
        user: {
          user_id: "agent-list-test-user",
          tenant_id: "agent-list-test-tenant",
          user_email: "agent-list@nexent.test",
          user_role: "SPEED",
          auth_provider: "local",
          group_ids: [],
          permissions: [],
          accessibleRoutes: ["/agents"],
        },
      },
    })
  );
  await page.route("**/api/groups/list", (route) =>
    json(route, { data: [], total: 0, message: "ok" })
  );
  await page.route("**/api/agent/list/page?*", (route) => {
    const query = new URL(route.request().url()).searchParams;
    const search = query.get("search")?.trim();
    const matchingItems = search
      ? listItems.filter((agent) => agent.display_name.includes(search))
      : listItems;
    const pageNumber = Number(query.get("page") ?? 1);
    const pageSize = Number(query.get("page_size") ?? 10);
    const items = matchingItems.slice(
      (pageNumber - 1) * pageSize,
      pageNumber * pageSize
    );
    return json(route, {
      items,
      pagination: {
        page: pageNumber,
        page_size: pageSize,
        total: matchingItems.length,
        total_pages: Math.ceil(matchingItems.length / pageSize),
      },
    });
  });
}

test("agent list matches the measured desktop card layout and keeps controls functional", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await mockAgentListApis(page);
  await page.goto(`${baseUrl}/zh/agents`);

  await expect(page.getByRole("heading", { name: "智能体开发" })).toBeVisible();
  await expect(page.locator("article")).toHaveCount(8);
  await expect(page.getByText("我创建的智能体")).toBeVisible();
  await expect(page.getByText("创建于2026-01-23").first()).toBeVisible();
  await expect(page.getByText("总计：8")).toBeVisible();
  await expect(page.getByText("10条/页")).toBeVisible();

  const guide = await page.getByTestId("agent-guide-background").boundingBox();
  const tabs = await page.getByTestId("agent-list-tabs").boundingBox();
  expect(guide?.width).toBe(1808);
  expect(guide?.height).toBe(353);
  expect(tabs?.y).toBe(guide!.y + guide!.height + 12);
  await expect(page.getByTestId("agent-guide-divider")).toHaveCount(0);

  const firstCard = page.locator("article").first();
  await expect(firstCard).toHaveCSS("border-radius", "12px");
  await expect(firstCard).toHaveCSS("padding", "16px 24px");
  await expect(firstCard.getByText("健康小助手")).toHaveCSS(
    "font-size",
    "16px"
  );
  await expect(firstCard.getByText("健康小助手")).toHaveCSS(
    "line-height",
    "24px"
  );
  await expect(firstCard.getByText("健康小助手")).toHaveCSS(
    "font-weight",
    "500"
  );
  await expect(firstCard.getByText("医疗")).toHaveCSS("height", "22px");
  await expect(firstCard.locator("p")).toHaveCSS("font-size", "12px");
  await expect(firstCard.locator("p")).toHaveCSS("line-height", "20px");
  await expect(firstCard.locator("p")).toHaveCSS("color", "rgb(119, 119, 119)");

  const first = await page.locator("article").nth(0).boundingBox();
  const second = await page.locator("article").nth(1).boundingBox();
  const fifth = await page.locator("article").nth(4).boundingBox();
  const search = await page
    .getByPlaceholder("按名称或描述搜索")
    .locator("..")
    .boundingBox();
  expect(first).not.toBeNull();
  expect(second).not.toBeNull();
  expect(fifth).not.toBeNull();
  expect(search).not.toBeNull();
  expect(first!.width).toBeCloseTo(440, 0);
  expect(first!.height).toBe(148);
  expect(second!.x - first!.x - first!.width).toBeCloseTo(16, 0);
  expect(fifth!.y - first!.y - first!.height).toBeCloseTo(12, 0);
  expect(search!.width).toBeCloseTo(360, 0);
  expect(search!.height).toBeCloseTo(32, 0);

  await page.screenshot({
    path: test.info().outputPath("agent-list-desktop.png"),
    fullPage: true,
  });

  await firstCard.hover();
  await expect(firstCard.getByRole("button", { name: "配置" })).toBeVisible();
  await expect(firstCard.getByRole("button", { name: "发布" })).toBeVisible();

  await page.getByRole("button", { name: "列表视图" }).click();
  const table = page.getByRole("table");
  await expect(table).toBeVisible();
  await expect(page.locator(".nexent-standard-table")).toBeVisible();
  await expect(page.locator(".nexent-standard-table .ant-table")).toHaveCSS(
    "background-color",
    "rgb(255, 255, 255)"
  );
  await expect(table.getByRole("columnheader").first()).toHaveCSS(
    "background-color",
    "rgb(243, 243, 243)"
  );
  await expect(table.getByRole("columnheader").first()).toHaveCSS(
    "height",
    "40px"
  );
  await expect(table.getByRole("columnheader").nth(1)).toHaveCSS(
    "padding-left",
    "8px"
  );
  const headerCells = await table.getByRole("columnheader").all();
  for (const header of headerCells.slice(0, -1)) {
    const separator = await header.evaluate((element) => {
      const style = window.getComputedStyle(element, "::before");
      const translationY = Number(
        style.transform.match(
          /matrix\([^,]+,[^,]+,[^,]+,[^,]+,[^,]+,([^)]+)\)/
        )?.[1] ?? 0
      );
      const independentTranslation = style.translate.match(/([-\d.]+)(px|%)$/);
      const independentTranslationY = independentTranslation
        ? independentTranslation[2] === "%"
          ? (Number.parseFloat(independentTranslation[1] ?? "0") / 100) *
            Number.parseFloat(style.height)
          : Number.parseFloat(independentTranslation[1] ?? "0")
        : 0;
      const separatorCenter =
        Number.parseFloat(style.top) +
        translationY +
        independentTranslationY +
        Number.parseFloat(style.height) / 2;
      return {
        height: style.height,
        width: style.width,
        top: style.top,
        transform: style.transform,
        translate: style.translate,
        cellHeight: element.getBoundingClientRect().height,
        centerOffset: Math.abs(
          separatorCenter - element.getBoundingClientRect().height / 2
        ),
        color: style.backgroundColor,
        content: style.content,
      };
    });
    expect(separator).toEqual({
      height: "14px",
      width: "1px",
      top: expect.any(String),
      transform: expect.any(String),
      translate: expect.any(String),
      cellHeight: expect.any(Number),
      centerOffset: expect.any(Number),
      color: "rgb(201, 201, 201)",
      content: '""',
    });
    expect(
      separator.centerOffset,
      JSON.stringify(separator)
    ).toBeLessThanOrEqual(1);
  }
  const finalHeaderSeparator = await headerCells[
    headerCells.length - 1
  ]!.evaluate(
    (element) => window.getComputedStyle(element, "::before").content
  );
  expect(finalHeaderSeparator).toBe("none");
  await expect(
    table.getByRole("columnheader").nth(1).locator("svg")
  ).toBeVisible();
  await expect(
    table.getByRole("columnheader").nth(5).locator("svg")
  ).toBeVisible();
  await expect(table.getByRole("columnheader")).toHaveText([
    "名称",
    "类型",
    "描述",
    "状态",
    "创建人",
    "更新时间",
    "操作",
  ]);
  await expect(table.locator("tbody tr")).toHaveCount(8);
  await expect(table.locator("tbody tr").nth(0)).toContainText("刘晨");
  await expect(table.locator("tbody tr").nth(0)).toContainText("-");
  await expect(table.locator("tbody tr").nth(1)).toContainText("2026-02-04");
  await expect(
    table.locator("tbody tr").first().locator("td").first()
  ).toHaveCSS("height", "40px");
  await expect(
    table.locator("tbody tr").first().locator("td").first()
  ).toHaveCSS("border-bottom-color", "rgb(240, 240, 240)");

  const tableBody = await page
    .getByTestId("agent-list-table-scroll")
    .boundingBox();
  const tableContent = await table.boundingBox();
  const tableSearch = await page
    .getByPlaceholder("按名称或描述搜索")
    .locator("..")
    .boundingBox();
  expect(tableBody?.width).toBeCloseTo(1808, 0);
  expect(tableBody?.height).toBeGreaterThan(300);
  expect(tableBody?.height).toBeLessThan(400);
  expect(tableBody?.height).toBeLessThanOrEqual(500);
  expect(
    Math.abs((tableBody?.height ?? 0) - (tableContent?.height ?? 0))
  ).toBeLessThanOrEqual(2);
  expect(tableSearch?.width).toBeCloseTo(296, 0);
  await expect(
    table.getByRole("button", { name: "删除" }).first()
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("agent-list-table-desktop.png"),
    fullPage: true,
  });

  await page.getByPlaceholder("按名称或描述搜索").fill("健康小助手");
  await expect(table.locator("tbody tr")).toHaveCount(1);
  const filteredTableBody = await page
    .getByTestId("agent-list-table-scroll")
    .boundingBox();
  expect(filteredTableBody?.height).toBeLessThan(tableBody!.height);
  await page.getByRole("button", { name: "新建智能体" }).click();
  await expect(page.getByText("从模板创建")).toBeVisible();
});

test("table row shortcuts preserve configure and publish navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await mockAgentListApis(page);
  await page.goto(`${baseUrl}/zh/agents`);
  await page.getByRole("button", { name: "列表视图" }).click();

  const firstRow = page.getByRole("table").locator("tbody tr").first();
  await firstRow.getByRole("button", { name: "配置" }).click();
  await expect(page).toHaveURL(/\/zh\/agents\/1$/);

  await page.goto(`${baseUrl}/zh/agents`);
  await page.getByRole("button", { name: "列表视图" }).click();
  const firstLoadedRow = page.getByRole("table").locator("tbody tr").first();
  await firstLoadedRow.getByRole("button", { name: "发布" }).click();
  await expect(page).toHaveURL(/\/zh\/agents\/1\?publish=1$/);
});

test("table body follows rendered content, caps available height, and scrolls internally", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 1400 });
  const manyAgents = Array.from({ length: 20 }, (_, index) => ({
    ...agents[index % agents.length],
    agent_id: index + 1,
    id: String(index + 1),
    name: `health_agent_${index + 1}`,
    display_name: `健康智能体${index + 1}`,
  }));
  await mockAgentListApis(page, manyAgents);
  await page.goto(`${baseUrl}/zh/agents`);
  await page.getByRole("button", { name: "列表视图" }).click();

  const table = page.getByRole("table");
  await page.getByRole("combobox", { name: "每页条数" }).click();
  await page.getByText("20条/页").click();
  await expect(table.locator("tbody tr")).toHaveCount(20);

  const scrollArea = page.getByTestId("agent-list-table-scroll");
  await expect(scrollArea).toHaveCSS("max-height", "500px");
  const dimensions = await scrollArea.evaluate((element) => ({
    height: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }));
  expect(dimensions.height).toBe(500);
  expect(dimensions.scrollHeight).toBeGreaterThan(dimensions.height);

  await scrollArea.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  expect(
    await scrollArea.evaluate((element) => element.scrollTop)
  ).toBeGreaterThan(0);
  await expect(page.getByText("总计：20")).toBeVisible();

  await page.setViewportSize({ width: 1920, height: 700 });
  const shortViewportBody = await scrollArea.boundingBox();
  expect(shortViewportBody?.height).toBeGreaterThan(0);
  expect(shortViewportBody?.height).toBeLessThan(500);
  const shortViewportDimensions = await scrollArea.evaluate((element) => ({
    height: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }));
  expect(shortViewportDimensions.scrollHeight).toBeGreaterThan(
    shortViewportDimensions.height
  );
});

test("the guide divider is shown only when the agent list is empty", async ({
  page,
}) => {
  await mockAgentListApis(page, []);
  await page.goto(`${baseUrl}/zh/agents`);

  await expect(page.getByText("暂无智能体，请创建")).toBeVisible();
  await expect(page.getByTestId("agent-guide-divider")).toBeVisible();

  const guide = await page.getByTestId("agent-guide-background").boundingBox();
  expect(guide?.height).toBe(378);
});

test("publish shortcut routes to the existing configuration flow", async ({
  page,
}) => {
  await mockAgentListApis(page);
  await page.goto(`${baseUrl}/zh/agents`);
  const card = page.locator("article").first();
  await expect(card).toBeVisible();
  await card.hover();
  await card.getByRole("button", { name: "发布" }).click();
  await expect(page).toHaveURL(/\/zh\/agents\/1\?publish=1$/);
});

test("the list reflows without horizontal overflow at tablet width", async ({
  page,
}) => {
  await page.setViewportSize({ width: 768, height: 900 });
  await mockAgentListApis(page);
  await page.goto(`${baseUrl}/zh/agents`);
  await expect(page.locator("article")).toHaveCount(8);

  const first = await page.locator("article").nth(0).boundingBox();
  const second = await page.locator("article").nth(1).boundingBox();
  const third = await page.locator("article").nth(2).boundingBox();
  expect(first?.y).toBe(second?.y);
  expect(third?.x).toBe(first?.x);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth)
  ).toBeLessThanOrEqual(768);
});
