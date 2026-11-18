// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { journey } from "../../infra/automation/d4/runner/journey";
import {
  baseUrl,
  installEditor,
  label,
} from "../../infra/automation/d4/fixtures/agent-editor-workflows";

const catalog = [
  ...["line", "pie", "bar"].map((chart, index) => ({
    tool_id: 9101 + index,
    name: `generate_${chart}_chart`,
    origin_name: `generate_${chart}_chart`,
    description: `Generate a ${chart} chart`,
    source: "mcp",
    usage: "vis",
    is_available: true,
    params: [],
  })),
  {
    tool_id: 9104,
    name: "local_calculator",
    origin_name: "local_calculator",
    description: "Local calculator",
    source: "local",
    is_available: true,
    params: [],
  },
];

journey("AGENT-EDITOR-D4-007", async ({ page, contract, expect }) => {
  const fixture = await installEditor(page);
  const initialIds = [9001, 9101, 9102, 9104];
  const managedTools = fixture.draft.tools;
  const expectedIds = [...initialIds, 9103];
  const toolWrites: unknown[] = [];
  await page.route("**/api/tool/list", (route) =>
    route.fulfill({ json: catalog }),
  );
  await page.route("**/api/mcp/list**", (route) =>
    route.fulfill({
      json: {
        status: "success",
        remote_mcp_server_list: [
          { remote_mcp_server_name: "vis", permission: "EDIT" },
        ],
      },
    }),
  );
  await page.route("**/api/tool/search", (route) =>
    route.fulfill({ json: { params: {}, enabled: false } }),
  );
  await page.route("**/api/tool/update", (route) => {
    toolWrites.push(route.request().postDataJSON());
    return route.fulfill({ json: { status: "success" } });
  });
  await page.route("**/api/agent/search_info", (route) => {
    const enabledIds = fixture.updates.at(-1)?.enabled_tool_ids ?? initialIds;
    return route.fulfill({
      json: {
        ...fixture.draft,
        tools: [...managedTools, ...catalog].filter((tool) =>
          enabledIds.includes(tool.tool_id),
        ),
      },
    });
  });

  const steps = contract.expectedIds("steps");
  const group = page.getByTestId("agent-selected-mcp-service-vis");
  const grid = page.getByTestId("agent-selected-tool-grid");
  const title = label("toolPool.mcpSelectService").replace("{{name}}", "vis");
  const countText = (selected: number) =>
    label("toolPool.mcpSelectedToolCount")
      .replace("{{selected}}", String(selected))
      .replace("{{total}}", "3");

  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      expect((await page.request.get(baseUrl)).ok()).toBe(true);
    },
  );
  await contract.step(steps[0], async () => {
    await page.goto(`${baseUrl}/zh/agents/42`);
    await expect(group).toHaveCount(1);
    await expect(group.getByText(countText(2), { exact: true })).toBeVisible();
    await expect(
      grid.getByText("local_calculator", { exact: true }),
    ).toBeVisible();
    await expect(
      grid.getByText("generate_pie_chart", { exact: true }),
    ).toHaveCount(0);
    expect(fixture.updates).toEqual([]);
  });
  await contract.step(steps[1], async () => {
    await group.getByRole("button", { name: title }).click();
    const dialog = page.getByRole("dialog", { name: title });
    await expect(
      dialog.getByRole("checkbox", { name: "generate_pie_chart" }),
    ).toBeChecked();
    await dialog.getByRole("textbox").fill("bar");
    await expect(dialog.getByRole("checkbox")).toHaveCount(1);
    await dialog.getByRole("checkbox", { name: "generate_bar_chart" }).check();
    await expect(group.getByText(countText(3), { exact: true })).toBeVisible();
    await expect
      .poll(() => fixture.updates.at(-1)?.enabled_tool_ids)
      .toEqual(expectedIds);
    await expect
      .poll(() => toolWrites)
      .toEqual([{ tool_id: 9103, agent_id: 42, enabled: true, params: {} }]);
  });
  await contract.step(steps[2], async () => {
    await page.reload();
    await expect(group).toHaveCount(1);
    await expect(group.getByText(countText(3), { exact: true })).toBeVisible();
    await expect(
      grid.getByText("local_calculator", { exact: true }),
    ).toBeVisible();
    await group.getByRole("button", { name: title }).click();
    const dialog = page.getByRole("dialog", { name: title });
    await expect(dialog.getByRole("checkbox", { checked: true })).toHaveCount(
      3,
    );
  });
  await contract.assertion(contract.expectedIds("assertions")[0], async () => {
    expect(fixture.updates).toEqual([
      { agent_id: 42, enabled_tool_ids: expectedIds },
    ]);
    expect(fixture.creationAttempts).toEqual([]);
    expect(fixture.unexpectedWrites).toEqual([]);
  });
});
