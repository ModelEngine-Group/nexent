import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

journey("PW-CHAT-03", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-CHAT-03");
  let title = "";
  const chat = new ChatPage(page);
  let agentDisplay = "";
  let planItems = 0;
  let conversationId: number | undefined;

  contract.deferCleanup(async () => {
    if (conversationId) {
      try { await chat.captureConversationState(join(contract.caseDir,"conversation-state.json"), `EXEC-${token}`); }
      finally { await chat.deleteConversationById(conversationId); }
    }
  });

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        agentDisplay = resolveReadyAsset("agents", "d4_chat_display_name", "PW-CHAT-03");
        await chat.openAgent(agentDisplay);
        return `selected planning-capable published Agent ${agentDisplay}`;
      },
      async () => `prepared fixed multi-step task PLAN-${token}`,
    ],
    steps: [
      async () => `opened newchat and selected ${agentDisplay}`,
      async () => {
        await chat.selectMode("规划");
        return "Planning mode control was clicked and its selected styling became active";
      },
      async () => {
        await chat.startMessage(`这是规划模式测试，请先调用 create_plan 创建结构化执行计划，不能只在正文列出步骤。计划至少包含 6 项软件发布检查；每完成一项必须调用 update_plan_step 更新状态，再逐项详细说明检查方式。最终输出标记 PLAN-${token}。`);
        conversationId = chat.currentConversationId();
        return "submitted the deterministic multi-step task through Planning mode";
      },
      async () => {
        const plan = page.getByRole("region", { name: "执行计划" });
        await expect(plan).toBeVisible({ timeout: 180_000 });
        planItems = await plan.locator("li").count();
        expect(planItems).toBeGreaterThan(0);
        return `Plan region appeared with ${planItems} structured steps`;
      },
      async () => {
        const plan = page.getByRole("region", { name: "执行计划" });
        await expect.poll(async () => plan.locator("li .line-through").count(), { timeout: 300_000 }).toBeGreaterThan(0);
        return "at least one structured plan step transitioned to completed state before final text";
      },
      async () => {
        await chat.stopGeneration();
        return "stopped the still-running planning execution through the Composer cancel control";
      },
      async () => {
        title = await chat.currentThreadTitle();
        await page.reload({ waitUntil: "domcontentloaded" });
        await chat.openThread(title);
        const restoredPlan = page.getByRole("region", { name: "执行计划" });
        await expect(restoredPlan).toBeVisible({ timeout: 120_000 });
        await expect(restoredPlan.locator("li")).toHaveCount(planItems);
        return "refresh and reopen restored the structured completed/stopped plan";
      },
      async () => {
        await chat.selectMode("执行");
        const response = await chat.sendAndWait(`只回复：EXEC-${token}`);
        try {
          await expect(response).toContainText(`EXEC-${token}`, { timeout: 180_000 });
        } catch (cause) {
          const text = (await response.innerText()).trim();
          if (/已有智能体任务正在运行|task.*already.*running/i.test(text)) {
            const error = new Error("Planning Stop returned success but the following Execution turn was rejected as still running: " + text);
            error.name = "ProductFailure";
            throw error;
          }
          const error = new Error("Planning Stop and refresh succeeded, but the following Execution turn completed without the requested reply: " + text);
          error.name = "ProductFailure";
          throw error;
        }
        return "switched back to Execution and completed an ordinary follow-up question";
      },
    ],
    assertions: [
      async () => {
        await expect(page.getByRole("button", { name: "执行", exact: true })).toHaveClass(/bg-blue-50/);
        return "both real mode buttons operated and Execution is the final selected mode";
      },
      async () => {
        expect(planItems).toBeGreaterThan(0);
        return "the plan exposed structured live steps rather than only a final prose response";
      },
      async () => {
        await expect(page.getByRole("region", { name: "执行计划" })).toBeVisible();
        return "the stopped plan survived persistence and a subsequent Execution turn";
      },
    ],
  });
});
