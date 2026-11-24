// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { join } from "node:path";
import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";

journey("OPS-MONITORING-UI-D4-001", async ({ page, contract }) => {
  const tenants = [
    { tenant_id: "a", tenant_name: "运营中心" },
    { tenant_id: "b", tenant_name: "研发中心" },
  ];
  const resources = [
    { tenant_id: "a", kind: "agent", id: 1, name: "智能问答助手" },
    { tenant_id: "b", kind: "agent", id: 1, name: "研发助手" },
    { tenant_id: "a", kind: "model", id: 2, name: "文本生成模型" },
    { tenant_id: "a", kind: "mcp", id: 3, name: "知识库服务" },
    { tenant_id: "a", kind: "mcp", id: 4, name: "文件服务" },
    { tenant_id: "b", kind: "mcp", id: 5, name: "研发服务" },
  ];
  const user = {
    user_id: "monitoring-fixture",
    tenant_id: "a",
    user_email: "monitoring@nexent.test",
    user_role: "SU",
    roles: ["SU"],
    group_ids: [],
    permissions: [
      "ops.dashboard:read",
      "ops.configuration:read",
      "resource.inventory:read",
    ],
    accessibleRoutes: ["/ops/dashboard", "/ops/configuration"],
  };
  const reads: string[] = [];
  const unexpected: string[] = [];
  const listReads: Record<string, string>[] = [];
  const rankingReads: Record<string, string>[] = [];
  const modelTrendReads: Record<string, string>[] = [];
  const modelSummaryReads: Record<string, string>[] = [];
  const modelListReads: Record<string, string>[] = [];
  let overviewModelReads = 0;
  let releaseModelTrend = () => {};
  const delayedModelTrend = new Promise<void>((resolve) => {
    releaseModelTrend = resolve;
  });
  let holdOverviewScope = false;
  let releaseOverviewScope = () => {};
  const delayedOverviewScope = new Promise<void>((resolve) => {
    releaseOverviewScope = resolve;
  });
  const stats: {
    view: string;
    tenant: string | null;
    agent: string | null;
    group: string | null;
    from: string | null;
    to: string | null;
  }[] = [];
  let scenario: "normal" | "empty" | "failed" = "normal";
  let pagingFixture = false;
  let outcomeFixture = false;
  let holdMonth = false;
  let completedDelayedRequests = 0;
  let resumeSingleSummary = () => {};
  const delayedSingleSummary = new Promise<void>((resolve) => {
    resumeSingleSummary = resolve;
  });
  let resumeMonth = () => {};
  const delayedMonth = new Promise<void>((resolve) => {
    resumeMonth = resolve;
  });
  const executionStatus = {
    coverage_state: "partial",
    is_stale: false,
    data_as_of: "2026-11-23T07:08:09Z",
  };
  const tokenStatus = {
    coverage_state: "covered",
    is_stale: true,
    data_as_of: "2026-11-23T06:01:02Z",
  };
  const missing = {
    coverage_state: "uncovered",
    is_stale: false,
    data_as_of: null,
  };
  const listRows = [
    {
      tenant_id: "a",
      agent_id: 1,
      name: "support-agent",
      display_name: "智能问答助手",
      model_ids: [2],
      is_current: true,
      metrics: {
        execution_count: 17,
        succeeded_count: 13,
        failed_count: 2,
        success_rate: 13 / 15,
        avg_duration_ms: 123.45,
        avg_ttft_ms: null,
      },
      tokens: {
        total_tokens: {
          value: "9007199254740993",
          known_count: 3,
          eligible_count: 4,
          coverage_rate: 0.75,
        },
      },
      token_status: tokenStatus,
    },
    {
      tenant_id: "b",
      agent_id: 1,
      name: "research-agent",
      display_name: "研发助手",
      model_ids: [2],
      is_current: true,
      metrics: {
        execution_count: 5,
        succeeded_count: 0,
        failed_count: 2,
        success_rate: 0,
        avg_duration_ms: 0,
        avg_ttft_ms: 50,
      },
      tokens: {
        total_tokens: {
          value: "0",
          known_count: 1,
          eligible_count: 1,
          coverage_rate: 1,
        },
      },
      token_status: tokenStatus,
    },
    ...Array.from({ length: 10 }, (_, index) => ({
      tenant_id: "a",
      agent_id: index + 2,
      name: null,
      display_name: null,
      is_current: false,
      metrics: null,
      tokens: { total_tokens: null },
      token_status: missing,
    })),
  ];
  const extraRows = Array.from({ length: 23 }, (_, index) => ({
    ...listRows[0],
    agent_id: index + 30,
    name: `queue-${index}`,
    display_name: `工单助手 ${index + 1}`,
  }));
  const rankingNames = [
    "智能问答助手",
    "知识检索助手",
    "文档摘要助手",
    "合同审阅助手",
    "工单分类助手",
  ];
  const baseURL = process.env.NEXENT_BASE_URL || "http://localhost:3000";
  const fixedTime = new Date("2026-11-23T12:00:00Z");
  const dashboardUrl = new URL("/zh/ops/dashboard", baseURL).href;

  await page.setViewportSize({ width: 1600, height: 960 });
  await page.clock.setFixedTime(fixedTime);
  await page.context().addCookies([
    {
      name: "nexent_token_expires_at",
      value: String(Math.max(Date.now(), fixedTime.getTime()) / 1000 + 3600),
      url: baseURL,
    },
  ]);
  await page.addInitScript(() =>
    localStorage.setItem(
      "user_info",
      JSON.stringify({ id: "monitoring-fixture", tenantId: "a", role: "SU" }),
    ),
  );
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const { pathname, searchParams } = new URL(request.url());
    const tenantId = searchParams.get("tenant_id");
    let json: unknown = {};
    if (pathname === "/api/user/current_user_info") {
      json = { data: { user } };
    } else if (pathname === "/api/platform/quota/overview") {
      json = { tenants: [] };
    } else if (pathname === "/api/tenant_config/deployment_version") {
      json = {
        deployment_version: "enterprise",
        app_version: "test",
        status: "success",
      };
    } else if (pathname === "/api/ops/scope") {
      reads.push(`scope:${tenantId ?? "*"}`);
      if (holdOverviewScope && tenantId === "b") await delayedOverviewScope;
      json = {
        data: {
          tenant_id: tenantId,
          scope: tenantId ? "tenant" : "all_tenants",
        },
      };
    } else if (pathname === "/api/tenants/tenant-list") {
      reads.push("tenants");
      json = { data: tenants, page: 1, page_size: 100, total: tenants.length };
    } else if (pathname === "/api/ops/resources") {
      reads.push(`resources:${tenantId ?? "*"}`);
      if (searchParams.has("start_date") || searchParams.has("end_date"))
        unexpected.push("dated resource inventory");
      const items = resources.filter(
        (row) => !tenantId || row.tenant_id === tenantId,
      );
      json = { data: { items, total: items.length } };
    } else if (pathname === "/api/groups/list") {
      const tenant: string | undefined = request.postDataJSON()?.tenant_id;
      reads.push(`groups:${tenant}`);
      const data = [
        {
          group_id: tenant === "a" ? 10 : 20,
          group_name: tenant === "a" ? "一线运营组" : "研发组",
        },
      ];
      if (!tenant) unexpected.push("group request without tenant");
      json = { data, total: data.length };
    } else if (pathname === "/api/skills") {
      reads.push(`skills:${tenantId ?? "*"}`);
      if (!tenantId) unexpected.push("Skill request without tenant");
      json = { skills: [{ skill_id: 7, name: "文档摘要", source: "local" }] };
    } else if (pathname === "/api/mcp/tools") {
      const service = searchParams.get("mcp_id");
      reads.push(`tools:${service}`);
      if (service !== "3" && service !== "4")
        unexpected.push(`tools:${service}`);
      json = {
        status: "success",
        tools: [{ name: service === "3" ? "语义检索" : "查阅文件" }],
      };
    } else if (
      pathname === "/api/ops/v1/monitoring/models" &&
      request.method() === "GET"
    ) {
      modelListReads.push(Object.fromEntries(searchParams));
      const modelId = searchParams.get("model_id");
      const search = searchParams.get("search")?.toLowerCase() ?? "";
      const rows = [
        ...(tenantId === "b"
          ? []
          : Array.from({ length: 12 }, (_, i) => ({
              tenant_id: "a",
              model_id: i + 2,
              display_name: i === 0 ? "文本生成模型" : `向量模型 ${i}`,
              model_name: `model-${i + 2}`,
              model_factory: "fixture",
              model_type: i === 0 ? "llm" : "embedding",
              connect_status: "available",
              metrics: {
                request_count: 100 + i,
                error_rate: 0,
                avg_duration_ms: 1200,
                avg_ttft_ms: 100,
                total_tokens: {
                  value: (9007199254740989n + BigInt(i)).toString(),
                  known_count: 100 + i,
                  eligible_count: 100 + i,
                  coverage_rate: 1,
                },
                avg_generation_rate: 42,
              },
            }))),
        ...(tenantId === "a"
          ? []
          : [
              {
                tenant_id: "b",
                model_id: 2,
                display_name: "历史文本模型",
                model_name: "historical-model",
                model_factory: "fixture",
                model_type: "llm",
                connect_status: null,
                metrics: null,
              },
            ]),
      ].filter(
        (row) =>
          (!modelId || String(row.model_id) === modelId) &&
          row.display_name.toLowerCase().includes(search),
      );
      const metric = searchParams.get("sort_by") ?? "request_count";
      const descending = searchParams.get("descending") !== "false";
      const value = (row: (typeof rows)[number]) =>
        metric === "total_tokens"
          ? BigInt(row.metrics?.total_tokens.value ?? "0")
          : BigInt(row.metrics?.request_count ?? 0);
      rows.sort((left, right) => {
        if (!left.metrics || !right.metrics)
          return Number(!left.metrics) - Number(!right.metrics);
        const a = value(left);
        const b = value(right);
        return (descending ? -1 : 1) * (a < b ? -1 : Number(a > b));
      });
      const size = Number(searchParams.get("page_size"));
      const start = (Number(searchParams.get("page")) - 1) * size;
      json = {
        ...executionStatus,
        data: { items: rows.slice(start, start + size), total: rows.length },
      };
    } else if (
      pathname === "/api/ops/v1/monitoring/models/summary" &&
      request.method() === "GET"
    ) {
      modelSummaryReads.push(Object.fromEntries(searchParams));
      const single = searchParams.has("model_id");
      const grouped = searchParams.has("group_ids");
      const requests =
        (single ? 3050 : grouped ? 7010 : 8010) +
        (searchParams.get("start_date") === "2026-11-17" ? 10 : 0);
      const eligible = single ? 2000 : 5000;
      json = {
        ...executionStatus,
        data: {
          current_model_count: 1,
          request_count: requests,
          total_tokens: {
            value: single ? "8253321" : "9007199254740993",
            known_count: requests - 10,
            eligible_count: requests,
            coverage_rate: (requests - 10) / requests,
          },
          error_count: 10,
          error_eligible_count: eligible,
          error_rate: 10 / eligible,
        },
      };
    } else if (
      pathname === "/api/ops/v1/monitoring/models/trends" &&
      request.method() === "GET"
    ) {
      modelTrendReads.push(Object.fromEntries(searchParams));
      const start = searchParams.get("start_date");
      const end = searchParams.get("end_date");
      if (tenantId === null && start === "2026-11-17") await delayedModelTrend;
      if (tenantId === "b" && start === "2026-11-07") {
        await route.fulfill({
          status: 422,
          json: { detail: "Controlled Model query failure" },
        });
        return;
      }
      const unavailable = tenantId === "b";
      const data = [];
      for (
        const day = new Date(`${start}T00:00Z`);
        day <= new Date(`${end}T00:00Z`);
        day.setUTCDate(day.getUTCDate() + 1)
      ) {
        const index = data.length % 7;
        const count = unavailable
          ? null
          : [2500, 1200, 1800, 0, 2700, 3600, 1600][index];
        const eligible = count === null ? null : count ? count - 3 : 0;
        const errors =
          count === null ? null : count ? [3, 2, 6, 0, 5, 2, 8][index] : 0;
        data.push({
          statistic_date: day.toISOString().slice(0, 10),
          request_count: count,
          error_count: errors,
          error_eligible_count: eligible,
          error_rate: eligible && errors !== null ? errors / eligible : null,
          total_tokens:
            count === null
              ? null
              : {
                  value: count
                    ? String(1400000 + ((index * 451000) % 1200000))
                    : "0",
                  known_count: count,
                  eligible_count: count,
                  coverage_rate: count ? 1 : null,
                },
        });
      }
      json = { ...(unavailable ? missing : tokenStatus), data };
    } else if (
      pathname === "/api/ops/v1/monitoring/agents/rankings" &&
      request.method() === "GET"
    ) {
      rankingReads.push(Object.fromEntries(searchParams));
      const metric = searchParams.get("metric");
      if (
        searchParams.has("agent_id") ||
        !["execution_count", "success_rate", "total_tokens"].includes(
          metric ?? "",
        )
      )
        unexpected.push(`rankings:${searchParams}`);
      const token = metric === "total_tokens";
      const names = tenantId === "b" ? ["研发助手"] : rankingNames;
      const data = names.map((display_name, index) => ({
        tenant_id: tenantId ?? "a",
        agent_id: index + 1,
        display_name,
        metrics: {
          execution_count: [1461, 1350, 1104, 987, 816][index],
          success_rate: [0.991, 0.991, 0.977, 0.964, 0.931][index],
          ...(metric === "success_rate" && {
            success_sample_count: [151, 699, 857, 715, 432][index],
          }),
        },
        ...(token && {
          tokens: {
            total_tokens: {
              value: (9007199254740993n - BigInt(index)).toString(),
              known_count: 3,
              eligible_count: 4,
              coverage_rate: 0.75,
            },
          },
          token_status: tokenStatus,
        }),
      }));
      json = {
        ...executionStatus,
        data: scenario === "empty" ? [] : data,
        ...(token && { token_status: tokenStatus }),
      };
    } else if (
      pathname === "/api/ops/v1/monitoring/agents" &&
      request.method() === "GET"
    ) {
      listReads.push(Object.fromEntries(searchParams));
      const search = searchParams.get("search")?.toLowerCase() ?? "";
      if (scenario === "failed" || search === "error") {
        await route.fulfill({
          status: 422,
          json: { detail: "Controlled list failure" },
        });
        return;
      }
      const agent = searchParams.get("agent_id");
      const metric = searchParams.get("sort_by");
      const direction = searchParams.get("descending") === "true" ? -1 : 1;
      const value = (row: (typeof listRows)[number]) =>
        metric === "total_tokens"
          ? BigInt(row.tokens.total_tokens?.value ?? "-1")
          : BigInt(row.metrics?.execution_count ?? -1);
      const items =
        scenario === "empty"
          ? []
          : (pagingFixture ? [...listRows, ...extraRows] : listRows)
              .filter(
                (row) =>
                  (!tenantId || row.tenant_id === tenantId) &&
                  (!agent || String(row.agent_id) === agent),
              )
              .filter(
                (row) =>
                  !search ||
                  [row.name, row.display_name].some((name) =>
                    name?.toLowerCase().includes(search),
                  ),
              )
              .sort((a, b) => {
                const left = value(a);
                const right = value(b);
                if (left === right) return 0;
                if (left === -1n || right === -1n) return left === -1n ? 1 : -1;
                return left < right ? -direction : direction;
              });
      const size = Number(searchParams.get("page_size"));
      const start = (Number(searchParams.get("page")) - 1) * size;
      json = {
        ...executionStatus,
        token_status: tokenStatus,
        data: {
          items: items.slice(start, start + size),
          total: items.length,
          current_agent_count: items.filter((row) => row.is_current).length,
        },
      };
    } else if (
      /^\/api\/ops\/v1\/monitoring\/agents\/(summary|trends)$/.test(pathname) &&
      request.method() === "GET"
    ) {
      const scope = {
        view: pathname.endsWith("/summary") ? "summary" : "trends",
        tenant: tenantId,
        agent: searchParams.get("agent_id"),
        group: searchParams.get("group_ids"),
        from: searchParams.get("start_date"),
        to: searchParams.get("end_date"),
      };
      stats.push(scope);
      const delayed =
        holdMonth &&
        scope.from === "2026-10-25" &&
        scope.agent === null &&
        scope.view === "trends";
      const summaryFailure =
        holdMonth &&
        scope.from === "2026-10-25" &&
        scope.agent === null &&
        scope.view === "summary";
      const delayedSummary =
        holdMonth &&
        scope.from === "2026-10-25" &&
        scope.agent === "1" &&
        scope.view === "summary";
      if (delayed) await delayedMonth;
      if (delayedSummary) await delayedSingleSummary;
      if (summaryFailure || scenario === "failed") {
        await route.fulfill({
          status: 422,
          json: { detail: "Controlled failed read" },
        });
        return;
      }
      const empty = scenario === "empty";
      const single = scope.agent !== null;
      const outcomes = outcomeFixture && single;
      const metrics = {
        execution_count: empty
          ? null
          : delayed
            ? 700001
            : single
              ? outcomes
                ? 1047
                : 0
              : scope.group
                ? 33
                : 26847,
        succeeded_count: empty ? null : single ? (outcomes ? 750 : 0) : 977,
        failed_count: empty ? null : single ? (outcomes ? 250 : 0) : 23,
        success_rate: empty ? null : single ? (outcomes ? 0.75 : null) : 0.977,
      };
      const tokens = {
        total_tokens: empty
          ? null
          : {
              value: single
                ? outcomes
                  ? "1467232"
                  : "0"
                : scope.group
                  ? "9007199254740993"
                  : "25025913",
              known_count: single ? 0 : 3,
              eligible_count: single ? 0 : 4,
              coverage_rate: single ? null : 0.75,
            },
      };
      const days = [];
      for (
        const day = new Date(`${scope.from}T00:00Z`);
        day <= new Date(`${scope.to}T00:00Z`);
        day.setUTCDate(day.getUTCDate() + 1)
      ) {
        const index = days.length;
        const gap = !single && index === 2;
        days.push({
          ...metrics,
          execution_count: gap
            ? null
            : single
              ? outcomes
                ? 104 + ((index * 43) % 129)
                : 0
              : [1700, 1820, 1420, 2120, 2410, 2310, 2390][index % 7],
          success_rate:
            gap || (single && !outcomes)
              ? null
              : [0.89, 0.92, 0.81, 0.96, 1, 0.94, 0.97][index % 7],
          statistic_date: day.toISOString().slice(0, 10),
          coverage_state: gap ? "uncovered" : "covered",
          tokens: gap
            ? { total_tokens: null }
            : single && !outcomes
              ? tokens
              : {
                  total_tokens: {
                    ...tokens.total_tokens,
                    value: String(1500000 + (index % 7) * 142000),
                  },
                },
          token_status: gap ? missing : tokenStatus,
        });
      }
      json = {
        ...(empty ? missing : executionStatus),
        token_status: empty ? missing : tokenStatus,
        ...(scope.view === "summary"
          ? { data: metrics, tokens }
          : { data: empty ? [] : days }),
      };
      if (delayed) {
        await route.fulfill({ json }).catch(() => {});
        completedDelayedRequests += 1;
        return;
      }
    } else if (pathname.startsWith("/api/ops/v1/monitoring/")) {
      unexpected.push(`${request.method()} ${pathname}`);
    }
    await route.fulfill({ json });
  });
  contract.deferCleanup(async () => {
    releaseModelTrend();
    releaseOverviewScope();
    resumeMonth();
    resumeSingleSummary();
    await page.close();
  });

  const tab = (name: string) => page.getByRole("tab", { name, exact: true });
  const dropdown = page.locator(".ant-select-dropdown:visible");
  const option = (name: string) =>
    dropdown
      .locator(".ant-select-item-option")
      .getByText(name, { exact: true });
  const picker = page.locator(".ant-picker-dropdown:visible");
  const placeholder = page.getByText("统计数据暂未接入", { exact: true });
  const heading = page.getByRole("heading", { name: "监控", exact: true });
  const allTools = page
    .getByRole("tabpanel", { name: "MCP" })
    .getByText("全部工具", { exact: true });
  const select = (label: string) =>
    page.getByRole("combobox", { name: label, exact: true });
  const choose = async (label: string, name: string) => {
    await select(label).click();
    await option(name).click();
  };
  const screenshot = async (name: string) => {
    await heading.click();
    await expect(dropdown).toHaveCount(0);
    await page.screenshot({
      path: join(contract.caseDir, `monitoring-${name}.png`),
      animations: "disabled",
      style: "nextjs-portal { visibility: hidden; }",
    });
  };

  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await page.goto(dashboardUrl);
      await expect(heading).toBeVisible();
      await expect(select("租户")).toBeEnabled();
    },
  );
  const [
    dates,
    scope,
    tools,
    metrics,
    states,
    details,
    charts,
    modelDrilldown,
  ] = contract.expectedIds("steps");
  await contract.step(dates, async () => {
    await expect(page.getByRole("tab")).toHaveText([
      "概览",
      "智能体",
      "模型",
      "Skill",
      "MCP",
    ]);
    await expect(select("用户组")).toHaveCount(0);
    await expect(select("智能体")).toHaveCount(0);
    const cards = page.locator('dl[aria-label="信息概览"]');
    const agentTrend = page.getByRole("region", { name: "智能体执行次数" });
    const modelTrend = page.getByRole("region", { name: "模型请求数" });
    const inventoryReads = () =>
      reads.filter((entry) => entry.startsWith("resources:"));
    const chart = (panel: typeof agentTrend) =>
      panel.locator(".recharts-area-curve");
    await expect(cards.locator("dd")).toHaveText([
      "2",
      "1",
      "暂未接入",
      "暂未接入",
    ]);
    await expect(
      page.getByRole("region", { name: "MCP 工具调用量" }),
    ).toHaveText(/暂未接入/);
    await expect(
      page.getByRole("region", { name: "Skill 使用次数" }),
    ).toHaveText(/暂未接入/);
    await expect(page.getByText("2026-11-17 – 2026-11-23")).toBeVisible();
    await expect(modelTrend).toHaveAttribute("aria-busy", "true");
    await expect(chart(agentTrend)).toBeVisible();
    await expect(chart(agentTrend)).toHaveAttribute("d", /M.+M/);
    releaseModelTrend();
    await expect(chart(modelTrend)).toBeVisible();
    await expect(
      modelTrend.getByText("数据滞后", { exact: true }),
    ).toBeVisible();
    await modelTrend.locator("circle.recharts-area-dot").nth(3).hover();
    await expect(
      modelTrend.getByText("模型请求数 · 0", { exact: true }),
    ).toBeVisible();
    await page.setViewportSize({ width: 1600, height: 1040 });
    await screenshot("overview");
    await page.setViewportSize({ width: 1600, height: 960 });

    const beforeDate = inventoryReads().length;
    await page.getByText("近一个月", { exact: true }).click();
    await expect(page.getByText("2026-10-25 – 2026-11-23")).toBeVisible();
    await expect
      .poll(() => modelTrendReads.at(-1))
      .toEqual({
        start_date: "2026-10-25",
        end_date: "2026-11-23",
      });
    await expect
      .poll(() => stats.at(-1))
      .toEqual({
        view: "trends",
        tenant: null,
        from: "2026-10-25",
        to: "2026-11-23",
        group: null,
        agent: null,
      });
    await expect(cards.locator("dd")).toHaveText([
      "2",
      "1",
      "暂未接入",
      "暂未接入",
    ]);
    expect(inventoryReads()).toHaveLength(beforeDate);

    holdOverviewScope = true;
    await choose("租户", "研发中心");
    await expect(cards.locator("dd")).toHaveText([
      "加载中",
      "加载中",
      "暂未接入",
      "暂未接入",
    ]);
    await expect(chart(agentTrend)).toHaveCount(0);
    await expect(chart(modelTrend)).toHaveCount(0);
    releaseOverviewScope();
    holdOverviewScope = false;
    await expect(cards.locator("dd")).toHaveText([
      "1",
      "0",
      "暂未接入",
      "暂未接入",
    ]);
    await expect(page.getByText("2026-10-25 – 2026-11-23")).toBeVisible();
    await expect
      .poll(() => modelTrendReads.at(-1))
      .toEqual({
        start_date: "2026-10-25",
        end_date: "2026-11-23",
        tenant_id: "b",
      });
    await expect
      .poll(() => stats.at(-1))
      .toMatchObject({
        view: "trends",
        tenant: "b",
        from: "2026-10-25",
        to: "2026-11-23",
      });
    await expect(modelTrend.locator(".ant-empty-description")).toHaveText(
      "暂无数据",
    );
    await expect(chart(modelTrend)).toHaveCount(0);
    expect(inventoryReads().at(-1)).toBe("resources:b");

    const beforeCustom = modelTrendReads.length;
    const beforeCustomInventory = inventoryReads().length;
    await page.getByText("自定义", { exact: true }).click();
    await expect(modelTrend.locator(".ant-empty-description")).toHaveText(
      "请选择起止日期",
    );
    expect(modelTrendReads).toHaveLength(beforeCustom);
    await page.getByPlaceholder("请选择开始日期").click();
    await picker.locator('[title="2026-11-07"]').click();
    await picker.locator('[title="2026-11-12"]').click();
    await expect(page.getByText("2026-11-07 – 2026-11-12")).toBeVisible();
    await expect(modelTrend.getByRole("alert")).toHaveText("加载失败，请重试");
    await expect(chart(agentTrend)).toBeVisible();
    await expect(cards.locator("dd")).toHaveText([
      "1",
      "0",
      "暂未接入",
      "暂未接入",
    ]);
    expect(inventoryReads()).toHaveLength(beforeCustomInventory);
    await choose("租户", "全部租户");
    await expect(chart(modelTrend)).toBeVisible();
    await expect(cards.locator("dd")).toHaveText([
      "2",
      "1",
      "暂未接入",
      "暂未接入",
    ]);
    overviewModelReads = modelTrendReads.length;
  });
  await contract.step(scope, async () => {
    await tab("智能体").click();
    await expect(select("用户组")).toBeDisabled();
    await expect(page.getByText("请先选择租户", { exact: true })).toBeVisible();
    await tab("Skill").click();
    await expect(select("Skill")).toBeDisabled();
    await tab("智能体").click();
    await choose("租户", "运营中心");
    await choose("用户组", "一线运营组");
    await choose("智能体", "智能问答助手");
    await expect(
      page.getByRole("heading", { name: "智能问答助手 · 运营中心" }),
    ).toBeVisible();
    await screenshot("agent");

    await tab("模型").click();
    await expect(page.getByText("一线运营组", { exact: true })).toBeVisible();
    await expect(page.getByPlaceholder("请选择开始日期")).toHaveValue(
      "2026-11-07",
    );
    const modelDetails = page.getByRole("region", { name: "模型明细" });
    const modelSearchButton = modelDetails
      .getByRole("columnheader", { name: /名称/ })
      .getByRole("button", { name: "搜索列表中的主名称" });
    const modelSearch = page.getByRole("searchbox", {
      name: "搜索列表中的主名称",
    });
    const agentReads = listReads.length;
    await modelDetails.locator(".ant-pagination-item-2").click();
    await expect.poll(() => modelListReads.at(-1)).toMatchObject({ page: "2" });
    await modelSearchButton.click();
    await expect(modelSearch).toBeFocused();
    await modelSearch.fill("文本生成");
    await modelSearch.press("Enter");
    await expect
      .poll(() => modelListReads.at(-1))
      .toMatchObject({
        page: "1",
        search: "文本生成",
        tenant_id: "a",
        group_ids: "10",
        start_date: "2026-11-07",
        end_date: "2026-11-12",
      });
    await expect(modelDetails.locator("tbody tr[data-row-key]")).toHaveCount(1);
    await modelSearch.locator("..").locator(".ant-input-clear-icon").click();
    await expect(modelSearch).toHaveValue("");
    await expect(modelDetails.locator("tbody tr[data-row-key]")).toHaveCount(
      10,
    );
    expect(modelListReads.at(-1)).not.toHaveProperty("search");
    await modelSearch.fill("向量模型");
    await modelSearch.press("Enter");
    await modelSearch.press("Escape");
    await expect(modelSearchButton).toBeFocused();
    const modelRows = modelDetails.locator("tbody tr[data-row-key]");
    const tokenColumn = modelDetails.getByRole("columnheader", {
      name: /Token 数/,
    });
    await expect(modelRows.first()).toContainText("向量模型 11");
    await modelDetails.locator(".ant-pagination-item-2").click();
    await expect(modelRows.first()).toContainText("向量模型 1");
    const beforeSort = [modelSummaryReads.length, modelTrendReads.length];
    const sortedScope = {
      search: "向量模型",
      page_size: "10",
      sort_by: "total_tokens",
      tenant_id: "a",
      group_ids: "10",
      start_date: "2026-11-07",
      end_date: "2026-11-12",
    };
    await tokenColumn.click();
    await expect(tokenColumn).toHaveAttribute("aria-sort", "descending");
    await expect
      .poll(() => modelListReads.at(-1))
      .toMatchObject({ ...sortedScope, page: "1", descending: "true" });
    await expect(modelRows.first()).toContainText("向量模型 11");
    await modelDetails.locator(".ant-pagination-item-2").click();
    await expect
      .poll(() => modelListReads.at(-1))
      .toMatchObject({ ...sortedScope, page: "2", descending: "true" });
    await expect(modelRows).toHaveCount(1);
    await expect(modelRows.first()).toContainText("向量模型 1");
    await tokenColumn.click();
    await expect(tokenColumn).toHaveAttribute("aria-sort", "ascending");
    await expect
      .poll(() => modelListReads.at(-1))
      .toMatchObject({ ...sortedScope, page: "1", descending: "false" });
    await expect(
      modelRows.first().getByText("向量模型 1", { exact: true }),
    ).toBeVisible();
    expect([modelSummaryReads.length, modelTrendReads.length]).toEqual(
      beforeSort,
    );
    await modelSearchButton.click();
    await modelSearch.locator("..").locator(".ant-input-clear-icon").click();
    await modelSearch.press("Escape");
    expect(listReads).toHaveLength(agentReads);
    const modelCards = page.locator('dl[aria-label="模型指标概览"]');
    const modelCard = (name: string) =>
      modelCards
        .locator("dt")
        .filter({ hasText: name })
        .locator("..")
        .locator("dd");
    const modelCalls = page.getByRole("region", {
      name: "调用趋势",
      exact: true,
    });
    const modelErrors = page.getByRole("region", {
      name: "错误率趋势",
      exact: true,
    });
    await expect(modelCard("当前模型数").locator("strong")).toHaveText("1");
    await expect(modelCard("模型请求数").locator("strong")).toHaveText("7,010");
    await expect(modelCard("Token 消耗量")).toContainText("9,007.2 万亿");
    await expect(modelErrors).not.toContainText("纳入统计");
    await expect(modelErrors).not.toContainText("区间错误率");
    await expect(modelErrors.getByRole("radio")).toHaveCount(0);
    await expect(modelErrors.locator(".recharts-area-curve")).toHaveAttribute(
      "d",
      /M.+M/,
    );
    await expect(modelCalls.locator(".recharts-area-curve")).toBeVisible();
    const beforeMetric = modelTrendReads.length;
    await modelCalls.getByText("Token", { exact: true }).click();
    await expect(
      modelCalls.getByRole("group", { name: "Token", exact: true }),
    ).toBeVisible();
    expect(modelTrendReads).toHaveLength(beforeMetric);
    await screenshot("model-all-metrics");

    await page.getByText("近七天", { exact: true }).click();
    await expect(modelCard("模型请求数").locator("strong")).toHaveText("7,020");
    await expect(modelCard("当前模型数").locator("strong")).toHaveText("1");
    await choose("用户组", "全部用户组");
    await expect(modelCard("模型请求数").locator("strong")).toHaveText("8,020");
    await expect(modelCard("当前模型数").locator("strong")).toHaveText("1");
    await choose("用户组", "一线运营组");
    await page.getByText("自定义", { exact: true }).click();
    await modelRows
      .filter({ hasText: "文本生成模型" })
      .getByRole("button", { name: "查看统计" })
      .click();
    await expect(
      page.getByRole("heading", { name: "文本生成模型 · 运营中心" }),
    ).toBeFocused();
    await expect(
      modelDetails.getByRole("button", { name: "查看统计" }),
    ).toBeDisabled();
    await expect
      .poll(() => modelListReads.at(-1))
      .toMatchObject({ tenant_id: "a", model_id: "2", page: "1" });
    await expect(modelCard("当前模型数")).toHaveCount(0);
    await expect(modelCard("模型请求数").locator("strong")).toHaveText("3,050");
    await expect(modelErrors).not.toContainText("区间错误率");
    await expect(modelCalls.locator(".recharts-area-curve")).toBeVisible();
    await expect(modelCard("Token 消耗量").locator("strong")).toHaveText(
      "825.33 万",
    );
    const statusText = page.getByText(
      /覆盖完整|部分覆盖|数据滞后|数据截至|请求覆盖/,
    );
    await expect(statusText).toHaveCount(0);
    await expect(modelCards.getByRole("button")).toHaveCount(0);
    for (const name of ["模型请求数", "Token 消耗量"]) {
      await modelCard(name).locator("strong").hover();
      await expect(page.getByRole("tooltip")).toHaveCount(0);
    }
    await page.setViewportSize({ width: 1600, height: 1080 });
    await screenshot("model-clean-display");
    await modelCalls.locator("circle.recharts-area-dot").nth(2).hover();
    await expect(
      modelCalls.getByText("Token · 2,302,000 tokens", { exact: true }),
    ).toBeVisible();
    await expect(statusText).toHaveCount(0);
    await modelErrors.locator("circle.recharts-area-dot").nth(2).hover();
    await expect(
      modelErrors.getByText("错误率 · 0.33%", { exact: true }),
    ).toBeVisible();
    await expect(
      modelErrors.getByText("6 次失败 / 1,797 次纳入统计", { exact: true }),
    ).toBeVisible();
    await expect(statusText).toHaveCount(0);
    await page.setViewportSize({ width: 1600, height: 960 });
    const modelRefresh = page.getByRole("button", {
      name: "刷新",
      exact: true,
    });
    const refetch = {
      tenant_id: "a",
      model_id: "2",
      group_ids: "10",
      start_date: "2026-11-07",
      end_date: "2026-11-12",
    };
    const beforeRefresh = [
      modelSummaryReads.length,
      modelTrendReads.length,
      modelListReads.length,
    ];
    await modelRefresh.click();
    for (const [index, reads] of [
      modelSummaryReads,
      modelTrendReads,
      modelListReads,
    ].entries()) {
      await expect
        .poll(() => reads.slice(beforeRefresh[index]))
        .toEqual([expect.objectContaining(refetch)]);
    }
    await tab("Skill").click();
    await choose("Skill", "文档摘要");
    await screenshot("skill");
    await tab("模型").click();
    await choose("租户", "研发中心");
    await expect(page.getByText("全部用户组", { exact: true })).toBeVisible();
    await expect(page.getByText("全部模型", { exact: true })).toBeVisible();
    await tab("智能体").click();
    await expect(
      page.getByRole("heading", { name: "全部智能体 · 研发中心" }),
    ).toBeVisible();
    await expect(page.getByPlaceholder("请选择结束日期")).toHaveValue(
      "2026-11-12",
    );
    await select("用户组").click();
    await expect(option("研发组")).toBeVisible();
    await expect(option("一线运营组")).toHaveCount(0);
    await page.keyboard.press("Escape");
  });
  await contract.step(tools, async () => {
    await tab("MCP").click();
    await choose("MCP", "研发服务");
    await expect(select("MCP 工具")).toBeDisabled();
    await choose("租户", "运营中心");
    await choose("MCP", "知识库服务");
    await choose("MCP 工具", "语义检索");
    await screenshot("mcp");
    await choose("MCP", "文件服务");
    await expect(allTools).toBeVisible();
    await select("MCP 工具").click();
    await expect(option("查阅文件")).toBeVisible();
    await expect(option("语义检索")).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("button", { name: "刷新", exact: true }),
    ).toBeEnabled();
    const start = reads.length;
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await expect
      .poll(() => reads.slice(start).sort())
      .toEqual(["groups:a", "resources:a", "scope:a", "tenants", "tools:4"]);
  });
  const overview = page.locator('dl[aria-label="智能体指标概览"]');
  const card = (title: string) =>
    overview.getByText(title, { exact: true }).locator("..").locator("dd");
  const trend = page.getByRole("region", { name: "调用趋势", exact: true });
  const table = page.getByRole("region", { name: "智能体明细", exact: true });
  const displayNameSearch = "搜索展示名称或内部名称";
  const searchTrigger = table
    .getByRole("columnheader", { name: /展示名称/ })
    .getByRole("button", { name: displayNameSearch });
  const detailSearch = page.getByRole("searchbox", { name: displayNameSearch });
  const openDetailSearch = async () => {
    if ((await searchTrigger.getAttribute("aria-expanded")) !== "true")
      await searchTrigger.click();
    await expect(detailSearch).toBeVisible();
  };
  const searchDetails = async (name: string) => {
    await openDetailSearch();
    await detailSearch.fill(name);
    await detailSearch.press("Enter");
  };
  const ranking = page.getByRole("region", { name: "智能体排行", exact: true });
  const distribution = page.getByRole("region", {
    name: "调用结果分布",
    exact: true,
  });
  const curve = trend.locator(".recharts-area-curve");
  const refresh = page.getByRole("button", { name: "刷新", exact: true });
  const chooseMetric = (name: string) =>
    trend.getByText(name, { exact: true }).click();
  await contract.step(metrics, async () => {
    await tab("智能体").click();
    await expect(card("当前智能体总数")).toContainText("1");
    await expect(card("调用量").locator("strong")).toHaveText("26,847");
    await expect(card("调用成功率")).toContainText("97.7%");
    await expect(card("调用成功率")).toContainText("1,000 次纳入统计");
    await expect(card("Token 消耗量").locator("strong")).toHaveText(
      "2,502.59 万",
    );
    await expect(card("Token 消耗量")).not.toContainText("请求覆盖");
    await card("Token 消耗量").locator("strong").hover();
    const agentTokenTooltip = page
      .getByRole("tooltip")
      .filter({ hasText: "25,025,913 tokens" });
    await expect(agentTokenTooltip).toContainText("请求覆盖 3 / 4（75%）");
    await heading.hover();
    await expect(
      page
        .getByText("数据截至 2026-11-23 07:08:09 UTC", { exact: true })
        .first(),
    ).toBeVisible();
    await expect(
      trend.getByText("数据截至 2026-11-23 06:01:02 UTC", { exact: true }),
    ).toBeVisible();
    await expect(trend.getByText("数据滞后", { exact: true })).toBeVisible();
    await expect(curve).toBeVisible();
    await expect(curve).toHaveAttribute("d", /M.+M/);
    await screenshot("agent-token-trend");

    const beforeToggle = stats.length;
    await chooseMetric("调用量");
    await expect(
      trend.getByRole("group", { name: "调用量", exact: true }),
    ).toBeVisible();
    await screenshot("agent-execution-trend");
    await chooseMetric("成功率");
    await expect(
      trend.getByRole("group", { name: "成功率", exact: true }),
    ).toBeVisible();
    await screenshot("agent-success-trend");
    expect(stats).toHaveLength(beforeToggle);

    const inventoryReads = reads.filter((key) =>
      key.startsWith("resources:"),
    ).length;
    await choose("用户组", "一线运营组");
    await expect(card("调用量").locator("strong")).toHaveText("33");
    await expect(card("Token 消耗量").locator("strong")).toHaveText(
      "9,007.2 万亿",
    );
    await page.getByText("近七天", { exact: true }).click();
    await expect(card("调用量").locator("strong")).toHaveText("33");
    await expect(card("当前智能体总数").locator("strong")).toHaveText("1");
    expect(reads.filter((key) => key.startsWith("resources:"))).toHaveLength(
      inventoryReads,
    );
    const beforeRefresh = stats.length;
    const beforeListRefresh = listReads.length;
    await refresh.click();
    await expect
      .poll(() =>
        stats
          .slice(beforeRefresh)
          .map((item) => item.view)
          .sort(),
      )
      .toEqual(["summary", "trends"]);
    await expect
      .poll(() => listReads.slice(beforeListRefresh))
      .toEqual([
        expect.objectContaining({
          start_date: "2026-11-17",
          end_date: "2026-11-23",
          tenant_id: "a",
          group_ids: "10",
        }),
      ]);
    for (const request of stats.slice(beforeRefresh)) {
      expect(request).toMatchObject({
        tenant: "a",
        agent: null,
        group: "10",
        from: "2026-11-17",
        to: "2026-11-23",
      });
    }
  });
  await contract.step(states, async () => {
    holdMonth = true;
    const beforeMonth = stats.length;
    await page.getByText("近一个月", { exact: true }).click();
    await expect
      .poll(
        () =>
          stats
            .slice(beforeMonth)
            .filter((item) => item.from === "2026-10-25" && !item.agent).length,
      )
      .toBe(2);
    await expect(
      page.getByText("智能体指标加载失败", { exact: true }),
    ).toBeVisible();
    await expect(card("调用量").locator("strong")).toHaveText("—");
    await expect(overview).toHaveAttribute("aria-busy", "false");
    await expect(trend).toHaveAttribute("aria-busy", "true");
    await choose("智能体", "智能问答助手");
    await expect(card("当前智能体总数")).toHaveCount(0);
    await expect(
      trend.getByText("所选指标暂无可用值", { exact: true }),
    ).toBeVisible();
    await expect(trend).toHaveAttribute("aria-busy", "false");
    await expect(overview).toHaveAttribute("aria-busy", "true");
    await expect(card("调用量").locator("strong")).toHaveText("加载中");
    resumeSingleSummary();
    await expect(card("调用量").locator("strong")).toHaveText("0");
    await expect(card("调用成功率").locator("strong")).toHaveText("—");
    await expect(card("Token 消耗量").locator("strong")).toHaveText("0");
    await expect(
      distribution.getByText("暂无纳入统计的调用结果", { exact: true }),
    ).toBeVisible();
    await expect(distribution.locator("dd")).toHaveText("0");
    await expect(
      trend.getByText("所选指标暂无可用值", { exact: true }),
    ).toBeVisible();
    resumeMonth();
    holdMonth = false;
    await expect.poll(() => completedDelayedRequests).toBe(1);
    await expect(card("调用量").locator("strong")).toHaveText("0");
    await screenshot("agent-single");

    scenario = "empty";
    await refresh.click();
    await expect(trend.locator(".ant-empty-description")).toHaveText(
      "暂无数据",
    );
    await expect(card("调用量").locator("strong")).toHaveText("—");
    scenario = "failed";
    await refresh.click();
    await expect(
      page.getByText("智能体指标加载失败", { exact: true }),
    ).toBeVisible();
    await expect(
      trend.getByText("调用趋势加载失败", { exact: true }),
    ).toBeVisible();
  });
  await contract.step(details, async () => {
    scenario = "normal";
    await choose("租户", "全部租户");
    await page.getByText("近七天", { exact: true }).click();
    const body = table.locator("tbody");
    const support = body.getByRole("row").filter({ hasText: "support-agent" });
    const research = body
      .getByRole("row")
      .filter({ hasText: "research-agent" });
    await expect(support.getByRole("cell").first()).toHaveText("智能问答助手");
    await expect(research.getByRole("cell").first()).toHaveText("研发助手");
    await expect(research.getByText("研发助手", { exact: true })).toHaveCSS(
      "white-space",
      "nowrap",
    );
    await expect(searchTrigger).toBeVisible();
    await expect(detailSearch).toBeHidden();
    await expect(
      support.getByRole("cell", { name: "文本生成模型", exact: true }),
    ).toBeVisible();
    await expect(
      support.getByText("9,007,199,254,740,993", { exact: true }),
    ).toBeVisible();
    await expect(
      support.getByRole("cell", { name: "123.45", exact: true }),
    ).toBeVisible();
    await expect(
      research.getByRole("cell", { name: "0%", exact: true }),
    ).toBeVisible();
    await expect(
      research.getByRole("cell", { name: "文本生成模型", exact: true }),
    ).toHaveCount(0);
    await expect(table.getByText("数据滞后", { exact: true })).toBeVisible();
    await expect(table.getByText("共 12 个", { exact: true })).toBeVisible();
    await expect(body.locator("tr[data-row-key]")).toHaveCount(10);
    const historical = body.getByRole("row").filter({ hasText: "智能体 #2" });
    await expect(
      historical.getByRole("button", { name: "查看统计" }),
    ).toBeDisabled();
    await table.screenshot({
      path: join(contract.caseDir, "monitoring-agent-details.png"),
      animations: "disabled",
    });
    await support.getByText("9,007,199,254,740,993", { exact: true }).hover();
    await expect(
      page.getByRole("tooltip").getByText("请求覆盖 3 / 4（75%）"),
    ).toBeVisible();

    const before = stats.length;
    await table.locator(".ant-pagination-item-2").click();
    await expect
      .poll(() => listReads.at(-1))
      .toMatchObject({ page: "2", page_size: "10" });
    await expect(body.locator("tr[data-row-key]")).toHaveCount(2);
    const sortToken = table.getByRole("columnheader", { name: /Token 消耗量/ });
    await sortToken.click();
    await expect
      .poll(() => listReads.at(-1))
      .toMatchObject({
        page: "1",
        sort_by: "total_tokens",
        descending: "true",
      });
    await expect(support).toBeVisible();
    await sortToken.click();
    await expect
      .poll(() => listReads.at(-1))
      .toMatchObject({
        page: "1",
        sort_by: "total_tokens",
        descending: "false",
      });
    await expect(body.getByRole("row").first()).toContainText("research-agent");

    await table.locator(".ant-pagination-item-2").click();
    await expect.poll(() => listReads.at(-1)).toMatchObject({ page: "2" });
    await openDetailSearch();
    await expect(detailSearch).toBeFocused();
    await searchDetails("智能问答");
    await expect
      .poll(() => listReads.at(-1))
      .toMatchObject({ page: "1", search: "智能问答" });
    await expect(body.getByRole("row")).toHaveCount(1);
    await expect(support).toBeVisible();
    await openDetailSearch();
    await expect(detailSearch).toHaveValue("智能问答");
    await detailSearch.locator("..").locator(".ant-input-clear-icon").click();
    await expect(detailSearch).toHaveValue("");
    await expect(research).toBeVisible();
    expect(listReads.at(-1)).not.toHaveProperty("search");
    await searchDetails("missing");
    await expect(
      table.getByText("未找到匹配的智能体", { exact: true }),
    ).toBeVisible();
    await searchDetails("error");
    await expect(
      table.getByText("智能体明细加载失败", { exact: true }),
    ).toBeVisible();
    await searchDetails("research-agent");
    await expect(research).toBeVisible();
    expect(stats).toHaveLength(before);
    await research.getByRole("button", { name: "查看统计" }).click();
    await expect(
      page.getByRole("heading", { name: "研发助手 · 研发中心" }),
    ).toBeVisible();
    await expect
      .poll(() => listReads.at(-1))
      .toMatchObject({ tenant_id: "b", agent_id: "1", page: "1" });
    await expect(research).toBeVisible();
    await expect(support).toHaveCount(0);
    await tab("MCP").click();
    await choose("租户", "运营中心");
    await choose("MCP", "文件服务");
    await page.getByText("自定义", { exact: true }).click();
  });
  await contract.step(charts, async () => {
    pagingFixture = true;
    await tab("智能体").click();
    await page.getByText("近七天", { exact: true }).click();
    const rankMetric = (name: string) =>
      ranking.getByText(name, { exact: true });
    const rankRows = ranking.getByRole("listitem");
    await expect(rankRows).toHaveCount(5);
    await expect(rankRows.first()).toContainText("1,461");
    await expect
      .poll(() => rankingReads.at(-1))
      .toMatchObject({ metric: "execution_count", tenant_id: "a" });

    await rankMetric("成功率").click();
    await expect(rankRows.nth(0)).toContainText("智能问答助手");
    await expect(rankRows.nth(0)).toContainText("99.1%");
    await expect(rankRows.nth(0)).toContainText("151 次纳入统计");
    await expect(rankRows.nth(1)).toContainText("知识检索助手");
    await expect(rankRows.nth(1)).toContainText("699 次纳入统计");
    await screenshot("agent-all-rankings");

    await rankMetric("Token").click();
    await expect(rankRows.nth(0)).toContainText("9,007,199,254,740,993");
    await expect(rankRows.nth(1)).toContainText("9,007,199,254,740,992");
    await expect(ranking.getByText("数据滞后", { exact: true })).toBeVisible();

    const tableRequest = {
      page_size: "20",
      search: "queue",
      sort_by: "total_tokens",
      descending: "true",
    };
    await table.getByRole("combobox").click();
    await dropdown.getByText(/20.*条\/页/).click();
    await table.getByRole("columnheader", { name: /Token 消耗量/ }).click();
    await searchDetails("queue");
    await expect
      .poll(() => listReads.at(-1))
      .toMatchObject({ ...tableRequest, page: "1" });
    const pageTwo = table.locator(".ant-pagination-item-2");
    await pageTwo.click();
    await expect
      .poll(() => listReads.at(-1))
      .toMatchObject({ ...tableRequest, page: "2" });

    const beforeDate = listReads.length;
    await page.getByText("近一个月", { exact: true }).click();
    await expect
      .poll(() => listReads.slice(beforeDate))
      .toEqual([
        expect.objectContaining({
          ...tableRequest,
          page: "1",
          start_date: "2026-10-25",
        }),
      ]);
    await openDetailSearch();
    await expect(detailSearch).toHaveValue("queue");
    await detailSearch.press("Escape");
    await expect(searchTrigger).toBeFocused();
    await pageTwo.click();
    await expect
      .poll(() => listReads.at(-1))
      .toMatchObject({ ...tableRequest, page: "2", start_date: "2026-10-25" });

    const beforeGroup = listReads.length;
    await choose("用户组", "一线运营组");
    await expect
      .poll(() => listReads.slice(beforeGroup))
      .toEqual([
        expect.objectContaining({
          ...tableRequest,
          page: "1",
          group_ids: "10",
        }),
      ]);
    await openDetailSearch();
    await expect(detailSearch).toHaveValue("queue");
    await detailSearch.press("Escape");
    const activeRanking = {
      metric: "total_tokens",
      tenant_id: "a",
      group_ids: "10",
      start_date: "2026-10-25",
    };
    await expect.poll(() => rankingReads.at(-1)).toMatchObject(activeRanking);
    await expect(refresh).toBeEnabled();
    const beforeRefresh = rankingReads.length;
    await refresh.click();
    await expect
      .poll(() => rankingReads.slice(beforeRefresh))
      .toEqual([expect.objectContaining(activeRanking)]);

    await page.getByText("近七天", { exact: true }).click();
    await expect
      .poll(() => rankingReads.at(-1))
      .toMatchObject({
        ...activeRanking,
        start_date: "2026-11-17",
      });
    await expect(rankRows).toHaveCount(5);
    outcomeFixture = true;
    const beforeSingle = rankingReads.length;
    const beforeSummary = stats.length;
    await choose("智能体", "智能问答助手");
    await expect(ranking).toHaveCount(0);
    await expect(
      distribution.getByText("次纳入统计", { exact: true }),
    ).toBeVisible();
    await expect(
      distribution.getByText("1,000", { exact: true }),
    ).toBeVisible();
    await expect(distribution.locator("dt")).toHaveText([
      "调用量",
      "成功 · 75%",
      "失败 · 25%",
    ]);
    await expect(distribution.locator("dd")).toHaveText([
      "1,047",
      "750",
      "250",
    ]);
    expect(
      stats.slice(beforeSummary).filter((item) => item.view === "summary"),
    ).toEqual([
      expect.objectContaining({
        tenant: "a",
        agent: "1",
        group: "10",
        from: "2026-11-17",
      }),
    ]);
    expect(rankingReads).toHaveLength(beforeSingle);
    await screenshot("agent-selected-outcomes");
    await tab("MCP").click();
    await page.getByText("自定义", { exact: true }).click();
  });
  await contract.step(modelDrilldown, async () => {
    await tab("模型").click();
    await choose("租户", "全部租户");
    const modelDetails = page.getByRole("region", { name: "模型明细" });
    await modelDetails.locator(".ant-pagination-item-2").click();
    await modelDetails
      .getByRole("row", { name: /历史文本模型/ })
      .getByRole("button", { name: "查看统计" })
      .click();
    await expect(
      page.getByRole("heading", { name: "历史文本模型 · 研发中心" }),
    ).toBeFocused();
    const expected = {
      tenant_id: "b",
      model_id: "2",
      start_date: "2026-11-07",
      end_date: "2026-11-12",
    };
    await expect.poll(() => modelSummaryReads.at(-1)).toEqual(expected);
    await expect.poll(() => modelTrendReads.at(-1)).toEqual(expected);
    await expect.poll(() => modelListReads.at(-1)).toMatchObject(expected);
    await expect(page.getByPlaceholder("请选择开始日期")).toHaveValue(
      expected.start_date,
    );
    await expect(page.getByPlaceholder("请选择结束日期")).toHaveValue(
      expected.end_date,
    );
    await choose("模型", "全部模型");
    await expect(
      page.getByRole("heading", { name: "全部模型 · 全部租户" }),
    ).toBeVisible();
    await choose("租户", "运营中心");
    await tab("MCP").click();
    await choose("MCP", "文件服务");
  });
  const [
    dashboard,
    reset,
    agentMetrics,
    safeRefresh,
    agentDetails,
    agentCharts,
    monitoringOverview,
    sharedDetailSearch,
    modelMetrics,
    modelListNavigation,
  ] = contract.expectedIds("assertions");
  await contract.assertion(dashboard, async () => {
    await expect(heading).toBeVisible();
    await expect(placeholder).toBeVisible();
    await expect(page.getByPlaceholder("请选择开始日期")).toHaveValue(
      "2026-11-07",
    );
  });
  await contract.assertion(reset, async () => {
    expect(reads).toEqual(
      expect.arrayContaining([
        "groups:a",
        "groups:b",
        "skills:a",
        "tools:3",
        "tools:4",
      ]),
    );
    await expect(allTools).toBeVisible();
    expect(unexpected).toEqual([]);
  });
  await contract.assertion(agentMetrics, async () => {
    expect(stats).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          tenant: null,
          agent: null,
          from: "2026-11-07",
        }),
        expect.objectContaining({
          tenant: "b",
          agent: null,
          from: "2026-11-07",
        }),
      ]),
    );
  });
  await contract.assertion(safeRefresh, async () => {
    expect(stats).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          view: "summary",
          tenant: "a",
          group: "10",
          agent: "1",
          from: "2026-10-25",
        }),
        expect.objectContaining({
          view: "trends",
          tenant: "a",
          group: "10",
          agent: "1",
          from: "2026-10-25",
        }),
      ]),
    );
    expect(unexpected).toEqual([]);
  });
  await contract.assertion(agentDetails, async () => {
    expect(stats).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ view: "summary", tenant: "b", agent: "1" }),
        expect.objectContaining({ view: "trends", tenant: "b", agent: "1" }),
      ]),
    );
    expect(unexpected).toEqual([]);
  });
  await contract.assertion(agentCharts, async () => {
    expect(new Set(rankingReads.map(({ metric }) => metric))).toEqual(
      new Set(["execution_count", "success_rate", "total_tokens"]),
    );
    expect(unexpected).toEqual([]);
  });
  await contract.assertion(monitoringOverview, async () => {
    expect(modelTrendReads.slice(0, overviewModelReads)).toEqual(
      expect.arrayContaining([
        { start_date: "2026-11-07", end_date: "2026-11-12", tenant_id: "b" },
        { start_date: "2026-11-07", end_date: "2026-11-12" },
      ]),
    );
    expect(unexpected).toEqual([]);
  });
  await contract.assertion(sharedDetailSearch, async () => {
    expect(modelListReads).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          search: "文本生成",
          page: "1",
          tenant_id: "a",
        }),
      ]),
    );
    expect(listReads).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ search: "智能问答", page: "1" }),
      ]),
    );
    expect(unexpected).toEqual([]);
  });
  await contract.assertion(modelMetrics, async () => {
    const single = expect.objectContaining({
      tenant_id: "a",
      model_id: "2",
      group_ids: "10",
    });
    expect(modelSummaryReads).toEqual(expect.arrayContaining([single]));
    expect(modelTrendReads).toEqual(expect.arrayContaining([single]));
    expect(unexpected).toEqual([]);
  });
  await contract.assertion(modelListNavigation, async () => {
    expect(modelListReads).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          search: "向量模型",
          page: "2",
          sort_by: "total_tokens",
          descending: "true",
        }),
        expect.objectContaining({
          search: "向量模型",
          page: "1",
          sort_by: "total_tokens",
          descending: "false",
        }),
        expect.objectContaining({ tenant_id: "b", model_id: "2", page: "1" }),
      ]),
    );
    expect(unexpected).toEqual([]);
  });
});
