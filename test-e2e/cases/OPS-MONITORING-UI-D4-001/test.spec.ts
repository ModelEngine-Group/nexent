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
    } else if (pathname.startsWith("/api/ops/v1/monitoring/")) {
      unexpected.push(`${request.method()} ${pathname}`);
    }
    await route.fulfill({ json });
  });
  contract.deferCleanup(async () => page.close());

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
  const [dates, scope, tools] = contract.expectedIds("steps");
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
  const [dashboard, reset] = contract.expectedIds("assertions");
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
});
