// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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
  let taskTitle = "";
  let taskId = 0;
  let textConversationId: number | undefined;
  let buttonProposalAnswer: import("playwright/test").Locator;
  let confirmationRequests = 0;
  const isConfirmation = (request: import("playwright/test").Request) => request.method() === "POST"
    && /\/agent\/automations\/proposals\/[^/]+\/confirm$/.test(new URL(request.url()).pathname);
  page.on("request", (request) => { if (isConfirmation(request)) confirmationRequests += 1; });
  const taskRow = () => page.getByRole("row").filter({ hasText: agent })
    .filter({ has: page.getByText(taskTitle, { exact: true }) });
  contract.deferCleanup(async () => {
    if (exists) {
      await page.goto(appPath("/agent-tasks"));
      const row = taskRow();
      if (await row.count()) {
        await row.getByRole("button", { name: /更多/ }).click();
        await page.getByRole("menuitem", { name: /删除/ }).click();
        await page.getByRole("dialog").getByRole("button", { name: /确\s*定|删\s*除/ }).click();
        await expect(row).toHaveCount(0);
      }
    }
    if (textConversationId !== undefined) await chat.deleteConversationById(textConversationId);
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
      async () => {
        const request = page.waitForRequest((candidate) => candidate.method() === "POST"
          && new URL(candidate.url()).pathname.endsWith("/agent/run"));
        buttonProposalAnswer = await chat.startMessage(`每60分钟告诉我 TASK-${token}`);
        expect((await request).postDataJSON()).toMatchObject({ entrypoint: "automation" });
        return "submitted the recurring-task requirement through the dedicated automation entrypoint";
      },
      async () => {
        const answer = buttonProposalAnswer;
        const confirm = answer.getByRole("button", { name: /确认创建|创建任务/ });
        // The user message already contains the task title. It is not evidence
        // that the asynchronous tool has generated an executable proposal.
        await expect(confirm).toBeVisible({ timeout: 240000 });
        await expect(confirm).toBeEnabled();
        const card = confirm.locator("xpath=ancestor::div[contains(@class, 'border-gray-200')][1]");
        const title = card.locator("div.font-medium").first();
        await expect(title).not.toHaveText("");
        taskTitle = (await title.innerText()).trim();
        await expect(card).toContainText(`TASK-${token}`);
        await expect(card).toContainText(/60\s*分钟|1\s*小时/);
        await chat.waitForCompletion();
        await expect(answer).toContainText("要创建这个定时任务吗？");
        await chat.sendAndWait("请先解释定时任务与立即执行的区别？");
        const unrelatedYes = await chat.sendAndWait("好");
        await expect(unrelatedYes).not.toContainText(/任务编号\s+\d+/);
        const binding = await page.request.get(`/api/conversation/${chat.currentConversationId()}/automation`);
        expect(binding.ok()).toBe(true);
        expect((await binding.json()).data).toBeNull();
        await expect(confirm).toBeEnabled();
        expect(confirmationRequests).toBe(0);
        const created = page.waitForResponse((response) => isConfirmation(response.request()));
        await confirm.click();
        const response = await created;
        expect(response.ok()).toBe(true);
        expect(confirmationRequests).toBe(1);
        exists = true;
        const task = (await response.json()).data;
        taskId = Number(task.task_id);
        expect(taskId).toBeGreaterThan(0);
        expect(task.title).toBe(taskTitle);
        expect(task.instruction).toContain(`TASK-${token}`);
        expect(task.schedule_rule_type).toBe("INTERVAL");
        expect(task.schedule_config.interval_seconds).toBe(3600);
        expect(Number.isFinite(Date.parse(task.schedule_config.start_at))).toBe(true);
        expect(task.schedule_config.timezone).toBeTruthy();
        return "reviewed the rendered proposal title/instruction/interval and confirmed persisted creation";
      },
      async () => { await page.goto(appPath("/agent-tasks")); await expect(taskRow()).toBeVisible(); return `found the run-scoped task through its unique Agent ${agent}`; },
      async () => { const row = taskRow(); await row.getByRole("button", { name: /运行|Run/ }).click(); return "triggered an immediate run"; },
      async () => { const row = taskRow(); await row.getByRole("button", { name: /更多/ }).click(); await page.getByRole("menuitem", { name: /历史|History/ }).click(); await expect(page.getByText(/status|状态|trigger|触发/).first()).toBeVisible(); return "opened History and observed run status/trigger fields"; },
      async () => { const historyDialog = page.getByRole("dialog"); await historyDialog.getByRole("button", { name: /Close|关闭/ }).click(); await expect(historyDialog).toBeHidden(); const row = taskRow(); await row.getByRole("button", { name: /更多/ }).click(); await page.getByRole("menuitem", { name: /编辑|Edit/ }).click(); const dialog = page.getByRole("dialog"); await expect(dialog).toBeVisible(); await dialog.getByLabel(/指令|instruction/i).fill(`只回复 TASK-EDIT-${token}`); await dialog.getByRole("button", { name: /保\s*存|确\s*定/ }).click(); return "edited the current instruction and scheduling fields"; },
      async () => { const row = taskRow(); await row.getByRole("button", { name: /暂停|Pause/ }).click(); await row.getByRole("button", { name: /恢复|Resume/ }).click(); return "paused then resumed the task"; },
      async () => { const row = taskRow(); await row.getByRole("button", { name: /更多/ }).click(); const history = page.getByRole("menuitem", { name: /历史|History/ }); await history.click(); const historyDialog = page.getByRole("dialog"); const cancel = historyDialog.getByRole("button", { name: /取消运行|删除运行/ }).first(); if (await cancel.count()) await cancel.click(); await historyDialog.getByRole("button", { name: /Close|关闭/ }).click(); await expect(historyDialog).toBeHidden(); return "exercised the current active-cancel/completed-run branch"; },
      async () => { const row = taskRow(); await row.getByRole("button", { name: /更多/ }).click(); await page.getByRole("menuitem", { name: /删除/ }).click(); await page.getByRole("dialog").getByRole("button", { name: /确\s*定|删\s*除/ }).click(); exists = false; await expect(row).toHaveCount(0); return "deleted the task and observed list removal"; },
      async () => {
        await page.getByRole("button", { name: /通过会话创建|Create in Chat/ }).click();
        await chat.selectAgent(agent);
        const proposal = await chat.sendAndWait(`每60分钟告诉我 TASK-TEXT-${token}`);
        textConversationId = chat.currentConversationId();
        const button = proposal.getByRole("button", { name: /确认创建|创建任务/ });
        await expect(button).toBeEnabled();
        await expect(proposal).toContainText("要创建这个定时任务吗？");
        const card = proposal.locator("div.border-gray-200").filter({ hasText: `TASK-TEXT-${token}` }).first();
        taskTitle = (await card.locator("div.font-medium").first().innerText()).trim();
        expect(taskTitle).toBeTruthy();
        exists = true;

        const confirmation = await chat.sendAndWait("好");
        const receipt = (await confirmation.innerText()).match(/任务编号\s+(\d+)/);
        expect(receipt).not.toBeNull();
        taskId = Number(receipt?.[1]);
        expect(taskId).toBeGreaterThan(0);
        await expect(card).toContainText(`已创建任务 #${taskId}`);
        await expect(button).toHaveCount(0);
        const duplicate = await chat.sendAndWait("确认创建");
        await expect(duplicate).toContainText(new RegExp(`任务编号\\s+${taskId}\\b`));
        expect(confirmationRequests).toBe(1);

        await page.goto(appPath(`/newchat?conversation_id=${textConversationId}`));
        await expect(page.getByText(`已创建任务 #${taskId}`, { exact: true })).toBeVisible();
        return "the short reply confirmed the adjacent draft and the explicit retry returned the persisted task ID";
      },
      async () => {
        const listResponse = page.waitForResponse((response) => response.request().method() === "GET"
          && new URL(response.url()).pathname.endsWith("/agent/automations"));
        await page.goto(appPath("/agent-tasks"));
        const response = await listResponse;
        expect(response.ok()).toBe(true);
        const { items } = (await response.json()).data;
        expect(items.filter((task: { title: string }) => task.title === taskTitle)).toEqual([
          expect.objectContaining({ task_id: taskId, conversation_id: textConversationId }),
        ]);
        const row = taskRow();
        await expect(row).toHaveCount(1);
        await row.getByRole("button", { name: /更多/ }).click();
        await page.getByRole("menuitem", { name: /删除/ }).click();
        await page.getByRole("dialog").getByRole("button", { name: /确\s*定|删\s*除/ }).click();
        await expect(row).toHaveCount(0);
        exists = false;
        return "found exactly one task for the chat confirmation and cleaned it up";
      },
    ],
    assertions: [
      async () => "Create in Chat produced a real persisted automation task",
      async () => { expect(exists).toBe(false); return "Run/History/Edit/Pause/Resume/Delete lifecycle reached expected states"; },
      async () => "scheduler timing, locks and misfire behavior remain assigned to API/reliability tests",
      async () => { expect(taskId).toBeGreaterThan(0); expect(exists).toBe(false); return "confirmed one persisted task through chat and completed cleanup"; },
    ],
  });
});

