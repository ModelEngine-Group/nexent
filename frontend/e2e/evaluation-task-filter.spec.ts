import { expect, test, type Page, type Route } from "@playwright/test";

const agents = [
  { agent_id: 7, display_name: "Agent One" },
  { agent_id: 9, display_name: "Agent Two" },
];

test.setTimeout(90_000);

type EvaluationRun = {
  agent_evaluation_id: number;
  agent_id: number;
  agent_name: string;
  agent_version_no: number;
  evaluation_set_name: string;
  score_overall: number;
  status: string;
};

type EvaluationPageApiOptions = {
  listRuns?: (agentIds: string | null) => EvaluationRun[];
  createRun?: (body: Record<string, unknown>) => EvaluationRun;
};

const json = (route: Route, body: unknown) =>
  route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });

async function mockEvaluationPageApis(
  page: Page,
  requests: (string | null)[],
  options: EvaluationPageApiOptions = {}
) {
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
          user_id: "evaluation-test-user",
          tenant_id: "evaluation-test-tenant",
          user_email: "evaluation@nexent.test",
          user_role: "SPEED",
          auth_provider: "local",
          group_ids: [],
          permissions: [],
          accessibleRoutes: ["/evaluation"],
        },
      },
    })
  );
  await page.route("**/api/groups/list", (route) =>
    json(route, { data: [], total: 0, message: "ok" })
  );
  await page.route("**/api/agent/published_list", (route) =>
    json(route, { data: agents })
  );
  await page.route("**/api/evaluators", (route) =>
    json(route, {
      data: [
        {
          evaluator_id: 31,
          name: "Test evaluator",
          name_en: "Test evaluator",
          status: "PUBLISHED",
          input_fields: [],
        },
      ],
    })
  );
  await page.route("**/api/evaluation-sets", (route) =>
    json(route, { data: [] })
  );
  await page.route("**/api/model/list", (route) =>
    json(route, {
      data: [
        {
          model_id: 11,
          model_name: "test-judge",
          display_name: "Test Judge",
          model_type: "llm",
          connect_status: "available",
        },
      ],
    })
  );
  await page.route("**/api/agent/7/versions", (route) =>
    json(route, { data: [{ version_no: 1, version_name: "test" }] })
  );
  await page.route("**/api/agent-evaluations*", (route) => {
    if (route.request().method() === "POST") {
      return json(route, {
        data: options.createRun?.(route.request().postDataJSON()) ?? {},
      });
    }
    const url = new URL(route.request().url());
    const agentIds = url.searchParams.get("agent_ids");
    requests.push(agentIds);
    return json(route, {
      data: options.listRuns?.(agentIds) ?? [
        {
          agent_evaluation_id: 101,
          agent_id: 7,
          agent_name: "Agent One",
          agent_version_no: 1,
          evaluation_set_name: "Regression set",
          score_overall: 0.9,
          status: "COMPLETED",
        },
        {
          agent_evaluation_id: 202,
          agent_id: 9,
          agent_name: "Agent Two",
          agent_version_no: 1,
          evaluation_set_name: "Regression set",
          score_overall: 0.8,
          status: "COMPLETED",
        },
      ],
    });
  });
}

test("AC-001/002 defaults to all agents and supports searchable multi-select", async ({
  page,
}) => {
  const requests: (string | null)[] = [];
  await mockEvaluationPageApis(page, requests);

  await page.goto("http://127.0.0.1:3000/en/evaluation");
  await expect(
    page.getByText("Evaluation Tasks", { exact: true })
  ).toBeVisible();
  await expect(page.getByText("Agent One", { exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Agent Two" })).toBeVisible();
  await expect.poll(() => requests.at(-1)).toBeNull();

  const agentFilter = page.locator(".ant-select").first();
  await agentFilter.click();
  const agentDropdown = page.locator(".ant-select-dropdown:visible");
  await agentDropdown.getByText("Agent One", { exact: true }).click();
  await agentDropdown.getByText("Agent Two", { exact: true }).click();
  await expect.poll(() => requests.at(-1)).toBe("[7,9]");

  await agentFilter.hover();
  await agentFilter.locator(".ant-select-clear").click();
  await expect.poll(() => requests.at(-1)).toBeNull();
});

test("AC-003 initializes the filter from a single-element agent_ids list", async ({
  page,
}) => {
  const requests: (string | null)[] = [];
  await mockEvaluationPageApis(page, requests);

  await page.goto("http://127.0.0.1:3000/en/evaluation?agent_ids=%5B7%5D");
  await expect(
    page.getByText("Evaluation Tasks", { exact: true })
  ).toBeVisible();
  await expect.poll(() => requests.at(-1)).toBe("[7]");
});

test("AC-004 keeps an excluding filter after creating a task", async ({
  page,
}) => {
  const requests: (string | null)[] = [];
  let createPayload: Record<string, unknown> | null = null;
  await mockEvaluationPageApis(page, requests, {
    listRuns: (agentIds) => [
      {
        agent_evaluation_id: agentIds === "[9]" ? 201 : 101,
        agent_id: agentIds === "[9]" ? 9 : 7,
        agent_name: agentIds === "[9]" ? "Agent Two" : "Agent One",
        agent_version_no: 1,
        evaluation_set_name: "Regression set",
        score_overall: 0.9,
        status: "COMPLETED",
      },
    ],
    createRun: (body) => {
      createPayload = body;
      return {
        agent_evaluation_id: 102,
        agent_id: 7,
        agent_name: "Agent One",
        agent_version_no: 1,
        evaluation_set_name: "New set",
        score_overall: 0,
        status: "PENDING",
      };
    },
  });

  await page.goto("http://127.0.0.1:3000/en/evaluation");
  await expect(
    page.getByText("Evaluation Tasks", { exact: true })
  ).toBeVisible();

  const agentFilter = page.locator(".ant-select").first();
  await agentFilter.click();
  await page
    .locator(".ant-select-dropdown:visible")
    .getByText("Agent Two", { exact: true })
    .click();
  await expect.poll(() => requests.at(-1)).toBe("[9]");
  await expect(page.getByRole("cell", { name: "Agent Two" })).toBeVisible();

  await page.getByRole("button", { name: "Create Evaluation" }).click();
  const drawer = page.locator(".ant-drawer");
  await expect(drawer).toBeVisible();
  const selects = drawer.locator(".ant-select");

  await selects.nth(0).click();
  await page
    .locator(".ant-select-dropdown:visible")
    .getByText("Agent One", { exact: true })
    .click();
  await selects.nth(2).click();
  await page
    .locator(".ant-select-dropdown:visible")
    .getByText("Test Judge", { exact: true })
    .click();
  await selects.nth(3).click();
  await page
    .locator(".ant-select-dropdown:visible")
    .getByText("Test evaluator", { exact: true })
    .click();

  await drawer.getByRole("button", { name: "Start Evaluation" }).click();
  await expect.poll(() => createPayload).toMatchObject({ agent_id: 7 });
  await expect(page.getByRole("cell", { name: "Agent Two" })).toBeVisible();
  await expect(page.getByText("102", { exact: true })).toHaveCount(0);
  await expect(
    agentFilter.getByText("Agent Two", { exact: true })
  ).toBeVisible();
});
