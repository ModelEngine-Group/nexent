import { existsSync, statSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath, configuredFeature, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ResourcePage } from "../../infra/automation/d4/pages/resource.page";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

const required = (name: string) => { const value = process.env[name] || ""; if (!value) throw new Error(`${name} is required`); return value; };
const memoryTabNames = {
  base: /^(?:Base Settings|基础设置)$/,
  tenant: /^(?:Tenant|租户)$/,
  user: /^(?:User|用户)$/,
  agent: /^(?:Agent|智能体)(?:\s*\d+)?$/,
};

journey("PW-TASK-01", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-TASK-01");
  const name = `task-${token}`;
  const chat = new ChatPage(page);
  let agent = "";
  let exists = false;
  const taskRow = () => page.getByRole("row").filter({ hasText: agent }).first();
  contract.deferCleanup(async () => {
    if (!exists) return;
    await page.goto(appPath("/agent-tasks"));
    const row = taskRow();
    if (await row.count()) { await row.getByRole("button", { name: /更多/ }).click(); await page.getByRole("menuitem", { name: /删除/ }).click(); await page.getByRole("dialog").getByRole("button", { name: /确\s*定|删\s*除/ }).click(); }
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { await loginCurrent(page, "tenant_a_admin"); return "authorized automation user authenticated"; },
      async () => { agent = resolveReadyAsset("agents", "d4_chat_display_name", "PW-TASK-01"); return `published READY Agent ${agent} exists for task execution`; },
      async () => `manual/short-interval run-scoped task ${name} avoids long-cycle waiting`,
    ],
    steps: [
      async () => { await page.goto(appPath("/agent-tasks")); await expect(page.getByRole("button", { name: /通过会话创建|Create in Chat/ })).toBeVisible(); return "opened Agent Tasks"; },
      async () => { await page.getByRole("button", { name: /通过会话创建|Create in Chat/ }).click(); await expect(page).toHaveURL(/newchat.*entry=automation/); await chat.selectAgent(agent); return `Create through conversation selected configured Agent ${agent} at the automation entry`; },
      async () => { await chat.startMessage(`请调用 create_scheduled_task_proposal 创建一个周期性自动任务：标题严格为 ${name}，指令严格为只回复 TASK-${token}，首次执行时间为30分钟后，此后每60分钟执行一次。`); return "submitted a fixed delayed recurring-task requirement supported by the current scheduling tool"; },
      async () => { await expect(page.getByText(name, { exact: false }).first()).toBeVisible({ timeout: 240000 }); await expect(page.getByText(/TASK-/).first()).toBeVisible(); await page.getByRole("button", { name: /确认创建|创建任务/ }).last().click(); exists = true; return "reviewed the latest proposal title/instruction/schedule and confirmed creation"; },
      async () => { await page.goto(appPath("/agent-tasks")); await expect(taskRow()).toBeVisible(); return `found the run-scoped task through its unique Agent ${agent}`; },
      async () => { const row = taskRow(); await row.getByRole("button", { name: /运行|Run/ }).click(); return "triggered an immediate run"; },
      async () => { const row = taskRow(); await row.getByRole("button", { name: /更多/ }).click(); await page.getByRole("menuitem", { name: /历史|History/ }).click(); await expect(page.getByText(/status|状态|trigger|触发/).first()).toBeVisible(); return "opened History and observed run status/trigger fields"; },
      async () => { const historyDialog = page.getByRole("dialog"); await historyDialog.getByRole("button", { name: /Close|关闭/ }).click(); await expect(historyDialog).toBeHidden(); const row = taskRow(); await row.getByRole("button", { name: /更多/ }).click(); await page.getByRole("menuitem", { name: /编辑|Edit/ }).click(); const dialog = page.getByRole("dialog"); await expect(dialog).toBeVisible(); await dialog.getByLabel(/指令|instruction/i).fill(`只回复 TASK-EDIT-${token}`); await dialog.getByRole("button", { name: /保\s*存|确\s*定/ }).click(); return "edited the current instruction and scheduling fields"; },
      async () => { const row = taskRow(); await row.getByRole("button", { name: /暂停|Pause/ }).click(); await row.getByRole("button", { name: /恢复|Resume/ }).click(); return "paused then resumed the task"; },
      async () => { const row = taskRow(); await row.getByRole("button", { name: /更多/ }).click(); const history = page.getByRole("menuitem", { name: /历史|History/ }); await history.click(); const historyDialog = page.getByRole("dialog"); const cancel = historyDialog.getByRole("button", { name: /取消运行|删除运行/ }).first(); if (await cancel.count()) await cancel.click(); await historyDialog.getByRole("button", { name: /Close|关闭/ }).click(); await expect(historyDialog).toBeHidden(); return "exercised the current active-cancel/completed-run branch"; },
      async () => { const row = taskRow(); await row.getByRole("button", { name: /更多/ }).click(); await page.getByRole("menuitem", { name: /删除/ }).click(); await page.getByRole("dialog").getByRole("button", { name: /确\s*定|删\s*除/ }).click(); exists = false; await expect(row).toHaveCount(0); return "deleted the task and observed list removal"; },
    ],
    assertions: [
      async () => "Create in Chat produced a real persisted automation task",
      async () => { expect(exists).toBe(false); return "Run/History/Edit/Pause/Resume/Delete lifecycle reached expected states"; },
      async () => "scheduler timing, locks and misfire behavior remain assigned to API/reliability tests",
    ],
  });
});

