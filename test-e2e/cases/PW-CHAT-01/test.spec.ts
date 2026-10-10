import { join } from "node:path";
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
  let stoppedHistory: Awaited<ReturnType<ChatPage["persistedMessages"]>> = [];
  let completedHistory: Awaited<ReturnType<ChatPage["persistedMessages"]>> = [];
  const ownedConversationIds = new Set<number>();
  // Stop validates an in-progress stream, including visible reasoning. Other
  // journeys still require final-answer Markdown through ChatPage.messageText.
  const streamText = async (message: ReturnType<ChatPage["assistantMessages"]>) => {
    const collapsed = message.locator('.aui-reasoning-root button[data-state="closed"]');
    while (await collapsed.count()) await collapsed.first().click();
    return (await message.locator(".aui-md:visible").allTextContents()).join("\n").trim();
  };

  contract.deferCleanup(async () => {
    try {
      if (ownedConversationIds.size) await chat.captureConversationState(join(contract.caseDir,"conversation-state.json"), `CONTINUE-${token}`);
    } finally {
      for (const id of ownedConversationIds) await chat.deleteConversationById(id);
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
        const message = await chat.startMessage(`先原样输出标记 ${firstMarker}，再逐项详细列出 1 到 1200，每项写一句不同的说明。必须逐项输出，不能使用代码、循环或省略号代替；这个长输出用于验证用户中途停止，不要提前总结。`);
        ownedConversationIds.add(chat.currentConversationId());
        await expect.poll(async () => (await streamText(message)).length, { timeout: 120_000 }).toBeGreaterThan(0);
        const initial = await streamText(message);
        await expect.poll(async () => (await streamText(message)).length, { timeout: 120_000 }).toBeGreaterThan(initial.length);
        await expect(page.locator("button:has(svg.lucide-square)")).toBeVisible();
        return "assistant message appeared and grew through the real streaming channel";
      },
      async () => {
        const message = chat.assistantMessages().last();
        await chat.stopGeneration();
        let stable = 0;
        stoppedText = await streamText(message);
        await expect.poll(async () => {
          const current = await streamText(message);
          stable = current === stoppedText ? stable + 1 : 0;
          stoppedText = current;
          return stable;
        }, { timeout: 15000, intervals: [1000] }).toBeGreaterThanOrEqual(4);
        expect(stoppedText.length).toBeGreaterThan(0);
        stoppedHistory = await chat.persistedMessages();
        const stoppedAssistant = stoppedHistory.filter((item) => item.role === "assistant");
        expect(stoppedAssistant).toHaveLength(1);
        expect(stoppedAssistant[0].status).toBe("stopped");
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
        if (!(await chat.messageText(response)).includes("CONTINUE-" + token)) {
          const error = new Error("The real continuation request completed after Stop but the final answer omitted its required CONTINUE marker; runtime/provider root cause requires retained evidence review");
          error.name = "ProductFailure";
          throw error;
        }
        completedHistory = await chat.persistedMessages();
        const assistants = completedHistory.filter((item) => item.role === "assistant");
        expect(assistants).toHaveLength(2);
        expect(assistants[0]).toEqual(stoppedHistory.filter((item) => item.role === "assistant")[0]);
        expect(assistants[1].status).toBe("completed");
        return "the stopped conversation accepted and completed a second message";
      },
      async () => {
        originalThreadTitle = await chat.currentThreadTitle();
        await page.reload({ waitUntil: "domcontentloaded" });
        await chat.openThread(originalThreadTitle);
        await expect(chat.userMessages().filter({ hasText: firstMarker })).toHaveCount(1);
        await expect(chat.userMessages()).toHaveCount(2);
        await expect(chat.assistantMessages()).toHaveCount(2);
        // Cancellation rolls back the uncommitted model attempt, including
        // transient thinking. Refresh must preserve committed history/status,
        // not reintroduce that abandoned attempt (OpenAIModel rollback hook).
        expect(await chat.persistedMessages()).toEqual(completedHistory);
        const parts = stoppedHistory.find((item) => item.role === "assistant")!.message;
        const final = Array.isArray(parts)
          ? parts.filter((part: any) => part.type === "final_answer").map((part: any) => String(part.content || "")).join("").trim()
          : String(parts || "").trim();
        await expect.poll(() => chat.messageText(chat.assistantMessages().first()), { timeout: 30000 }).toBe(final);
        await expect.poll(() => chat.messageText(chat.assistantMessages().last()), { timeout: 30000 }).toContain(`CONTINUE-${token}`);
        await expect(page.locator("button:has(svg.lucide-square)")).toHaveCount(0);
        return "refresh restored both committed messages, exact persisted stopped output/status, and completed continuation without reviving the cancelled stream";
      },
      async () => {
        await chat.renameActiveThread(firstTitle);
        await chat.newConversation(agentDisplay);
        await chat.startMessage(`只回复：${secondMarker}`);
        ownedConversationIds.add(chat.currentConversationId());
        await chat.waitForCompletion();
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
        const deletedId = chat.currentConversationId();
        await chat.deleteThread(secondTitle);
        ownedConversationIds.delete(deletedId);
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

