// @ts-nocheck
/**
 * D4 browser acceptance for three merged but independently observable
 * behaviours of the agent repository / agent management surfaces:
 *
 *  1. Agent repository listings can be ordered by publish time (latest first).
 *  2. Each repository listing card is marked as a main or an ordinary agent.
 *  3. The agent management page matches agents by tag on top of its name and
 *     description search, and a tag persisted as a stringified array renders
 *     as an individual tag instead of crashing the page.
 *
 * Product surface exercised:
 *   - frontend/app/[locale]/agent-space/agent-space.tsx   (sort control + badge)
 *   - frontend/app/[locale]/agents/page.tsx               (tag search)
 *
 * Every HTTP response is fulfilled with deterministic fixtures, so the journey
 * never depends on a live tenant, provider or database.
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
const label = (key) => {
  const value = messages[key];
  if (typeof value !== "string") throw new Error(`Missing zh test label: ${key}`);
  return value;
};

const SORT_LABEL = label("agentRepository.sort.label");
const SORT_DEFAULT_LABEL = label("agentRepository.sort.default");
const SORT_LATEST_LABEL = label("agentRepository.sort.latest");
const MAIN_AGENT_LABEL = label("agentRepository.card.mainAgent");
const AGENT_SEARCH_PLACEHOLDER = label("agentSelector.searchPlaceholder");

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

/** Default order: newest repository id first, independent of publish time. */
const defaultOrderedListings = () =>
  [...REPOSITORY_LISTINGS].sort(
    (left, right) => right.agent_repository_id - left.agent_repository_id
  );

/** Latest-published order: dated listings newest first, undated listings last. */
const latestOrderedListings = () => {
  const dated = REPOSITORY_LISTINGS.filter((listing) => listing.create_time);
  const undated = REPOSITORY_LISTINGS.filter((listing) => !listing.create_time);
  const sorted = [...dated].sort((left, right) =>
    left.create_time === right.create_time
      ? right.agent_repository_id - left.agent_repository_id
      : left.create_time < right.create_time
        ? 1
        : -1
  );
  return [...sorted, ...undated];
};

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
    permission: "EDIT",
  },
  {
    agent_id: ORDINARY_AGENT_ID,
    name: "ordinary_agent",
    display_name: ORDINARY_AGENT_TITLE,
    description: "不参与标签匹配的普通智能体。",
    tags: ["普通标签"],
    create_time: "2026-02-03T09:00:00",
    current_version_no: null,
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
            accessibleRoutes: ["/agents", "/agent-space"],
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
    if (endpoint === "/repository/agent/mine")
      return json(route, {
        items: [],
        pagination: { page: 1, page_size: 20, total: 0, total_pages: 0 },
      });
    if (endpoint === "/repository/agent") {
      const latest = url.searchParams.get("sort_by_update_time") === "true";
      const items = latest ? latestOrderedListings() : defaultOrderedListings();
      return json(route, {
        items,
        pagination: {
          page: 1,
          page_size: items.length,
          total: items.length,
          total_pages: 1,
        },
      });
    }
    if (endpoint === "/agent/list/page") {
      const search = url.searchParams.get("search")?.trim() ?? "";
      const predicates = url.searchParams.get("search_tag_predicates") ?? "";
      const tagMatched =
        predicates.includes(`"definition_id":${TAG_DEFINITION_ID}`) &&
        predicates.includes(`${TAG_VALUE_ID}`);
      const matching = AGENT_ROWS.filter((agent) => {
        const haystack = `${agent.display_name ?? agent.name} ${agent.description ?? ""}`;
        return (
          haystack.includes(search) ||
          (tagMatched && agent.agent_id === TAG_AGENT_ID)
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

  const repositoryCard = (title) =>
    page
      .getByRole("heading", { level: 2, name: title, exact: true })
      .locator(
        "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' group ')][1]"
      );

  const agentCard = (title) =>
    page
      .locator("article")
      .filter({ has: page.getByRole("button", { name: title, exact: true }) });

  const selectSortOption = async (optionLabel) => {
    await page
      .getByRole("combobox", { name: SORT_LABEL, exact: true })
      .click();
    await page
      .locator(".ant-select-item-option:visible")
      .filter({ hasText: optionLabel })
      .click();
  };

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
        await page.goto(`${baseUrl}/zh/agent-space`);
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
        return "agent repository rendered three deterministic listings";
      },
    ],
    steps: [
      async () => {
        // The untouched default order must not request publish-time sorting.
        expect(
          fixture.repositoryListings.every(
            (request) => !request.query.includes("sort_by_update_time")
          )
        ).toBe(true);
        await expect.poll(repositoryTitleOrder).toEqual([
          UNDATED_TITLE,
          MAIN_TITLE,
          ORDINARY_TITLE,
        ]);

        const latestBaseline = fixture.repositoryListings.length;
        await selectSortOption(SORT_LATEST_LABEL);
        await expect
          .poll(() =>
            requestsSince(
              "repositoryListings",
              latestBaseline,
              (request) => request.query.includes("sort_by_update_time=true")
            ).length
          )
          .toBeGreaterThan(0);
        await expect.poll(repositoryTitleOrder).toEqual([
          MAIN_TITLE,
          ORDINARY_TITLE,
          UNDATED_TITLE,
        ]);

        const defaultBaseline = fixture.repositoryListings.length;
        await selectSortOption(SORT_DEFAULT_LABEL);
        await expect
          .poll(() =>
            requestsSince(
              "repositoryListings",
              defaultBaseline,
              (request) => request.query.includes("sort_by_update_time")
            ).length
          )
          .toBe(0);
        await expect.poll(repositoryTitleOrder).toEqual([
          UNDATED_TITLE,
          MAIN_TITLE,
          ORDINARY_TITLE,
        ]);
        return "latest-published order forwarded, default order left untouched";
      },
      async () => {
        await expect(
          repositoryCard(MAIN_TITLE).locator("span.bg-amber-50")
        ).toHaveText(MAIN_AGENT_LABEL);
        await expect(
          repositoryCard(ORDINARY_TITLE).locator("span.bg-amber-50")
        ).toHaveCount(0);
        await expect(repositoryCard(ORDINARY_TITLE)).not.toContainText(
          MAIN_AGENT_LABEL
        );
        await expect(page.locator("span.bg-amber-50:visible")).toHaveCount(1);
        return "main agent badged, ordinary listing unbadged";
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
    ],
    assertions: [
      async () => {
        await page.goto(`${baseUrl}/zh/agent-space`);
        await expect(
          page.getByRole("heading", {
            level: 2,
            name: MAIN_TITLE,
            exact: true,
          })
        ).toBeVisible();
        const baseline = fixture.repositoryListings.length;
        await selectSortOption(SORT_LATEST_LABEL);
        await expect
          .poll(() =>
            requestsSince(
              "repositoryListings",
              baseline,
              (request) => request.query.includes("sort_by_update_time=true")
            ).length
          )
          .toBeGreaterThan(0);
        expect(await repositoryTitleOrder()).toEqual([
          MAIN_TITLE,
          ORDINARY_TITLE,
          UNDATED_TITLE,
        ]);
        const ordered = latestOrderedListings();
        expect(ordered.at(-1).display_name).toBe(UNDATED_TITLE);
        return "latest-published order carries the flag and lists the undated listing last";
      },
      async () => {
        await page.goto(`${baseUrl}/zh/agent-space`);
        await expect(
          page.getByRole("heading", {
            level: 2,
            name: MAIN_TITLE,
            exact: true,
          })
        ).toBeVisible();
        await expect(
          repositoryCard(MAIN_TITLE).locator("span.bg-amber-50")
        ).toHaveText(MAIN_AGENT_LABEL);
        await expect(
          repositoryCard(ORDINARY_TITLE).locator("span.bg-amber-50")
        ).toHaveCount(0);
        await expect(page.locator("span.bg-amber-50:visible")).toHaveCount(1);
        return "exactly the main-agent listing shows the amber main-agent badge";
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
    ],
  });
});
