// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";
import { appPath } from "../../infra/automation/d4/runner/runtime-config";

const execute = promisify(execFile);
async function fixtures(operation: "setup" | "cleanup") {
  const python = process.env.FIXED_TEST_PYTHON, repo = process.env.NEXENT_REPO;
  if (!python || !repo) throw new Error("FAF requires the configured runner interpreter and repository");
  try {
    const result = await execute(python, [join(repo, "test-e2e/infra/automation/d4/faf_client.py"), operation],
      { env: process.env, timeout: 180_000 });
    return JSON.parse(result.stdout);
  } catch {
    throw new Error(`FAF fixture ${operation} failed; inspect the case asset journal`);
  }
}

journey("FAF-D4-001", async (context) => {
  const { page, expect, contract } = context;
  const chat = new ChatPage(page);
  const conversations: number[] = [];
  let agents: Record<string, { name: string; display_name: string }>;
  let currentKind = "";
  let parentConversationId = 0;
  const answer = (text: string) => chat.assistantMessages().last().locator("p").filter({ hasText: new RegExp(`^${text}$`) });
  const assertAnswer = async (text: string) => {
    const result = answer(text);
    await expect(result).toHaveCount(1);
    await expect(result).toBeVisible();
    expect(await result.evaluate(el => {
      const triggers = [...document.querySelectorAll("button[aria-controls]")]
        .filter(button => /^(Reasoning|步骤\s*\d+|Step\s*\d+)/.test((button.textContent ?? "").trim()));
      return triggers.some(button => {
        const id = button.getAttribute("aria-controls");
        return id && document.getElementById(id)?.contains(el);
      });
    })).toBe(false);
  };
  const run = async (kind: string) => {
    currentKind = kind;
    await chat.openAgent(agents[kind].display_name);
    await chat.selectMode("执行");
    await chat.startMessage("Execute the final-answer acceptance task.");
    conversations.push(chat.currentConversationId());
    await chat.waitForCompletion();
  };
  const expandChild = async () => {
    const group = chat.assistantMessages().last().getByRole("button", { name: "1 subagent call", exact: true });
    await expect(group).toBeVisible();
    if ((await group.getAttribute("aria-expanded")) !== "true") await group.click();
    const child = page.getByRole("button", { name: new RegExp(agents.child.display_name + " Completed") });
    await expect(child).toBeVisible();
    if ((await child.getAttribute("aria-expanded")) !== "true") await child.click();
    await assertAnswer("FAF-CHILD-OK");
    expect(await answer("FAF-CHILD-OK").evaluate(el => Boolean(el.closest("[data-subagent-id]")))).toBe(true);
  };
  contract.deferCleanup(async () => {
    try {
      // Record a started run even if completion failed before its step ended.
      try {
        const current = chat.currentConversationId();
        if (!conversations.includes(current)) conversations.push(current);
      } catch { /* no response header means no known owned conversation */ }
      if (conversations.length) await chat.captureConversationState(join(contract.caseDir, "conversation-state.json"), "FAF-");
    } finally {
      for (const id of conversations) await chat.deleteConversationById(id);
      await fixtures("cleanup");
    }
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { agents = await fixtures("setup"); },
      async () => { await loginCurrent(page, "tenant_a_admin"); },
    ],
    steps: [
      async () => {
        await run("mixed");
        await assertAnswer("FAF-MIXED-OK");
        const reasoning = chat.assistantMessages().last().getByRole("button", { name: "Reasoning", exact: true });
        await expect(reasoning).toHaveCount(1);
        if ((await reasoning.getAttribute("aria-expanded")) !== "true") await reasoning.click();
        const contentId = await reasoning.getAttribute("aria-controls");
        expect(contentId).toBeTruthy();
        await expect(page.locator(`[id="${contentId}"]`)).toContainText("检查已完成。");
        await reasoning.click();
        await assertAnswer("FAF-MIXED-OK");
      },
      async () => {
        await run("subagent");
        parentConversationId = chat.currentConversationId();
        await assertAnswer("FAF-PARENT-OK");
        await expandChild();
        await page.goto(appPath(`/newchat?conversation_id=${chat.currentConversationId()}`), { waitUntil: "domcontentloaded" });
        await assertAnswer("FAF-PARENT-OK");
        await expandChild();
      },
      async () => {
        await run("pure");
        await assertAnswer("FAF-PURE-OK");
        const response = await page.request.get(`/api/conversation/${chat.currentConversationId()}`);
        expect(response.status()).toBe(200);
        const rows = (await response.json()).data.flatMap((row: any) => row.message).filter((row: any) => row.role === "assistant");
        const parts = rows.flatMap((row: any) => typeof row.message === "string" ? JSON.parse(row.message) : row.message);
        if (parts.some((part: any) => part.type === "model_output_deep_thinking" && String(part.content ?? "").trim())) {
          const error = new Error("Configured real provider emitted genuine deep reasoning; pure-answer fixture was not obtained");
          error.name = "DependencyFailure";
          throw error;
        }
        await expect(chat.assistantMessages().last().getByRole("button", { name: "Reasoning", exact: true })).toHaveCount(0);
        expect(parts.filter((part: any) => ["step_count", "model_output_thinking", "model_output_deep_thinking"].includes(part.type))).toEqual([]);
        expect(parts.filter((part: any) => part.type === "final_answer").map((part: any) => part.content)).toEqual(["FAF-PURE-OK"]);
      },
    ],
    assertions: [
      async () => {
        await page.goto(appPath(`/newchat?conversation_id=${parentConversationId}`), { waitUntil: "domcontentloaded" });
        await assertAnswer("FAF-PARENT-OK"); await expandChild();
      },
      async () => { expect(conversations).toHaveLength(3); expect(new Set(conversations).size).toBe(3); },
      async () => { expect(currentKind).toBe("pure"); await expect(answer("FAF-CHILD-OK")).toHaveCount(1); },
    ],
  });
});
