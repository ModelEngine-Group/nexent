// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { installEditor } from "../../infra/automation/d4/fixtures/agent-editor-workflows";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("WB-CONTROLS-D4-004", async ({ page, contract }) => {
  const localCatalogCalls: string[] = [];
  const toolWrites: Array<Record<string, any>> = [];
  const runs: Array<Record<string, any>> = [];
  const catalog = ["kds:alpha", "kds:beta"].map((id, index) => ({
    kds_id: id,
    kds_name: index ? "AIDP Beta" : "AIDP Alpha",
    description: "Authorized remote knowledge",
    document_count: 0,
    chunk_count: 0,
    permission: "READ_ONLY",
    embedding_model: "remote-only",
  }));
  const tool = {
    tool_id: 9001,
    name: "aidp_search",
    origin_name: "aidp_search",
    class_name: "AidpSearchTool",
    is_available: true,
    description: "AIDP search",
    params: [
      { name: "kds_list", type: "string", optional: true, default: "[]" },
    ],
  };
  page.on("request", (request) => {
    if (/\/api\/indices(?:\?|$|\/health)/.test(request.url()))
      localCatalogCalls.push(request.url());
  });
  const editor = await installEditor(page);
  editor.draft.tools = [tool];
  const installAidpRoutes = async () => {
    await page.route("**/api/tenant_config/deployment_version", (route) =>
      route.fulfill({
        json: {
          deployment_version: "speed",
          app_version: "fixture",
          status: "success",
          enable_agent_workbench: true,
          enable_aidp_knowledge: true,
        },
      }),
    );
    await page.route("**/api/aidp-mgmt/knowledge-bases?*", (route) =>
      route.fulfill({
        json: {
          code: 0,
          value: catalog,
          has_more: false,
          total_count: catalog.length,
        },
      }),
    );
  };
  await installAidpRoutes();
  await page.route(
    "**/api/tag-libraries/assignments/knowledge_base/batch_read",
    (route) => route.fulfill({ json: [] }),
  );
  await page.route("**/api/tool/list", (route) =>
    route.fulfill({ json: [tool] }),
  );
  await page.route("**/api/tool/update", async (route) => {
    const body = route.request().postDataJSON();
    toolWrites.push(body);
    editor.draft.tools = [
      {
        ...tool,
        params: tool.params.map((param) => ({
          ...param,
          default: body.params[param.name],
        })),
      },
    ];
    await route.fulfill({ json: { status: "success" } });
  });
  await page.goto(`${process.env.NEXENT_BASE_URL}/zh/agents/42`);
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await expect(
        page.getByRole("button", { name: "点击添加知识库", exact: true }),
      ).toBeVisible();
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await page
      .getByRole("button", { name: "点击添加知识库", exact: true })
      .click();
    const drawer = page.getByRole("dialog", {
      name: "添加知识库",
      exact: true,
    });
    await expect(drawer.locator('[data-picker-part="search"]')).toBeVisible();
    await expect(
      drawer.getByRole("option", { name: "AIDP Beta", exact: true }),
    ).toBeEnabled();
    await expect(drawer).toContainText("remote-only");
    await drawer
      .getByRole("option", { name: "AIDP Beta", exact: true })
      .click();
    await drawer.getByRole("button", { name: "确认", exact: true }).click();
    await expect(drawer).toHaveCount(0);
    await expect.poll(() => toolWrites.length).toBe(1);
    expect(toolWrites[0]).toMatchObject({
      tool_id: 9001,
      agent_id: 42,
      params: { kds_list: '["kds:beta"]' },
      enabled: true,
    });
    await page
      .getByRole("button", { name: "点击添加知识库", exact: true })
      .click();
    await expect(
      drawer.getByRole("option", { name: "AIDP Beta", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    await drawer
      .getByRole("button", { name: "关闭", exact: true })
      .last()
      .click();
    await expect(drawer).toHaveCount(0);
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await page.unrouteAll({ behavior: "wait" });
    await prepareWorkbench(page);
    await installAidpRoutes();
    await page.reload();
    await page.route("**/api/agent/run", async (route) => {
      runs.push(route.request().postDataJSON());
      await route.fulfill({ json: { code: 0, data: {} } });
    });
    const open = () =>
      page.getByRole("button", { name: "知识库", exact: true }).click();
    const drawer = page.getByRole("dialog", {
      name: "当前对话知识库",
      exact: true,
    });
    await open();
    await expect(
      drawer.getByRole("option", { name: "AIDP Alpha", exact: true }),
    ).toBeVisible();
    await expect(
      drawer.getByRole("button", { name: "管理标签", exact: true }),
    ).toHaveCount(0);
    await drawer
      .getByRole("option", { name: "AIDP Alpha", exact: true })
      .click();
    await drawer
      .locator('[data-picker-part="footer"]')
      .getByRole("button", { name: "关闭", exact: true })
      .click();
    await expect(drawer).toHaveCount(0);
    await open();
    await expect(
      drawer.getByRole("option", { name: "AIDP Alpha", exact: true }),
    ).toHaveAttribute("aria-selected", "false");
    await drawer
      .getByRole("option", { name: "AIDP Beta", exact: true })
      .click();
    await drawer.getByRole("button", { name: "确认", exact: true }).click();
    await expect(drawer).toHaveCount(0);
    await open();
    await expect(
      drawer.getByRole("option", { name: "AIDP Beta", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    await drawer
      .locator('[data-picker-part="footer"]')
      .getByRole("button", { name: "关闭", exact: true })
      .click();
    await expect(drawer).toHaveCount(0);
    await page
      .locator("[data-workbench-composer]")
      .fill("AIDP scope verification");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await expect.poll(() => runs.length).toBe(1);
  });
  await contract.assertion(contract.expectedIds("assertions")[0], async () => {
    expect((runs[0].workbench ?? runs[0]).knowledge_scope).toMatchObject({
      local: { mode: "disabled", knowledge_ids: [] },
      aidp: { mode: "override", kds_ids: ["kds:beta"] },
    });
  });
  await contract.assertion(contract.expectedIds("assertions")[1], async () => {
    expect(toolWrites).toHaveLength(1);
    expect(editor.creationAttempts).toEqual([]);
    expect(localCatalogCalls).toEqual([]);
    expect(editor.unexpectedWrites).toEqual([]);
  });
});
