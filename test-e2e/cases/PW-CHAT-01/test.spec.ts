import { existsSync, readFileSync } from "node:fs";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

journey("PW-CHAT-01", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-CHAT-01");
  const firstTitle = `chat-stop-${token}`;
  const secondTitle = `chat-isolation-${token}`;
  const firstMarker = `NX-CHAT-A-${token}`;
  const secondMarker = `NX-CHAT-B-${token}`;
  const chat = new ChatPage(page);
  let agentDisplay = "";
  let stoppedText = "";
  let originalThreadTitle = "";

  contract.deferCleanup(async () => {
    for (const title of [firstTitle, secondTitle, originalThreadTitle].filter(Boolean)) {
      if (await page.getByRole("button", { name: title, exact: true }).count()) await chat.deleteThread(title);
    }
  });

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        agentDisplay = resolveReadyAsset("agents", "d4_chat_display_name", "PW-CHAT-01");
        await chat.openAgent(agentDisplay);
        return `selected published real-LLM Agent ${agentDisplay}`;
      },
      async () => "prepared deterministic long-output and continuation prompts with run-scoped markers",
    ],
    steps: [
      async () => `opened /newchat and selected ${agentDisplay}`,
      async () => {
        await chat.selectMode("执行");
        return "selected the product's Execution mode; no independent ReAct control was assumed";
      },
      async () => {
        const message = await chat.startMessage(`先原样输出标记 ${firstMarker}，再逐项详细列出 1 到 80，每项写一句不同的说明。`);
        await expect.poll(async () => chat.messageText(message), { timeout: 120_000 }).toContain(firstMarker);
        return "assistant message appeared and grew through the real streaming channel";
      },
      async () => {
        const message = chat.assistantMessages().last();
        await chat.stopGeneration();
        stoppedText = await chat.assertTextStopsChanging(message);
        expect(stoppedText.length).toBeGreaterThan(0);
        return `Stop terminated the old stream at ${stoppedText.length} visible characters`;
      },
      async () => {
        const response = await chat.sendAndWait(`只回复：CONTINUE-${token}`);
        const text = (await response.innerText()).trim();
        if (/已有智能体任务正在运行|task.*already.*running/i.test(text)) {
          const error = new Error("Stop API returned success but the next turn was rejected as still running: " + text);
          error.name = "ProductFailure";
          throw error;
        }
        expect(text).toContain("CONTINUE-" + token);
        return "the stopped conversation accepted and completed a second message";
      },
      async () => {
        originalThreadTitle = await chat.currentThreadTitle();
        await page.reload({ waitUntil: "domcontentloaded" });
        await chat.openThread(originalThreadTitle);
        await expect(chat.userMessages().filter({ hasText: firstMarker })).toHaveCount(1);
        expect(await chat.messageText(chat.assistantMessages().first())).toBe(stoppedText);
        return "refresh plus sidebar reopen restored both history and the exact stopped assistant text";
      },
      async () => {
        await chat.renameActiveThread(firstTitle);
        await chat.newConversation(agentDisplay);
        await chat.sendAndWait(`只回复：${secondMarker}`);
        await chat.renameActiveThread(secondTitle);
        return "used the supported sidebar New action and renamed both run-scoped conversations";
      },
      async () => {
        await chat.openThread(firstTitle);
        await expect(chat.userMessages().filter({ hasText: secondMarker })).toHaveCount(0);
        await expect(chat.userMessages().filter({ hasText: firstMarker })).toHaveCount(1);
        await chat.openThread(secondTitle);
        await expect(chat.userMessages().filter({ hasText: firstMarker })).toHaveCount(0);
        await expect(chat.userMessages().filter({ hasText: secondMarker })).toHaveCount(1);
        return "switching the two named conversations preserved mutually isolated message histories";
      },
      async () => {
        await chat.deleteThread(secondTitle);
        return "deleted the second test conversation and observed its sidebar item disappear";
      },
    ],
    assertions: [
      async () => {
        expect(stoppedText.length).toBeGreaterThan(0);
        return "Execution used real streaming and the stopped message remained stable after cancellation";
      },
      async () => {
        await chat.openThread(firstTitle);
        await expect(chat.userMessages().filter({ hasText: `CONTINUE-${token}` })).toHaveCount(1);
        return "continuation and refreshed persistence remained consistent";
      },
      async () => {
        await expect(chat.userMessages().filter({ hasText: secondMarker })).toHaveCount(0);
        return "the remaining first conversation contains no message from the deleted isolated conversation";
      },
    ],
  });
});

