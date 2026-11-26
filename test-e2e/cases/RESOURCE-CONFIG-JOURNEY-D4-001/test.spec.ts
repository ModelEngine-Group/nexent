// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { installEditor } from "../../infra/automation/d4/fixtures/agent-editor-workflows";

journey("RESOURCE-CONFIG-JOURNEY-D4-001", async ({ page, contract }) => {
  const selected: string[] = [];
  const writes: unknown[] = [];
  let failSave = true;
  const resources = [
    {
      key: "local_lookup",
      name: "local_lookup",
      resource_type: "tool",
      source: "local",
      description: "Local utility",
    },
    {
      key: "mcp:enterprise",
      name: "Enterprise",
      resource_type: "mcp",
      description: "Enterprise search service",
    },
    {
      key: "search",
      name: "search",
      resource_type: "tool",
      source: "mcp",
      parent_key: "mcp:enterprise",
      service: "Enterprise",
    },
    {
      key: "skill:research",
      name: "research",
      resource_type: "skill",
      description: "Analyze publications",
    },
  ];
  await page.context().addCookies([
    {
      name: "nexent_token_expires_at",
      value: String(Math.floor(Date.now() / 1000) + 3600),
      url: process.env.NEXENT_BASE_URL ?? "http://localhost:3000",
    },
  ]);
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/user/current_user_info")
      return route.fulfill({
        json: {
          data: {
            user: {
              user_id: "resource-config-user",
              tenant_id: "resource-config-tenant",
              user_email: "admin@example.invalid",
              user_role: "SU",
              roles: ["SU"],
              auth_provider: "local",
              group_ids: [],
              permissions: [
                "ops.configuration:read",
                "ops.configuration:update",
              ],
              accessiblePages: ["ops-configuration"],
            },
          },
        },
      });
    if (path === "/api/system_configurations/resource_denylist") {
      if (request.method() === "PUT") {
        writes.push(request.postDataJSON());
        if (failSave) {
          failSave = false;
          return route.fulfill({
            status: 409,
            json: { detail: "Configuration changed" },
          });
        }
        const body = request.postDataJSON();
        selected.splice(
          0,
          selected.length,
          ...body.tool_names,
          ...body.resource_refs,
        );
      }
      return route.fulfill({
        json: {
          items: resources,
          selected,
          revision: `revision-${selected.length}`,
        },
      });
    }
    if (path === "/api/system_configurations")
      return route.fulfill({ json: { items: [], total: 0 } });
    if (path === "/api/tenant_config/deployment_version")
      return route.fulfill({
        json: {
          deployment_version: "full",
          app_version: "test",
          status: "success",
        },
      });
    if (path === "/api/groups/list")
      return route.fulfill({ json: { data: [], total: 0 } });
    if (path === "/api/notifications")
      return route.fulfill({
        json: { data: { items: [], pagination: { total: 0 } } },
      });
    return route.fulfill({ json: { data: {} } });
  });
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await page.goto("/zh/ops/configuration");
      await expect(
        page.getByRole("heading", { name: "系统配置", exact: true }),
      ).toBeVisible();
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await page.getByRole("tab", { name: "资源配置", exact: true }).click();
    await expect(page.getByText("资源屏蔽项", { exact: true })).toHaveCount(1);
    await expect(
      page.getByRole("button", { name: "添加屏蔽", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByText("被屏蔽的资源不参与配置（NL2Agent也不会推荐）。", {
        exact: true,
      }),
    ).toBeVisible();
    await page.getByRole("button", { name: "查看详情", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveAccessibleName("资源屏蔽项");
    await expect(
      page.getByRole("tab", { name: "本地工具", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    await expect(
      page.getByRole("checkbox", { name: "local_lookup", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("checkbox", { name: "Enterprise", exact: true }),
    ).toHaveCount(0);
    await page.getByRole("tab", { name: "MCP", exact: true }).click();
    await expect(
      page.getByRole("checkbox", { name: "local_lookup", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("tab", { name: "全部", exact: true }),
    ).toHaveCount(0);
    const dialogBox = await page.getByRole("dialog").boundingBox();
    const closeBox = await page
      .getByRole("dialog")
      .getByRole("button", { name: "关闭", exact: true })
      .boundingBox();
    expect(
      dialogBox &&
        closeBox &&
        closeBox.x > dialogBox.x + dialogBox.width / 2 &&
        closeBox.y < dialogBox.y + 80,
    ).toBeTruthy();
    await expect(
      page.getByRole("tab", { name: "MCP", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("tab", { name: "技能", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("tab", { name: "智能体", exact: true }),
    ).toHaveCount(0);
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    const disclosure = page.getByRole("button", {
      name: "Enterprise",
      exact: true,
    });
    await expect(disclosure).toHaveAttribute("aria-expanded", "false");
    await disclosure.click();
    await expect(disclosure).toHaveAttribute("aria-expanded", "true");
    await expect(
      page.getByRole("checkbox", { name: "Enterprise", exact: true }),
    ).not.toBeChecked();
    await page
      .getByRole("checkbox", { name: "Enterprise / search", exact: true })
      .check();
    await page
      .getByRole("checkbox", { name: "Enterprise", exact: true })
      .check();
    await expect(
      page.getByRole("checkbox", { name: "Enterprise / search", exact: true }),
    ).toBeDisabled();
    await page
      .getByRole("checkbox", { name: "Enterprise", exact: true })
      .uncheck();
    await expect(
      page.getByRole("checkbox", { name: "Enterprise / search", exact: true }),
    ).toBeChecked();
    await page
      .getByRole("textbox", { name: "搜索资源名称或描述" })
      .fill("publications");
    await page.getByRole("tab", { name: "技能", exact: true }).click();
    await expect(
      page.getByRole("checkbox", { name: "research", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("checkbox", { name: "Enterprise", exact: true }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "取消", exact: true }).click();
    expect(writes).toHaveLength(0);
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    await page.getByRole("button", { name: "查看详情", exact: true }).click();
    await page.getByRole("tab", { name: "MCP", exact: true }).click();
    await page.getByText("Enterprise", { exact: true }).click();
    await expect(
      page.getByRole("checkbox", { name: "Enterprise / search", exact: true }),
    ).not.toBeChecked();
    await page
      .getByRole("checkbox", { name: "Enterprise / search", exact: true })
      .check();
    await page.getByRole("tab", { name: "技能", exact: true }).click();
    await page.getByRole("checkbox", { name: "research", exact: true }).check();
    const summary = page.getByTestId("resource-denylist-summary");
    await expect(summary.getByRole("region")).toHaveCount(0);
    await expect(
      summary.getByRole("group", { name: "MCP 工具", exact: true }),
    ).toContainText("Enterprise / search");
    await expect(
      summary.getByRole("group", { name: "技能", exact: true }),
    ).toContainText("research");
    await page.screenshot({ path: `${contract.caseDir}/resource-drawer.png` });
    await page.getByRole("button", { name: /确定$/ }).click();
    await expect(page.getByText(/保存失败或配置已更新/)).toBeVisible();
    await expect(
      page.getByRole("checkbox", { name: "research", exact: true }),
    ).toBeChecked();
    await page.getByRole("button", { name: /确定$/ }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(selected).toEqual(["search", "skill:research"]);
    await page.getByRole("button", { name: "查看详情", exact: true }).click();
    await page.getByRole("checkbox", { name: "local_lookup", exact: true }).check();
    failSave = true;
    await page.getByRole("button", { name: /确定$/ }).click();
    await expect(page.getByText(/保存失败或配置已更新/)).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "local_lookup", exact: true })).toBeChecked();
    await page.getByRole("button", { name: "重新加载", exact: true }).click();
    await expect(page.getByText(/保存失败或配置已更新/)).toHaveCount(0);
    await expect(page.getByRole("checkbox", { name: "local_lookup", exact: true })).not.toBeChecked();
    await expect(page.getByRole("button", { name: /确定$/ })).toBeDisabled();
    expect(writes).toHaveLength(3);
    expect(selected).toEqual(["search", "skill:research"]);
    await page.getByRole("tab", { name: "技能", exact: true }).click();
    await expect(page.getByRole("checkbox", { name: "research", exact: true })).toBeChecked();
    await page.getByRole("button", { name: "取消", exact: true }).click();
    await page.goto("/en/ops/configuration");
    await page
      .getByRole("tab", { name: "Resource configuration", exact: true })
      .click();
    await page
      .getByRole("button", { name: "View details", exact: true })
      .click();
    await expect(page.getByRole("dialog")).toContainText("Resource exclusions");
    await page.getByRole("tab", { name: "Skill", exact: true }).click();
    await expect(
      page.getByRole("checkbox", { name: "research", exact: true }),
    ).toBeChecked();
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
  });
  const assertions = contract.expectedIds("assertions");
  await contract.assertion(assertions[0], async () => {
    await expect(page.getByTestId("resource-configuration")).toBeVisible();
  });
  await contract.assertion(assertions[1], async () => {
    expect(writes).toHaveLength(3);
  });
  await contract.assertion(assertions[2], async () => {
    expect(selected).toEqual(["search", "skill:research"]);
  });
  await contract.step(contract.expectedIds("steps")[3], async () => {
    const fixture = await installEditor(page);
    const bindingWrites: unknown[] = [];
    const tool = { tool_id: 77, name: "retained_tool", source: "local", is_available: true,
      is_user_selectable: true, blocked_by_denylist: true, params: [], inputs: "{}" };
    const skill = { skill_id: 78, name: "retained_skill", source: "custom", blocked_by_denylist: true };
    (fixture.draft as any).tools = [tool];
    (fixture.draft as any).skills = [skill];
    await page.route("**/api/tool/list*", (route) => route.fulfill({ json: [tool] }));
    await page.route("**/api/skills?*", (route) => route.fulfill({ json: { skills: [skill] } }));
    await page.route("**/api/tool/search", async (route) => {
      expect(route.request().postDataJSON()).toEqual({ tool_id: 77, agent_id: 42 });
      await route.fulfill({ json: { params: {}, enabled: true } });
    });
    await page.route("**/api/tool/update", async (route) => {
      bindingWrites.push(route.request().postDataJSON());
      await route.fulfill({ json: { success: true } });
    });
    await page.route("**/api/user/current_user_info", (route) => route.fulfill({ json: { data: { user: {
      user_id: "fixture-user", tenant_id: "fixture-tenant", user_email: "fixture@example.invalid",
      user_role: "SU", roles: ["SU"], auth_provider: "local", group_ids: [], permissions: [],
      accessiblePages: ["/agents", "/mcp-space", "/knowledges", "/newchat"],
    } } } }));
    await page.goto("/zh/agents/42");
    const warning = "该资源已被管理员屏蔽，移除后将无法重新添加。";
    const retainedTool = page.getByTestId("agent-selected-tool-77");
    const retainedSkill = page.getByTestId("agent-selected-skill-78");
    await expect(retainedTool).toContainText("已有绑定保留");
    await expect(retainedSkill).toContainText("已有绑定保留");
    expect(fixture.updates).toEqual([]);
    expect(bindingWrites).toEqual([]);
    for (const row of [retainedTool, retainedSkill]) {
      await row.getByRole("button", { name: /移除/ }).click();
      const confirmation = page.getByRole("dialog");
      await expect(confirmation).toContainText(warning);
      await confirmation.getByRole("button", { name: /取消/ }).click();
      await expect(confirmation).toHaveCount(0);
      await expect(row).toBeVisible();
    }
    expect(fixture.updates).toEqual([]);
    expect(bindingWrites).toEqual([]);
    await retainedTool.getByRole("button", { name: /移除/ }).click();
    await page.getByRole("dialog").getByRole("button", { name: /确定/ }).click();
    await expect(retainedTool).toHaveCount(0);
    await retainedSkill.getByRole("button", { name: /移除/ }).click();
    await page.getByRole("dialog").getByRole("button", { name: /确定/ }).click();
    await expect(retainedSkill).toHaveCount(0);
    await expect.poll(() => fixture.updates.length).toBeGreaterThan(0);
    await expect.poll(() => bindingWrites.length).toBe(1);
    expect(bindingWrites).toEqual([{ tool_id: 77, agent_id: 42, params: {}, enabled: false }]);
    expect(fixture.unexpectedWrites).toEqual([]);
    expect(fixture.creationAttempts).toEqual([]);
  });
  await contract.assertion(assertions[3], async () => {
    await expect(page.getByTestId("agent-selected-tool-77")).toHaveCount(0);
    await expect(page.getByTestId("agent-selected-skill-78")).toHaveCount(0);
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });
});
