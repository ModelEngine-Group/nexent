// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { existsSync, readFileSync } from "node:fs";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

journey("PW-CHAT-02", async (context) => {
  const { page, expect } = context;
  const token = runToken("PW-CHAT-02");
  const toolName = "get_test_code";
  const expectedCode = "NX-92831";
  const noToolMarker = `NO-TOOL-${token}`;
  const wirePath = process.env.NEXENT_TEST_MCP_WIRE_LOG || "";
  const chat = new ChatPage(page);
  const waitForVisibleAnswer = (message: ReturnType<ChatPage["assistantMessages"]>) =>
    expect(message.locator('[data-slot="aui_assistant-message-completion-indicator"]'))
      .toHaveText(/^(已完成|Completed?)$/, { timeout: 90_000 });
  let agentDisplay = "";
  let wireOffset = 0;
  let toolAnswer = "";
  let noToolAnswer = "";
  let completedToolCount = 0;
  let wireAfterTool = 0;
  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        agentDisplay = await chat.openPreparedAgent("d4_tool_chat", "PW-CHAT-02");
        return `selected published Agent ${agentDisplay}, whose Draft was bound to ${toolName} before publishing`;
      },
      async () => {
        expect(wirePath).not.toBe("");
        wireOffset = existsSync(wirePath) ? readFileSync(wirePath, "utf8").length : 0;
        return `controlled Test MCP is healthy and writes protocol evidence to ${wirePath}`;
      },
      async () => "the configured real LLM passed model connectivity checks and is expected to support tool calling",
    ],
    steps: [
      async () => {
        await chat.selectMode("执行");
        await expect(chat.composerInput()).toBeVisible();
        return `opened /newchat with ${agentDisplay} and confirmed Execution mode`;
      },
      async () => {
        const prompt = `必须调用工具 ${toolName}，不要猜测；工具完成后只回复它返回的测试编号。`;
        await chat.composerInput().fill(prompt);
        return `entered an explicit ${toolName} request`;
      },
      async () => {
        const prompt = await chat.composerText();
        await chat.startMessage(prompt);
        chat.registerOwnedConversation("PW-CHAT-02");
        return "sent the request and observed the real streaming turn start";
      },
      async () => {
        await expect(page.locator("[data-slot='tool-group-root']").last()).toBeVisible({ timeout: 180_000 });
        await expect(page.locator("[data-slot='tool-group-trigger']").last()).toBeVisible();
        return "the current DOM exposed a real tool-call group and execution state";
      },
      async () => {
        await waitForVisibleAnswer(chat.assistantMessages().last());
        const group = page.locator("[data-slot='tool-group-root']").last();
        const trigger = group.locator("[data-slot='tool-group-trigger']");
        if ((await trigger.getAttribute("data-state")) === "closed") await trigger.click();
        const completedTool = page.getByRole("button", { name: new RegExp(`(?:Used tool:|已使用工具[:：]?)\\s*${toolName}`) }).last();
        await expect(completedTool).toBeVisible();
        toolAnswer = await chat.messageText(chat.assistantMessages().last());
        return "tool execution reached complete state and the assistant produced its final answer";
      },
      async () => {
        expect(toolAnswer).toContain(expectedCode);
        return `the final answer contains deterministic marker ${expectedCode}`;
      },
      async () => {
        const delta = readFileSync(wirePath, "utf8").slice(wireOffset);
        const events = delta.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
        expect(events.some((event) => event.tool === toolName && event.result === expectedCode)).toBe(true);
        return `MCP wire JSONL proves a real ${toolName} invocation returned ${expectedCode}`;
      },
      async () => {
        const toolLabel = new RegExp("(?:Used tool:|已使用工具[:：]?)\\s*" + toolName);
        completedToolCount = await page.getByRole("button", { name: toolLabel }).count();
        wireAfterTool = readFileSync(wirePath, "utf8").length;
        const response = await chat.startMessage(`不要调用任何工具，只回复：${noToolMarker}`);
        await waitForVisibleAnswer(response);
        noToolAnswer = await chat.messageText(response);
        expect(noToolAnswer).toContain(noToolMarker);
        await expect(page.getByRole("button", { name: toolLabel })).toHaveCount(completedToolCount);
        expect(readFileSync(wirePath, "utf8").slice(wireAfterTool)).not.toContain('\"tool\": \"' + toolName + '\"');
        return "a no-tool follow-up completed without reusing get_test_code state; unrelated fresh built-in tool activity is not conflated with stale reuse";
      },
    ],
    assertions: [
      async () => {
        const composer = chat.composerInput();
        await composer.fill(`COMPOSER-READY-${token}`);
        await expect(page.getByRole("button", { name: "发送", exact: true })).toBeEnabled();
        await composer.fill("");
        expect(completedToolCount).toBeGreaterThan(0);
        return "Execution completed a real Tool call and the Composer still accepts input and enables Send";
      },
      async () => {
        expect(toolAnswer).toContain(expectedCode);
        const delta = readFileSync(wirePath, "utf8").slice(wireOffset);
        expect(delta).toContain(`\"tool\": \"${toolName}\"`);
        expect(delta).toContain(`\"result\": \"${expectedCode}\"`);
        return "both the user-visible marker and independent MCP wire evidence agree";
      },
      async () => {
        expect(noToolAnswer).toContain(noToolMarker);
        return "the no-tool follow-up is isolated; ReAct retry and max_steps remain assigned to AGENT-IT/contract tests";
      },
    ],
  });
});

