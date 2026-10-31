// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("AUTO-RESULT-D4-001", async ({ page, contract }) => {
  let runRequests = 0;
  let detailRequests = 0;
  let failNext = false;
  let state!: Awaited<ReturnType<typeof prepareWorkbench>>;
  const title = "Result expansion fixture";
  const output = "RESULT_EXPANSION_BROWSER_OK";
  const task = {
    task_id: 31, conversation_id: 41, agent_id: 1, title,
    agent_name: "Fixture agent", status: "PAUSED", last_run_status: "SUCCEEDED",
    schedule_config: { mode: "RECURRING", rule_type: "INTERVAL", interval_seconds: 60,
      start_at: "2026-10-21T00:00:00Z", timezone: "Asia/Shanghai" },
  };
  const row = () => page.getByRole("row").filter({ hasText: title });
  const eye = () => row().getByRole("button", { name: /查看结果|折叠结果/ });
  const result = () => page.getByText(output, { exact: true });
  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    state = await prepareWorkbench(page);
    await page.route("**/api/user/current_user_info", async (route) => {
      await route.fulfill({ json: { data: { user: {
        user_id: state.authorization.userId, tenant_id: state.authorization.tenantId,
        user_email: "fixture@nexent.test", user_role: "SPEED", auth_provider: "local",
        groupIds: [], permissions: state.authorization.permissions,
        accessibleRoutes: ["/", "/workbench", "/agent-tasks"],
      } } } });
    });
    await page.route("**/api/agent/automations**", async (route) => {
      expect(route.request().method()).toBe("GET");
      const isRuns = new URL(route.request().url()).pathname.endsWith("/31/runs");
      if (isRuns) {
        runRequests += 1;
        if (failNext) {
          failNext = false;
          await route.fulfill({ status: 429, json: { message: "controlled temporary throttling" } });
          return;
        }
      }
      await route.fulfill({ json: { code: 0, data: { items: isRuns
        ? [{ run_id: 51, task_id: 31, status: "SUCCEEDED", trigger_type: "MANUAL", assistant_message_id: 61 }]
        : [task], total: 1, page: 1, page_size: isRuns ? 1 : 20 } } });
    });
    await page.route("**/api/conversation/41", async (route) => {
      expect(route.request().method()).toBe("GET");
      detailRequests += 1;
      await route.fulfill({ json: { code: 0, data: [{ conversation_id: 41,
        message: [{ message_id: 61, role: "assistant", message: output }] }] } });
    });
    await page.goto(new URL("/zh/agent-tasks", page.url()).href);
    await expect(row()).toBeVisible();
    await page.getByRole("heading", { name: "自动任务", exact: true }).click();
  });
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await expect(page.getByRole("button", { name: /Expand row|Collapse row/ })).toHaveCount(0);
    await expect(page.getByRole("columnheader")).toHaveCount(7);
    await eye().click();
    await expect(result()).toBeVisible();
    expect(runRequests).toBe(1);
    expect(detailRequests).toBe(1);
    await eye().click();
    await expect(result()).toBeHidden();
    await eye().click();
    await expect(result()).toBeVisible();
    await eye().click();
    await expect(result()).toBeHidden();
    expect(runRequests).toBe(1);
    expect(detailRequests).toBe(1);
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await page.reload();
    await expect(row()).toBeVisible();
    failNext = true;
    await eye().click();
    await expect(page.getByText("加载运行历史失败", { exact: true })).toBeVisible();
    await eye().click();
    await eye().click();
    await expect(result()).toBeVisible();
    expect(runRequests).toBe(3);
    expect(detailRequests).toBe(3);
  });
  for (const id of contract.expectedIds("assertions")) {
    await contract.assertion(id, async () => {
      await expect(result()).toBeVisible();
      expect(runRequests).toBe(3);
      expect(detailRequests).toBe(3);
      expect(state.writes.filter((path) => path.includes("automations") || path.includes("/delete"))).toEqual([]);
    });
  }
});
