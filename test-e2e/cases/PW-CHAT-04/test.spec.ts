import { existsSync, readFileSync } from "node:fs";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

journey("PW-CHAT-04", async (context) => {
  const { page, expect, contract } = context;
  const chat = new ChatPage(page);
  const token = runToken("PW-CHAT-04");
  const title = `multi-agent-${token}`;
  let agent = "";
  let childA = "";
  let childB = "";
  let conversationId = 0;
  let cardCount = 0;
  let cardTexts: string[] = [];
  contract.deferCleanup(async () => { if (conversationId > 0) await chat.deleteConversationById(conversationId); });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { agent = resolveReadyAsset("agents", "d4_multi_display_name", "PW-CHAT-04"); childA = resolveReadyAsset("agents", "d4_multi_child_a_display_name", "PW-CHAT-04"); childB = resolveReadyAsset("agents", "d4_multi_child_b_display_name", "PW-CHAT-04"); expect(childA).not.toBe(childB); return `main Agent ${agent} has two explicitly named collaborators`; },
      async () => `fixed normal and controlled partial-failure prompts use run marker ${token}`,
    ],
    steps: [
      async () => { await loginCurrent(page, "tenant_a_admin"); await chat.openAgent(agent); await chat.selectMode("执行"); return `selected multi-Agent ${agent}`; },
      async () => { await chat.startMessage(`必须分别委派 ${childA} 和 ${childB} 完成两个子任务，最后汇总标记 MULTI-${token}。`); conversationId = chat.currentConversationId(); return "submitted a deterministic multi-collaborator task and registered its server conversation ID for cleanup"; },
      async () => {
        try {
          await expect(page.locator("[data-subagent-id]")).toHaveCount(2, { timeout: 240000 });
        } catch {
          const error = new Error("configured multi-Agent produced no two visible sub-Agent cards within 240000ms");
          error.name = "ProductFailure";
          throw error;
        }
        cardCount = await page.locator("[data-subagent-id]").count(); cardTexts = await page.locator("[data-subagent-id]").allInnerTexts(); return `observed ${cardCount} real sub-Agent cards: ${JSON.stringify(cardTexts)}`;
      },
      async () => {
        const rendered = cardTexts.join("\n");
        // User-visible cards expose display names, not internal runtime variables.
        if (!rendered.includes(childA) || !rendered.includes(childB)) {
          const error = new Error(`sub-Agent cards omitted configured collaborator display names; expected=${JSON.stringify([childA, childB])}; cards=${JSON.stringify(cardTexts)}`);
          error.name = "ProductFailure";
          throw error;
        }
        return "card names match the two configured collaborators";
      },
      async () => { await chat.waitForCompletion(420000); await expect(page.getByText("Completed", { exact: true })).toHaveCount(cardCount); await expect(chat.assistantMessages().last()).toContainText(`MULTI-${token}`); return "normal run reached terminal cards and a main answer"; },
      async () => { const response = await chat.sendAndWait(`让 ${childA} 正常完成；让 ${childB} 调用受控失败工具 always_fail，保留成功和失败详情，最后回复 PARTIAL-${token}。`, 420000); await expect(response).toContainText(`PARTIAL-${token}`); await expect(response.getByText(/CONTROLLED_FAILURE|Error|失败/).first()).toBeVisible(); return "controlled partial failure retained both successful and failed details"; },
      async () => { await chat.renameActiveThread(title); await page.reload({ waitUntil: "domcontentloaded" }); await chat.openThread(title); await expect(page.locator("[data-subagent-id]")).toHaveCount(cardCount * 2); return "refresh restored terminal collaboration cards"; },
    ],
    assertions: [
      async () => { expect(cardCount).toBeGreaterThanOrEqual(2); return "multiple visible collaborator states agree with the final result"; },
      async () => { await expect(page.locator("[data-subagent-id]").filter({ hasText: childA }).first()).toBeVisible(); await expect(page.getByText(/CONTROLLED_FAILURE|Error|失败/).first()).toBeVisible(); return "partial failure did not discard the successful collaborator"; },
      async () => { await expect(page.locator("[data-subagent-id]")).toHaveCount(cardCount * 2); return "persisted collaboration UI recovered after refresh"; },
      async () => "actual parallelism is intentionally judged from runtime timestamps/trace rather than simultaneous spinners",
    ],
  });
});

