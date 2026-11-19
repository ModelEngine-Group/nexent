// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

// @ts-nocheck
/**
 * Verifies the default agent repository view, listing markers, pagination,
 * and tag search and filtering on the agent management page.
 * HTTP fixtures isolate the journey from live tenant data.
 */
import fs from "node:fs";
import path from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";

const ID = "AGENT-REPO-SORT-MAIN-TAG-D4-001";
const baseUrl = process.env.NEXENT_BASE_URL ?? "http://localhost:3000";

const messages = JSON.parse(
  fs.readFileSync(
    path.join(
      process.env.NEXENT_REPO,
      "frontend/public/locales/zh/common.json"
    ),
    "utf8"
  )
);
// The locale file mixes flat dotted keys with nested objects (for example
// resourceCenter), so resolve a key directly first and by path afterwards.
const label = (key) => {
  const value =
    key in messages
      ? messages[key]
      : key.split(".").reduce(
          (node, part) =>
            node && typeof node === "object" ? node[part] : undefined,
          messages
        );
  if (typeof value !== "string") throw new Error(`Missing zh test label: ${key}`);
  return value;
};

const SORT_LABEL = label("agentRepository.sort.label");
const MAIN_AGENT_LABEL = label("agentRepository.card.mainAgent");
const SUB_AGENT_LABEL = label("space.detail.tabs.subAgents");
const AGENT_SEARCH_PLACEHOLDER = label("agentSelector.searchPlaceholder");
const TAG_FILTER_BUTTON = label("repository.tagFilter.button");
const TAG_FILTER_CLEAR = label("repository.tagFilter.clear");

const MAIN_TITLE = "仓库智能体二";
const ORDINARY_TITLE = "仓库智能体一";
const UNDATED_TITLE = "仓库智能体三";

const TAG_AGENT_ID = 201;
const ORDINARY_AGENT_ID = 202;
const TAG_AGENT_TITLE = "标签智能体";
const ORDINARY_AGENT_TITLE = "普通智能体";
const TAG_SEARCH_KEYWORD = "d4_key";
const TAG_SEARCH_VALUE = "d4_value";
const TAG_DEFINITION_ID = 21;
const TAG_VALUE_ID = 311;
const TAG_BUCKET_ID = 7;
/** The historical defect: a tag array persisted as a Python-style string. */
const STRINGIFIED_TAG_PAYLOAD = "['d4_value', 'd4_extra']";
/** Accessible name of the tag filter's value selector for the fixture tag. */
const TAG_FILTER_SELECT_ARIA = label("tagManagement.filter.ariaLabel").replace(
  "{{definition}}",
  TAG_SEARCH_KEYWORD
);

/** POST endpoints that only read data; every other non-GET is a write. */
const READ_ONLY_POST_ENDPOINTS = new Set(["/agent/search_info", "/groups/list"]);

const REPOSITORY_LISTINGS = [
  {
    agent_repository_id: 11,
    agent_id: 101,
    name: "repository_agent_one",
    display_name: ORDINARY_TITLE,
    description: "普通仓库智能体，未被标记。",
    tags: [],
    create_time: "2026-01-10T09:00:00",
    tool_count: 0,
    downloads: 0,
    is_official: false,
    is_main_agent: false,
  },
  {
    agent_repository_id: 12,
    agent_id: 102,
    name: "repository_agent_two",
    display_name: MAIN_TITLE,
    description: "主智能体仓库条目，发布时间最新。",
    tags: [],
    create_time: "2026-03-05T09:00:00",
    tool_count: 0,
    downloads: 0,
    is_official: false,
    is_main_agent: true,
  },
  {
    agent_repository_id: 13,
    agent_id: 103,
    name: "repository_agent_three",
    display_name: UNDATED_TITLE,
    description: "没有发布时间记录的仓库智能体。",
    tags: [],
    create_time: null,
    tool_count: 0,
    downloads: 0,
    is_official: false,
    is_main_agent: false,
  },
];

/**
 * Undated filler listings that only exist to make the repository span more
 * than one page at the frozen test viewport (twelve cards per page). They stay
 * undated so the three tracked listings remain together on page one.
 */
const FILLER_LISTINGS = Array.from({ length: 10 }, (_, index) => {
  const sequence = index + 1;
  const suffix = String(sequence).padStart(2, "0");
  return {
    agent_repository_id: sequence,
    agent_id: 400 + sequence,
    name: `filler_repository_agent_${suffix}`,
    display_name: `填充仓库条目${suffix}`,
    description: "仅用于让仓库列表跨页的填充条目。",
    tags: [],
    create_time: null,
    tool_count: 0,
    downloads: 0,
    is_official: false,
    is_main_agent: false,
  };
});

const ALL_LISTINGS = [...REPOSITORY_LISTINGS, ...FILLER_LISTINGS];

/** Default order: newest repository id first, independent of publish time. */
const defaultOrderedListings = () =>
  [...ALL_LISTINGS].sort(
    (left, right) => right.agent_repository_id - left.agent_repository_id
  );

const AGENT_ROWS = [
  {
    agent_id: TAG_AGENT_ID,
    name: "tag_search_agent",
    display_name: TAG_AGENT_TITLE,
    description: "用于验证按标签搜索命中的智能体。",
    // The stringified array the tag search must recover from.
    tags: STRINGIFIED_TAG_PAYLOAD,
    create_time: "2026-02-01T09:00:00",
    update_time: "2026-02-02T09:00:00",
    current_version_no: 1,
    is_main_agent: true,
    permission: "EDIT",
  },
  {
    agent_id: ORDINARY_AGENT_ID,
    name: "ordinary_agent",
    display_name: ORDINARY_AGENT_TITLE,
    description: "不参与标签匹配的普通智能体。",
    tags: ["普通标签"],
    create_time: "2026-02-03T09:00:00",
    update_time: "2026-02-04T09:00:00",
    current_version_no: 1,
    is_main_agent: false,
    permission: "EDIT",
  },
];

async function mockNexent(page) {
  const fixture = {
    requests: [],
    writes: [],
    providerCalls: [],
    repositoryListings: [],
    agentList: [],
  };
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.includes("/api/")) return;
    const endpoint = url.pathname.replace(/^.*\/api/, "");
    const entry = { method: request.method(), endpoint, query: url.search };
    fixture.requests.push(entry);
    if (
      request.method() !== "GET" &&
      !READ_ONLY_POST_ENDPOINTS.has(endpoint)
    )
      fixture.writes.push(endpoint);
    if (/\/agent\/(run|nl2agent\/run)|\/skills\/nl2skill\/run/.test(endpoint))
      fixture.providerCalls.push(endpoint);
    if (endpoint === "/repository/agent") fixture.repositoryListings.push(entry);
    if (endpoint === "/agent/list/page") fixture.agentList.push(entry);
  });
  const json = (route, data) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(data),
    });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const endpoint = url.pathname.replace(/^.*\/api/, "");
    if (endpoint === "/tenant_config/deployment_version")
      return json(route, {
        deployment_version: "speed",
        app_version: "test",
        status: "success",
      });
    if (endpoint === "/user/current_user_info")
      return json(route, {
        data: {
          user: {
            user_id: "agent-repo-sort-d4-user",
            tenant_id: "agent-repo-sort-d4-tenant",
            user_email: "agent-repo-sort-d4@nexent.test",
            user_role: "SPEED",
            auth_provider: "local",
            group_ids: [],
            permissions: [],
            accessibleRoutes: ["/agents", "/resource-space"],
          },
        },
      });
    if (endpoint === "/groups/list")
      return json(route, { data: [], total: 0, message: "ok" });
    if (endpoint === "/tag-libraries")
      return json(route, [
        {
          bucket_id: TAG_BUCKET_ID,
          bucket_key: "default_resource",
          bucket_name: "Default resources",
          status: "active",
          resource_types: [],
          definition_count: 1,
          definition_capacity: 100,
        },
      ]);
    if (endpoint === `/tag-libraries/${TAG_BUCKET_ID}/definitions`)
      return json(route, [
        {
          definition_id: TAG_DEFINITION_ID,
          bucket_id: TAG_BUCKET_ID,
          definition_key: TAG_SEARCH_KEYWORD,
          definition_name: TAG_SEARCH_KEYWORD,
          selection_mode: "multi_select",
          sort_order: 1,
          status: "active",
          active_value_count: 1,
          value_capacity: 20,
          values: [
            {
              value_id: TAG_VALUE_ID,
              display_value: TAG_SEARCH_VALUE,
              normalized_value: TAG_SEARCH_VALUE,
              sort_order: 1,
              status: "active",
            },
          ],
        },
      ]);
    if (endpoint === "/repository/agent/tags") return json(route, { items: [] });
    if (endpoint === "/repository/agent") {
      const items = defaultOrderedListings();
      const current = Number(url.searchParams.get("page") ?? 1);
      const size = Number(url.searchParams.get("page_size") ?? 12);
      return json(route, {
        items: items.slice((current - 1) * size, current * size),
        pagination: {
          page: current,
          page_size: size,
          total: items.length,
          total_pages: Math.ceil(items.length / size),
        },
      });
    }
    if (endpoint === "/agent/list/page") {
      const search = url.searchParams.get("search")?.trim() ?? "";
      const searchPredicates =
        url.searchParams.get("search_tag_predicates") ?? "";
      const filterPredicates = url.searchParams.get("tag_predicates") ?? "";
      // "search_tag_predicates" widens the free-text search to tag matches,
      // while "tag_predicates" restricts the list to the tagged agents, so the
      // fixture models the two parameters with the semantics the page relies on.
      const matchesFixtureTag = (value) =>
        value.includes(`"definition_id":${TAG_DEFINITION_ID}`) &&
        value.includes(`${TAG_VALUE_ID}`);
      const searchTagMatched = matchesFixtureTag(searchPredicates);
      let source = AGENT_ROWS;
      if (matchesFixtureTag(filterPredicates))
        source = source.filter((agent) => agent.agent_id === TAG_AGENT_ID);
      const matching = source.filter((agent) => {
        if (!search) return true;
        const haystack = `${agent.display_name ?? agent.name} ${agent.description ?? ""}`;
        return (
          haystack.includes(search) ||
          (searchTagMatched && agent.agent_id === TAG_AGENT_ID)
        );
      });
      const current = Number(url.searchParams.get("page") ?? 1);
      const size = Number(url.searchParams.get("page_size") ?? 10);
      return json(route, {
        items: matching.slice((current - 1) * size, current * size),
        pagination: {
          page: current,
          page_size: size,
          total: matching.length,
          total_pages: Math.ceil(matching.length / size),
        },
      });
    }
    return json(route, {});
  });
  return fixture;
}

journey(ID, async (context) => {
  const { page, expect } = context;
  let fixture;

  /** Visible repository card headings, in rendered order. */
  const repositoryTitles = () =>
    page
      .getByRole("heading", { level: 2 })
      .filter({ hasText: /^仓库智能体[一二三]$/ });
  const repositoryTitleOrder = async () =>
    (await repositoryTitles().allInnerTexts()).map((value) => value.trim());

  /** The card group element that owns a heading. */
  const resourceCard = (title) =>
    page
      .getByRole("heading", { level: 2, name: title, exact: true })
      .locator(
        "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' group ')][1]"
      );

  const agentCard = (title) =>
    page
      .locator("article")
      .filter({ has: page.getByRole("button", { name: title, exact: true }) });

  const queryParam = (request, name) =>
    new URLSearchParams(request?.query ?? "").get(name);

  const hasSortFlag = (request) =>
    ["sort_by_downloads", "sort_by_published_time", "sort_by_update_time"].some(
      (key) => queryParam(request, key) !== null
    );

  const expectDefaultRepository = async (baseline = 0) => {
    await expect.poll(() => fixture.repositoryListings.length).toBeGreaterThan(baseline);
    await expect.poll(repositoryTitleOrder).toEqual([
      UNDATED_TITLE,
      MAIN_TITLE,
      ORDINARY_TITLE,
    ]);
    await expect(page.getByRole("combobox", { name: SORT_LABEL, exact: true })).toHaveCount(0);
    expect(fixture.repositoryListings.slice(baseline).some(hasSortFlag)).toBe(false);
  };

  const expectDefaultPagination = async () => {
    const baseline = fixture.repositoryListings.length;
    await page.goto(`${baseUrl}/zh/resource-space?tab=agent&sort=downloads`);
    await expectDefaultRepository(baseline);
    const pagingBaseline = fixture.repositoryListings.length;
    await page.locator(".ant-pagination-item-2:visible").click();
    await expect(page.getByRole("heading", { name: "填充仓库条目01", exact: true })).toBeVisible();
    await expect.poll(() =>
      fixture.repositoryListings.slice(pagingBaseline).some(
        (request) => queryParam(request, "page") === "2" && !hasSortFlag(request)
      )
    ).toBe(true);
    expect(fixture.writes).toEqual([]);
    expect(fixture.providerCalls).toEqual([]);
  };

  /** Open the agent management page's tag filter popover. */
  const openTagFilter = async () => {
    await page
      .getByRole("button", { name: TAG_FILTER_BUTTON, exact: true })
      .filter({ visible: true })
      .click();
    await expect(page.getByLabel(TAG_FILTER_SELECT_ARIA)).toBeVisible();
  };

  /** Select the fixture tag value offered by the open tag filter popover. */
  const selectTagFilterValue = async () => {
    await page.getByLabel(TAG_FILTER_SELECT_ARIA).click();
    await page
      .locator(".ant-select-item-option:visible")
      .filter({ hasText: TAG_SEARCH_VALUE })
      .click();
  };

  /** Drop the active tag selection through the popover's clear action. */
  const clearTagFilter = async () => {
    await page
      .getByRole("button", { name: TAG_FILTER_CLEAR, exact: true })
      .filter({ visible: true })
      .click();
  };

  const lastTagFilterRequest = () =>
    fixture.agentList
      .filter((request) => queryParam(request, "tag_predicates") !== null)
      .at(-1);

  const requestsSince = (kind, offset, predicate) =>
    fixture[kind].slice(offset).filter(predicate);

  const lastAgentListPredicates = () => {
    const withPredicates = fixture.agentList.filter((request) =>
      request.query.includes("search_tag_predicates")
    );
    return decodeURIComponent(withPredicates.at(-1)?.query ?? "");
  };

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await page.setViewportSize({ width: 1920, height: 1080 });
        fixture = await mockNexent(page);
        await page.goto(`${baseUrl}/zh/resource-space?tab=agent`);
        await expect(
          page.getByRole("heading", {
            level: 2,
            name: MAIN_TITLE,
            exact: true,
          })
        ).toBeVisible();
        await expect(repositoryTitles()).toHaveCount(3);
        await expect
          .poll(() => fixture.repositoryListings.length)
          .toBeGreaterThan(0);
        return "unified agent repository rendered three deterministic tracked listings";
      },
    ],
    steps: [
      async () => {
        await expectDefaultRepository();
        return "the default repository has no sort control and uses the default API order";
      },
      async () => {
        // The unified repository card marks each listing as a main agent or
        // an ordinary agent in its meta line.
        await expect(
          resourceCard(MAIN_TITLE).getByText(MAIN_AGENT_LABEL, { exact: true })
        ).toBeVisible();
        await expect(
          resourceCard(MAIN_TITLE).getByText(SUB_AGENT_LABEL, { exact: true })
        ).toHaveCount(0);
        await expect(
          resourceCard(ORDINARY_TITLE).getByText(SUB_AGENT_LABEL, {
            exact: true,
          })
        ).toBeVisible();
        await expect(resourceCard(ORDINARY_TITLE)).not.toContainText(
          MAIN_AGENT_LABEL
        );
        await expect(
          page.getByText(MAIN_AGENT_LABEL, { exact: true })
        ).toHaveCount(1);
        return "main agent marked, ordinary listing marked as an ordinary agent";
      },
      async () => {
        const baseline = fixture.agentList.length;
        await page.goto(`${baseUrl}/zh/agents`);
        const search = page.getByPlaceholder(AGENT_SEARCH_PLACEHOLDER);
        await expect(search).toBeVisible();
        await search.fill(TAG_SEARCH_KEYWORD);
        await expect
          .poll(() =>
            requestsSince("agentList", baseline, (request) =>
              request.query.includes("search_tag_predicates")
            ).length
          )
          .toBeGreaterThan(0);
        const card = agentCard(TAG_AGENT_TITLE);
        await expect(card).toBeVisible();
        await expect(page.locator("article")).toHaveCount(1);
        await expect(card.getByText(TAG_SEARCH_VALUE, { exact: true })).toBeVisible();
        await expect(card).not.toContainText("['d4_value");
        await expect(card).not.toContainText("d4_extra");
        return "tag keyword narrowed the list to the tag-matched agent";
      },
      async () => {
        await page.goto(`${baseUrl}/zh/agents`);
        await expect(
          page.getByPlaceholder(AGENT_SEARCH_PLACEHOLDER)
        ).toBeVisible();

        const baseline = fixture.agentList.length;
        await openTagFilter();
        await selectTagFilterValue();
        await expect
          .poll(
            () =>
              requestsSince(
                "agentList",
                baseline,
                (request) => queryParam(request, "tag_predicates") !== null
              ).length
          )
          .toBeGreaterThan(0);

        await expect(page.locator("article")).toHaveCount(1);
        await expect(agentCard(TAG_AGENT_TITLE)).toBeVisible();
        await expect(agentCard(ORDINARY_AGENT_TITLE)).toHaveCount(0);
        await expect(agentCard(TAG_AGENT_TITLE)).not.toContainText("['d4_value");
        return "tag filter narrowed the list to the tag-matched agent only";
      },
      async () => {
        await page.goto(`${baseUrl}/zh/agents`);
        const search = page.getByPlaceholder(AGENT_SEARCH_PLACEHOLDER);
        await openTagFilter();
        await selectTagFilterValue();
        await expect(page.locator("article")).toHaveCount(1);

        // The ordinary agent matches this query but carries no fixture tag, so
        // an intersection must hide it while both criteria are active.
        const baseline = fixture.agentList.length;
        await search.fill(ORDINARY_AGENT_TITLE);
        await expect
          .poll(
            () =>
              requestsSince(
                "agentList",
                baseline,
                (request) =>
                  queryParam(request, "search") === ORDINARY_AGENT_TITLE &&
                  queryParam(request, "tag_predicates") !== null
              ).length
          )
          .toBeGreaterThan(0);
        await expect(page.locator("article")).toHaveCount(0);

        await clearTagFilter();
        await expect
          .poll(() => queryParam(fixture.agentList.at(-1), "tag_predicates"))
          .toBeNull();
        await expect(agentCard(ORDINARY_AGENT_TITLE)).toBeVisible();
        await expect(page.locator("article")).toHaveCount(1);
        return "tag filter and query combined as an intersection and cleared back to the query result";
      },
      async () => {
        await expectDefaultPagination();
        return "pagination still works in the default order, even with a stale copies sort link";
      },
    ],
    assertions: [
      async () => {
        const baseline = fixture.repositoryListings.length;
        await page.goto(`${baseUrl}/zh/resource-space?tab=agent&sort=latest`);
        await expectDefaultRepository(baseline);
        return "a stale latest sort link does not affect the repository";
      },
      async () => {
        await page.goto(`${baseUrl}/zh/resource-space?tab=agent`);
        await expect(
          page.getByRole("heading", {
            level: 2,
            name: MAIN_TITLE,
            exact: true,
          })
        ).toBeVisible();
        await expect(
          resourceCard(MAIN_TITLE).getByText(MAIN_AGENT_LABEL, { exact: true })
        ).toBeVisible();
        await expect(
          resourceCard(ORDINARY_TITLE).getByText(SUB_AGENT_LABEL, {
            exact: true,
          })
        ).toBeVisible();
        await expect(
          page.getByText(MAIN_AGENT_LABEL, { exact: true })
        ).toHaveCount(1);
        return "exactly the main-agent listing carries the main-agent marker";
      },
      async () => {
        const baseline = fixture.agentList.length;
        await page.goto(`${baseUrl}/zh/agents`);
        const search = page.getByPlaceholder(AGENT_SEARCH_PLACEHOLDER);
        await expect(search).toBeVisible();
        await search.fill(TAG_SEARCH_KEYWORD);
        await expect
          .poll(() =>
            requestsSince("agentList", baseline, (request) =>
              request.query.includes("search_tag_predicates")
            ).length
          )
          .toBeGreaterThan(0);
        const query = lastAgentListPredicates();
        expect(query).toContain(`search=${TAG_SEARCH_KEYWORD}`);
        expect(query).toContain(`"definition_id":${TAG_DEFINITION_ID}`);
        expect(query).toContain(`${TAG_VALUE_ID}`);
        await expect(agentCard(TAG_AGENT_TITLE)).toBeVisible();
        await expect(
          agentCard(TAG_AGENT_TITLE).getByText(TAG_SEARCH_VALUE, { exact: true })
        ).toBeVisible();
        await expect(page.locator("article")).not.toContainText("['d4_value");
        expect(fixture.writes).toEqual([]);
        expect(fixture.providerCalls).toEqual([]);
        return "tag predicates forwarded, recovered tag rendered, no unrelated write or execution";
      },
      async () => {
        const baseline = fixture.agentList.length;
        await page.goto(`${baseUrl}/zh/agents`);
        await expect(
          page.getByPlaceholder(AGENT_SEARCH_PLACEHOLDER)
        ).toBeVisible();
        await openTagFilter();
        await selectTagFilterValue();
        await expect
          .poll(
            () =>
              requestsSince(
                "agentList",
                baseline,
                (request) => queryParam(request, "tag_predicates") !== null
              ).length
          )
          .toBeGreaterThan(0);

        const filters =
          queryParam(lastTagFilterRequest(), "tag_predicates") ?? "";
        expect(filters).toContain(`"definition_id":${TAG_DEFINITION_ID}`);
        expect(filters).toContain(`${TAG_VALUE_ID}`);
        await expect(page.locator("article")).toHaveCount(1);
        await expect(agentCard(TAG_AGENT_TITLE)).toBeVisible();
        await expect(agentCard(ORDINARY_AGENT_TITLE)).toHaveCount(0);
        await expect(agentCard(TAG_AGENT_TITLE)).not.toContainText("['d4_value");
        expect(fixture.writes).toEqual([]);
        expect(fixture.providerCalls).toEqual([]);
        return "the tag filter forwarded its predicates, narrowed the list and triggered no unrelated write";
      },
      async () => {
        await page.goto(`${baseUrl}/zh/agents`);
        const search = page.getByPlaceholder(AGENT_SEARCH_PLACEHOLDER);
        await openTagFilter();
        await selectTagFilterValue();
        await expect(page.locator("article")).toHaveCount(1);

        const baseline = fixture.agentList.length;
        await search.fill(ORDINARY_AGENT_TITLE);
        await expect
          .poll(
            () =>
              requestsSince(
                "agentList",
                baseline,
                (request) =>
                  queryParam(request, "search") === ORDINARY_AGENT_TITLE
              ).length
          )
          .toBeGreaterThan(0);
        await expect(page.locator("article")).toHaveCount(0);

        await clearTagFilter();
        await expect
          .poll(() => queryParam(fixture.agentList.at(-1), "tag_predicates"))
          .toBeNull();
        await expect(agentCard(ORDINARY_AGENT_TITLE)).toBeVisible();
        await expect(agentCard(TAG_AGENT_TITLE)).toHaveCount(0);
        return "only agents satisfying both the query and the selected tag remained, and clearing the filter restored the query result";
      },
      async () => {
        await expectDefaultPagination();
        return "pagination still works in the default order, even with a stale copies sort link";
      },
    ],
  });
});
