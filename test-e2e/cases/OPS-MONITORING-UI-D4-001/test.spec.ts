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
  const stats: {
    view: string;
    tenant: string | null;
    agent: string | null;
    group: string | null;
    from: string | null;
    to: string | null;
  }[] = [];
  let scenario: "normal" | "empty" | "failed" = "normal";
  let holdMonth = false;
  let completedDelayedRequests = 0;
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
        holdMonth && scope.from === "2026-10-25" && scope.agent === null;
      if (delayed) await delayedMonth;
      if (scenario === "failed") {
        await route.fulfill({
          status: 422,
          json: { detail: "Controlled failed read" },
        });
        return;
      }
      const empty = scenario === "empty";
      const single = scope.agent !== null;
      const metrics = {
        execution_count: empty
          ? null
          : delayed
            ? 700001
            : single
              ? 0
              : scope.group
                ? 33
                : 26847,
        succeeded_count: empty ? null : single ? 0 : 977,
        failed_count: empty ? null : single ? 0 : 23,
        success_rate: empty || single ? null : 0.977,
      };
      const tokens = {
        total_tokens: empty
          ? null
          : {
              value: single
                ? "0"
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
              ? 0
              : [1700, 1820, 1420, 2120, 2410, 2310, 2390][index % 7],
          success_rate:
            gap || single
              ? null
              : [0.89, 0.92, 0.81, 0.96, 1, 0.94, 0.97][index % 7],
          statistic_date: day.toISOString().slice(0, 10),
          coverage_state: gap ? "uncovered" : "covered",
          tokens: gap
            ? { total_tokens: null }
            : single
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
    resumeMonth();
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
  const [dates, scope, tools, metrics, states] = contract.expectedIds("steps");
  await contract.step(dates, async () => {
    await expect(page.getByRole("tab")).toHaveText([
      "概览",
      "智能体",
      "模型",
      "Skill",
      "MCP",
    ]);
    await expect(select("用户组")).toHaveCount(0);
    await expect(placeholder).toBeVisible();
    await expect(page.getByText("2026-11-17 – 2026-11-23")).toBeVisible();
    await screenshot("overview");
    await page.getByText("近一个月", { exact: true }).click();
    await expect(page.getByText("2026-10-25 – 2026-11-23")).toBeVisible();
    await page.getByText("自定义", { exact: true }).click();
    await page.getByPlaceholder("请选择开始日期").click();
    await picker.locator('[title="2026-11-07"]').click();
    await picker.locator('[title="2026-11-12"]').click();
    await expect(page.getByText("2026-11-07 – 2026-11-12")).toBeVisible();
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
    await choose("模型", "文本生成模型");
    await screenshot("model");
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
  const card = (title: string) =>
    page.getByText(title, { exact: true }).locator("..").locator("dd");
  const trend = page.getByRole("region", { name: "调用趋势", exact: true });
  const curve = trend.locator(".recharts-area-curve");
  const refresh = page.getByRole("button", { name: "刷新", exact: true });
  const chooseMetric = (name: string) =>
    trend.getByText(name, { exact: true }).click();
  await contract.step(metrics, async () => {
    await tab("智能体").click();
    await expect(card("当前智能体总数")).toContainText("1");
    await expect(card("调用量").locator("strong")).toHaveText("26,847");
    await expect(card("调用成功率")).toContainText("97.7%");
    await expect(card("调用成功率")).toContainText("1,000 次已结束");
    await expect(card("Token 消耗量").locator("strong")).toHaveText(
      "25,025,913",
    );
    await expect(
      card("Token 消耗量").getByText("tokens", { exact: true }),
    ).toBeVisible();
    await expect(card("Token 消耗量")).toContainText("请求覆盖 3 / 4（75%）");
    await expect(
      page.getByText("数据截至 2026-11-23 07:08:09 UTC", { exact: true }),
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
      "9,007,199,254,740,993",
    );
    await page.getByText("近七天", { exact: true }).click();
    await expect(card("调用量").locator("strong")).toHaveText("33");
    await expect(card("当前智能体总数").locator("strong")).toHaveText("1");
    expect(reads.filter((key) => key.startsWith("resources:"))).toHaveLength(
      inventoryReads,
    );
    const beforeRefresh = stats.length;
    await refresh.click();
    await expect
      .poll(() =>
        stats
          .slice(beforeRefresh)
          .map((item) => item.view)
          .sort(),
      )
      .toEqual(["summary", "trends"]);
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
    await page.getByText("近一个月", { exact: true }).click();
    await expect
      .poll(
        () =>
          stats.filter((item) => item.from === "2026-10-25" && !item.agent)
            .length,
      )
      .toBe(2);
    await expect(card("调用量").locator("strong")).toHaveText("加载中");
    await choose("智能体", "智能问答助手");
    await expect(card("当前智能体总数")).toHaveCount(0);
    await expect(card("调用量").locator("strong")).toHaveText("0");
    await expect(card("调用成功率").locator("strong")).toHaveText("—");
    await expect(card("Token 消耗量").locator("strong")).toHaveText("0");
    await expect(
      trend.getByText("所选指标暂无可用值", { exact: true }),
    ).toBeVisible();
    resumeMonth();
    holdMonth = false;
    await expect.poll(() => completedDelayedRequests).toBe(2);
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
    await tab("MCP").click();
    await page.getByText("自定义", { exact: true }).click();
  });
  const [dashboard, reset, agentMetrics, safeRefresh] =
    contract.expectedIds("assertions");
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
});
