// @ts-nocheck
import fs from "node:fs";
import path from "node:path";
import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
const scenarios: Array<{ name: string; run: (fixture: any) => Promise<void> }> = [];
const scenario = (name: string, run: (fixture: any) => Promise<void>) => scenarios.push({ name, run });

const repositoryRoot = process.env.NEXENT_REPO;
const baseUrl = process.env.NEXENT_BASE_URL ?? "http://localhost:3000";
const translations = Object.fromEntries(
  ["zh", "en"].map((locale) => [
    locale,
    JSON.parse(
      fs.readFileSync(
        path.join(
          repositoryRoot,
          `frontend/public/locales/${locale}/common.json`,
        ),
        "utf8",
      ),
    ),
  ]),
);
const label = (locale, key) => {
  const value = translations[locale][key];
  if (typeof value !== "string")
    throw new Error(`Missing ${locale} test label: ${key}`);
  return value;
};

function agentRows(count = 8) {
  return Array.from({ length: count }, (_, index) => ({
    agent_id: index + 1,
    name: index === 2 ? "fallback_agent" : `health_agent_${index + 1}`,
    display_name:
      index === 0 ? "健康小助手" : index === 2 ? null : `智能体${index + 1}`,
    description:
      index === 2
        ? ""
        : "一个专业、全面的健康咨询智能体，提供可靠、实用的健康信息。",
    tags: index === 0 ? ["医疗"] : [],
    author: index === 0 ? "刘晨" : undefined,
    create_time: index === 2 ? null : "2026-01-23T12:00:00",
    update_time: index === 0 ? "2026-02-04T09:30:00" : null,
    current_version_no: index === 0 ? 2 : null,
    permission: index === 1 ? "READ_ONLY" : "EDIT",
  }));
}

async function mockList(page, rows = agentRows()) {
  const fixture = { rows, requests: [], writes: [], providerCalls: [] };
  // These existing read endpoints use POST to carry lookup parameters.
  const readOnlyPostPaths = new Set([
    "/api/agent/search_info",
    "/api/groups/list",
  ]);
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) return;
    fixture.requests.push({
      method: request.method(),
      pathname: url.pathname,
      query: url.search,
    });
    if (
      request.method() !== "GET" &&
      !(request.method() === "POST" && readOnlyPostPaths.has(url.pathname))
    )
      fixture.writes.push(url.pathname);
    if (
      /\/agent\/(run|nl2agent\/run)|\/skills\/nl2skill\/run/.test(url.pathname)
    )
      fixture.providerCalls.push(url.pathname);
  });
  const json = (route, data) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(data),
    });
  await page.route("**/api/**", (route) => json(route, {}));
  await page.route("**/api/tenant_config/deployment_version", (route) =>
    json(route, {
      deployment_version: "speed",
      app_version: "test",
      status: "success",
    }),
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
    }),
  );
  await page.route("**/api/groups/list", (route) =>
    json(route, { data: [], total: 0, message: "ok" }),
  );
  await page.route("**/api/agent/search_info", (route) => {
    const { agent_id } = route.request().postDataJSON();
    const agent = fixture.rows.find((row) => row.agent_id === agent_id);
    return json(route, {
      ...agent,
      max_steps: 10,
      tools: [],
      skills: [],
      model_ids: [],
      enabled: true,
      provide_run_summary: false,
    });
  });
  await page.route("**/api/agent/list/page?*", (route) => {
    const query = new URL(route.request().url()).searchParams;
    const search = query.get("search")?.trim() ?? "";
    const matching = fixture.rows.filter((agent) =>
      `${agent.display_name ?? agent.name} ${agent.description}`.includes(
        search,
      ),
    );
    const current = Number(query.get("page") ?? 1);
    const size = Number(query.get("page_size") ?? 10);
    return json(route, {
      items: matching.slice((current - 1) * size, current * size),
      pagination: {
        page: current,
        page_size: size,
        total: matching.length,
        total_pages: Math.ceil(matching.length / size),
      },
    });
  });
  return fixture;
}

async function bounds(locator) {
  await expect(locator).toBeVisible();
  const result = await locator.boundingBox();
  expect(result).not.toBeNull();
  return result;
}

function pixel(actual, expected, name) {
  expect(Math.abs(actual - expected), name).toBeLessThanOrEqual(1);
}

async function typography(locator, size, lineHeight, weight, color) {
  await expect(locator).toHaveCSS("font-size", `${size}px`);
  await expect(locator).toHaveCSS("line-height", `${lineHeight}px`);
  await expect(locator).toHaveCSS("font-weight", String(weight));
  await expect(locator).toHaveCSS("color", color);
  await expect(locator).toHaveCSS("letter-spacing", /^(0px|normal)$/);
}

function noPresentationMutation(fixture) {
  expect(
    fixture.writes,
    "presentation-only actions must not write to the API",
  ).toEqual([]);
  expect(
    fixture.providerCalls,
    "presentation-only actions must not execute an Agent/provider",
  ).toEqual([]);
}

scenario("[AGENT-LIST-D4-002] measured desktop guide/card geometry and complete list journey", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  const fixture = await mockList(page);
  await page.goto(`${baseUrl}/zh/agents`);
  await expect(page.locator("article")).toHaveCount(8);
  const header = page.locator("header");
  const headerBox = await bounds(header);
  pixel(headerBox.width, 1808, "header width");
  pixel(headerBox.height, 48, "header height");
  const content = header.locator("..");
  const contentBox = await bounds(content);
  pixel(contentBox.width, 1856, "content width");
  await expect(content).toHaveCSS("padding", "24px");
  const toggle = header.getByRole("button");
  await expect(toggle).toHaveText("收起教程");
  const toggleBox = await bounds(toggle);
  pixel(toggleBox.width, 72, "tutorial toggle width");
  pixel(toggleBox.height, 22, "tutorial toggle height");
  pixel(toggleBox.x - headerBox.x, 1736, "tutorial toggle header left");
  pixel(toggleBox.y - headerBox.y, 13, "tutorial toggle header top");
  await typography(toggle, 14, 22, 400, "rgb(25, 25, 25)");
  await expect(toggle).toHaveCSS("gap", "6px");
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(toggle).toHaveAttribute(
    "aria-controls",
    "agent-configuration-guide",
  );
  expect(
    await toggle.evaluate((element) =>
      element.children[0].tagName.toLowerCase(),
    ),
  ).toBe("span");
  const arrowBox = await bounds(toggle.locator("svg"));
  pixel(arrowBox.width, 8, "tutorial arrow width");
  pixel(arrowBox.height, 8, "tutorial arrow height");
  pixel(
    (await bounds(toggle.locator("span"))).width,
    56,
    "tutorial text width",
  );

  const guide = page.getByTestId("agent-guide-background");
  const guideBox = await bounds(guide);
  pixel(guideBox.width, 1808, "guide width");
  pixel(guideBox.height, 378, "populated guide height");
  await expect(guide).toHaveCSS("padding", "24px");
  await expect(guide).toHaveCSS("border-radius", "16px");
  pixel(
    (await bounds(guide.locator(":scope > div"))).height,
    330,
    "guide inner height",
  );
  await expect(guide.getByRole("button")).toHaveCount(0);

  const introduction = page.getByTestId("agent-guide-introduction");
  const process = page.getByTestId("agent-guide-process");
  const introBox = await bounds(introduction);
  const processBox = await bounds(process);
  pixel(introBox.width, 1760, "guide inner width");
  pixel(introBox.height, 114, "introduction height");
  pixel(processBox.height, 192, "process height");
  pixel(
    processBox.y - introBox.y - introBox.height,
    24,
    "introduction/process gap",
  );
  await typography(introduction.locator("h2"), 16, 24, 500, "rgb(25, 25, 25)");
  pixel(
    (await bounds(introduction.locator("h2 span"))).x - introBox.x,
    24,
    "introduction text left",
  );
  pixel(
    (await bounds(introduction.locator("h2 svg"))).width,
    16,
    "introduction icon width",
  );
  await expect(introduction.locator("h2")).toHaveCSS("gap", "8px");
  await typography(introduction.locator("p"), 14, 22, 400, "rgb(25, 25, 25)");
  pixel(
    (await bounds(introduction.locator("p"))).y - introBox.y,
    36,
    "introduction body top",
  );
  const pointsBox = await bounds(introduction.locator("ol"));
  pixel(pointsBox.y - introBox.y, 70, "introduction points top");
  pixel(pointsBox.height, 44, "introduction points height");
  await typography(
    introduction.locator("ol"),
    14,
    22,
    400,
    "rgb(119, 119, 119)",
  );
  pixel(
    (await bounds(process.locator("h2"))).height,
    24,
    "process title height",
  );
  const steps = page.getByTestId("agent-guide-step");
  await expect(steps).toHaveCount(5);
  const stepBox = await bounds(steps.first());
  pixel(stepBox.width, 339.2, "step width");
  pixel(stepBox.height, 156, "step height");
  pixel(stepBox.y - processBox.y, 36, "process title/step gap");
  pixel(
    (await bounds(steps.nth(1))).x - stepBox.x - stepBox.width,
    16,
    "step horizontal gap",
  );
  const stepTitle = steps.first().locator("h3");
  const stepDescription = steps.first().locator("p");
  const stepTitleBox = await bounds(stepTitle);
  const stepDescriptionBox = await bounds(stepDescription);
  await typography(stepTitle, 18, 26, 500, "rgb(25, 25, 25)");
  await typography(stepDescription, 14, 22, 400, "rgb(119, 119, 119)");
  pixel(stepTitleBox.y - stepBox.y, 24, "step title top");
  pixel(stepTitleBox.x - stepBox.x, 21.09, "step title left");
  pixel(stepDescriptionBox.y - stepBox.y, 66, "step description top");
  pixel(stepDescriptionBox.width, 297.02, "step description width");
  pixel(
    stepDescriptionBox.y - stepTitleBox.y - stepTitleBox.height,
    16,
    "step title/description gap",
  );

  const cards = page.locator("article");
  const first = cards.first();
  const cardBox = await bounds(first);
  const secondBox = await bounds(cards.nth(1));
  const fifthBox = await bounds(cards.nth(4));
  pixel(cardBox.width, 440, "card width");
  pixel(cardBox.height, 148, "card height");
  const scrollport = page.getByTestId("agent-list-content");
  const scrollportBox = await bounds(scrollport);
  await expect(scrollport).toHaveCSS("overflow-y", "auto");
  const rightmostCardBox = await bounds(cards.nth(3));
  expect(
    cardBox.y - scrollportBox.y,
    "outside stroke has at least 1px of paint space above the first row",
  ).toBeGreaterThanOrEqual(1);
  expect(
    cardBox.x - scrollportBox.x,
    "outside stroke has at least 1px of paint space left of the first column",
  ).toBeGreaterThanOrEqual(1);
  expect(
    scrollportBox.x +
      scrollportBox.width -
      rightmostCardBox.x -
      rightmostCardBox.width,
    "outside stroke has at least 1px of paint space right of the last column",
  ).toBeGreaterThanOrEqual(1);
  pixel(secondBox.x - cardBox.x - cardBox.width, 16, "card horizontal gap");
  pixel(fifthBox.y - cardBox.y - cardBox.height, 12, "card vertical gap");
  expect((await bounds(cards.nth(3))).y).toBe(cardBox.y);
  await expect(first).toHaveCSS("padding", "16px 24px");
  await expect(first).toHaveCSS("border-radius", "12px");
  await expect(first).toHaveCSS("border-top-width", "0px");
  expect(
    await first.evaluate((element) => getComputedStyle(element).boxShadow),
  ).toContain("rgba(201, 201, 201, 0.4)");
  const body = first.getByTestId("agent-card-body");
  const bodyBox = await bounds(body);
  pixel(bodyBox.width, 392, "card inner width");
  pixel(bodyBox.height, 86, "card body height");
  pixel(bodyBox.x - cardBox.x, 24, "card horizontal padding");
  pixel(bodyBox.y - cardBox.y, 16, "card vertical padding");
  const title = first.getByText("健康小助手", { exact: true });
  const description = body.locator("p");
  await typography(title, 16, 24, 500, "rgb(25, 25, 25)");
  await typography(description, 12, 20, 400, "rgb(119, 119, 119)");
  const expectedFontFamily =
    '"HarmonyOS Sans SC", "Huawei Sans", system-ui, sans-serif';
  for (const text of [title, description, toggle])
    await expect(text).toHaveCSS("font-family", expectedFontFamily);
  await expect(
    page.getByRole("button", {
      name: label("zh", "agentConfig.list.new"),
      exact: true,
    }),
  ).toHaveCSS("font-family", expectedFontFamily);
  pixel((await bounds(description)).height, 42, "card description text bounds");
  pixel(
    (await bounds(description)).y -
      (await bounds(body.locator(":scope > div"))).y -
      40,
    4,
    "card header/description gap",
  );
  const footer = first.getByTestId("agent-card-footer");
  const footerBox = await bounds(footer);
  pixel(footerBox.height, 18, "card footer height");
  pixel(footerBox.y - bodyBox.y, 98, "card footer inner top");
  pixel(
    footerBox.y - bodyBox.y - bodyBox.height,
    12,
    "derived body/footer gap",
  );
  const status = first.getByTestId("agent-card-status");
  const statusBox = await bounds(status);
  pixel(statusBox.width, 48, "status width");
  pixel(statusBox.height, 18, "status height");
  pixel(statusBox.x - bodyBox.x, 197, "left-aligned status position");
  const dateBox = await bounds(footer.locator(":scope > span").first());
  pixel(statusBox.x - dateBox.x - dateBox.width, 78, "date/status gap");
  await expect(status).toHaveText("已上线");
  const dot = first.getByTestId("agent-card-status-dot");
  const dotBox = await bounds(dot);
  pixel(dotBox.width, 8, "status dot width");
  pixel(dotBox.height, 8, "status dot height");
  await expect(dot).toHaveAttribute("aria-hidden", "true");
  await expect(status).toHaveCSS("gap", "4px");
  await expect(first.getByText("更新于2026-02-04")).toBeVisible();
  await expect(cards.nth(1).getByText("创建于2026-01-23")).toBeVisible();
  await expect(cards.nth(1).getByTestId("agent-card-status")).toHaveText(
    "未上线",
  );
  await expect(cards.nth(2).getByText("-")).toBeVisible();
  await expect(
    cards.nth(2).getByText(label("zh", "agentRepository.card.noDescription")),
  ).toBeVisible();
  const more = first.getByRole("button", {
    name: label("zh", "agentRepository.mine.menu.more"),
  });
  const moreGlyph = more.locator("svg");
  const moreBox = await bounds(moreGlyph);
  pixel(moreBox.width, 12, "more glyph width");
  pixel(moreBox.height, 12, "more glyph height");
  pixel(moreBox.y - cardBox.y, 16, "more glyph top");
  pixel(
    cardBox.x + cardBox.width - moreBox.x - moreBox.width,
    24,
    "more glyph right",
  );
  await expect(moreGlyph).toHaveCSS("color", "rgb(25, 25, 25)");
  await expect(
    page.getByRole("button", {
      name: label("zh", "agentConfig.list.imported"),
      exact: true,
    }),
  ).toBeDisabled();
  await expect(page.getByTestId("agent-guide-divider")).toHaveCount(0);

  await first.hover();
  await expect(
    first.getByRole("button", { name: "配置", exact: true }),
  ).toBeVisible();
  await expect(
    first.getByRole("button", { name: "发布", exact: true }),
  ).toBeVisible();
  await expect(status).toBeHidden();
  await more.click();
  await expect(page.getByRole("menu")).toBeVisible();
  await header.getByRole("heading").click();
  await body.focus();
  await expect(
    first.getByRole("button", { name: "配置", exact: true }),
  ).toBeVisible();
  await expect(
    first.getByRole("button", { name: "发布", exact: true }),
  ).toBeVisible();
  await cards.nth(1).hover();
  await expect(
    cards.nth(1).getByRole("button", { name: "发布", exact: true }),
  ).toBeDisabled();

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(toggle).toHaveText("展开教程");
  await expect(guide).toHaveAttribute("aria-hidden", "true");
  await expect
    .poll(async () => (await guide.boundingBox())?.height ?? 0)
    .toBe(0);
  await expect(cards).toHaveCount(8);
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect.poll(async () => (await guide.boundingBox())?.height).toBe(378);

  const search = page.getByPlaceholder(
    label("zh", "agentSelector.searchPlaceholder"),
  );
  await expect(search).toHaveCSS("font-family", expectedFontFamily);
  await search.fill("健康小助手");
  await expect(cards).toHaveCount(1);
  await expect(
    cards.first().getByText("健康小助手", { exact: true }),
  ).toBeVisible();
  await search.fill("");
  await expect(cards).toHaveCount(8);
  await page
    .getByRole("button", { name: label("zh", "agentConfig.list.listView") })
    .click();
  await expect(page.getByRole("table")).toBeVisible();
  await expect(page.getByRole("table")).toHaveCSS(
    "font-family",
    expectedFontFamily,
  );
  await expect(page.getByRole("table").locator("tbody tr")).toHaveCount(8);
  await expect(
    page.getByRole("table").locator("tbody tr").first(),
  ).toContainText("2026-02-04");
  await expect(
    page.getByRole("table").locator("tbody tr").nth(1),
  ).not.toContainText("2026-01-23");
  await page
    .getByRole("button", { name: label("zh", "agentConfig.list.gridView") })
    .click();
  await expect(cards).toHaveCount(8);
  noPresentationMutation(fixture);

  fixture.rows = agentRows(20);
  await page.reload();
  await expect(cards).toHaveCount(10);
  await page.getByRole("listitem", { name: "2", exact: true }).click();
  await expect(
    cards.first().getByText("智能体11", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: label("zh", "agentConfig.list.pageSize") })
    .click();
  await page.getByText("20条/页", { exact: true }).click();
  await expect(cards).toHaveCount(20);
  expect(
    fixture.requests.some((request) => request.query.includes("page=2")),
  ).toBe(true);
  expect(
    fixture.requests.some((request) => request.query.includes("page_size=20")),
  ).toBe(true);
  noPresentationMutation(fixture);
  await page
    .getByRole("button", { name: label("zh", "agentConfig.list.new") })
    .click();
  await expect(
    page.getByText(label("zh", "agentConfig.createModal.template.create"), {
      exact: true,
    }),
  ).toBeVisible();
});

scenario("[AGENT-LIST-D4-002] empty guide height and narrow card/toolbar reachability", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  const fixture = await mockList(page, []);
  await page.goto(`${baseUrl}/zh/agents`);
  await expect(
    page.getByText(label("zh", "agentConfig.empty.noAgents")),
  ).toBeVisible();
  pixel(
    (await bounds(page.getByTestId("agent-guide-background"))).height,
    378,
    "empty guide height",
  );
  await expect(page.getByTestId("agent-guide-divider")).toBeVisible();
  fixture.rows = agentRows();
  await page.reload();
  await expect(page.locator("article")).toHaveCount(8);
  pixel(
    (await bounds(page.getByTestId("agent-guide-background"))).height,
    378,
    "restored populated guide height",
  );
  await expect(page.getByTestId("agent-guide-divider")).toHaveCount(0);
  await page.setViewportSize({ width: 768, height: 900 });
  const narrowCreate = page.getByRole("button", {
    name: label("zh", "agentConfig.list.new"),
    exact: true,
  });
  await narrowCreate.scrollIntoViewIfNeeded();
  await expect(narrowCreate).toBeInViewport();
  const narrowBody = page
    .locator("article")
    .first()
    .getByTestId("agent-card-body");
  await narrowBody.scrollIntoViewIfNeeded();
  await expect(narrowBody).toBeInViewport();
  await narrowBody.click();
  await expect(
    page
      .getByRole("dialog")
      .getByRole("heading", { name: "健康小助手", exact: true }),
  ).toBeVisible();
  await page.getByRole("dialog").locator(".ant-modal-close").click();
  const narrowFirstCard = page.locator("article").first();
  await narrowFirstCard.scrollIntoViewIfNeeded();
  await narrowFirstCard.hover();
  const narrowConfigure = narrowFirstCard.getByRole("button", {
    name: label("zh", "agentConfig.list.configure"),
    exact: true,
  });
  await expect(narrowConfigure).toBeInViewport();
  await narrowConfigure.click({ trial: true });
  const narrowMore = narrowFirstCard.getByRole("button", {
    name: label("zh", "agentRepository.mine.menu.more"),
    exact: true,
  });
  await expect(narrowMore).toBeInViewport();
  await narrowMore.click();
  await expect(page.getByRole("menu")).toBeVisible();
  await page.keyboard.press("Escape");
  const narrowLastBody = page
    .locator("article")
    .last()
    .getByTestId("agent-card-body");
  await narrowLastBody.scrollIntoViewIfNeeded();
  await expect(narrowLastBody).toBeInViewport();
  await narrowLastBody.click({ trial: true });
  noPresentationMutation(fixture);
  await page
    .getByRole("button", { name: label("zh", "agentConfig.guide.collapse") })
    .click();
  await expect
    .poll(
      async () =>
        (await page.getByTestId("agent-guide-background").boundingBox())
          ?.height ?? 0,
    )
    .toBe(0);
  const cards = page.locator("article");
  await expect(cards).toHaveCount(8);
  const first = await bounds(cards.first());
  const second = await bounds(cards.nth(1));
  const third = await bounds(cards.nth(2));
  pixel(first.y, second.y, "two-column narrow row");
  pixel(third.x, first.x, "narrow second-row position");
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(768);
  await expect(
    page.getByRole("button", { name: label("zh", "agentConfig.list.new") }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: label("zh", "agentConfig.button.import"),
      exact: true,
    }),
  ).toBeVisible();
  await cards.first().hover();
  await expect(
    cards.first().getByRole("button", { name: "配置", exact: true }),
  ).toBeVisible();
  noPresentationMutation(fixture);
  await narrowCreate.click();
  await expect(
    page.getByText(label("zh", "agentConfig.createModal.template.create"), {
      exact: true,
    }),
  ).toBeVisible();
});

scenario("[AGENT-LIST-D4-002] English step growth and 1280px hover/focus actions remain usable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 1080 });
  const rows = agentRows().map((agent, index) => ({
    ...agent,
    display_name: `Healthcare research assistant ${index + 1}`,
    tags: ["Long translated category name"],
    description:
      "A comprehensive healthcare research assistant that supports careful analysis and reliable information.",
  }));
  const fixture = await mockList(page, rows);
  await page.goto(`${baseUrl}/en/agents`);
  await expect(page.locator("article")).toHaveCount(8);
  const steps = page.getByTestId("agent-guide-step");
  for (const step of await steps.all()) {
    expect((await bounds(step)).height).toBeGreaterThanOrEqual(156);
    const stepBox = await bounds(step);
    const textBox = await bounds(step.locator("p"));
    expect(textBox.y + textBox.height).toBeLessThanOrEqual(
      stepBox.y + stepBox.height - 23,
    );
  }
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(1280);
  const toggle = page.locator("header").getByRole("button");
  await expect(toggle).toHaveText("Collapse tutorial");
  await expect(toggle).toBeVisible();
  await toggle.click();
  await expect(toggle).toHaveText("Expand tutorial");
  await expect
    .poll(
      async () =>
        (await page.getByTestId("agent-guide-background").boundingBox())
          ?.height ?? 0,
    )
    .toBe(0);
  await toggle.click();
  await expect(toggle).toHaveText("Collapse tutorial");
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("agent-guide-background")).toBeVisible();
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect
    .poll(
      async () =>
        (await page.getByTestId("agent-guide-background").boundingBox())
          ?.height ?? 0,
    )
    .toBe(0);
  const first = page.locator("article").first();
  await first.hover();
  const configure = first.getByRole("button", {
    name: label("en", "agentConfig.list.configure"),
    exact: true,
  });
  const publish = first.getByRole("button", {
    name: label("en", "agentConfig.list.publish"),
    exact: true,
  });
  const cardBox = await bounds(first);
  const configureBox = await bounds(configure);
  const publishBox = await bounds(publish);
  expect(configureBox.x + configureBox.width).toBeLessThanOrEqual(publishBox.x);
  expect(publishBox.x + publishBox.width).toBeLessThanOrEqual(
    cardBox.x + cardBox.width - 23,
  );
  const visibleTextBottom = await first
    .getByTestId("agent-card-body")
    .locator("p")
    .evaluate((element) => {
      const box = element.getBoundingClientRect();
      const range = document.createRange();
      range.selectNodeContents(element);
      const lineHeight = Number.parseFloat(
        getComputedStyle(element).lineHeight,
      );
      return Math.max(
        ...Array.from(range.getClientRects())
          .filter((rect) => rect.y < box.y + lineHeight * 2)
          .map((rect) => rect.bottom),
      );
    });
  expect(configureBox.y).toBeGreaterThanOrEqual(visibleTextBottom);
  await page.locator("header h1").click();
  await first.getByTestId("agent-card-body").focus();
  await expect(configure).toBeVisible();
  await expect(publish).toBeVisible();
  noPresentationMutation(fixture);
  await configure.click();
  await expect(page).toHaveURL(/\/en\/agents\/1$/);
});

journey("AGENT-LIST-D4-002", async ({ page, contract }) => {
  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    const response = await page.request.get(baseUrl);
    expect(response.ok()).toBe(true);
  });
  expect(scenarios).toHaveLength(3);
  for (const [index, scenario] of scenarios.entries()) {
    await page.unrouteAll({ behavior: "wait" });
    await page.context().clearCookies();
    if (page.url().startsWith(baseUrl)) await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
    // The audited assertion executes the complete scenario, including its boundary guards.
    await contract.step(contract.expectedIds("steps")[index], async () => {
      await contract.assertion(contract.expectedIds("assertions")[index], async () => {
        await scenario.run({ page });
        return scenario.name;
      });
      return scenario.name;
    });
  }
});
