// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

journey("TPC-D4-001", async context => {
  const { page, expect, contract } = context;
  const chat = new ChatPage(page);
  let cfg: any;
  let conversationId: number | undefined;
  let title = "";
  const code = () => chat.assistantMessages().last().getByRole("button", { name: /Executed code/ });
  const skill = () => chat.assistantMessages().last().getByRole("button", { name: "Used tool: read_skill_md", exact: true });
  const expandExecution = async () => {
    const message = chat.assistantMessages().last();
    for (const reasoning of await message.getByRole("button", { name: "Reasoning", exact: true }).all()) {
      if ((await reasoning.getAttribute("aria-expanded")) !== "true") await reasoning.click();
    }
    await expect(code()).toBeVisible();
    if ((await code().getAttribute("aria-expanded")) !== "true") await code().click();
    for (const group of await message.locator('[data-slot="tool-group-trigger"]').all()) {
      if ((await group.getAttribute("data-state")) === "closed") await group.click();
    }
    await expect(skill()).toBeVisible();
    if ((await skill().getAttribute("aria-expanded")) !== "true") await skill().click();
  };
  contract.deferCleanup(async () => {
    if (conversationId) await chat.deleteConversationById(conversationId);
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        const python = process.env.FIXED_TEST_PYTHON, repo = process.env.NEXENT_REPO;
        if (!python || !repo) throw new Error("Configured test interpreter and repository are required");
        try {
          const result = await promisify(execFile)(python, [join(repo, "test-e2e/infra/automation/d4/tpc_client.py")],
            { env: process.env, timeout: 180000 });
          cfg = JSON.parse(result.stdout);
        } catch { throw new Error("TPC owned fixture preparation failed; inspect the case asset journal"); }
        await loginCurrent(page, "tenant_a_admin");
        await chat.openAgent(cfg.agent_display);
        return "authenticated owner and freshly published Skill-bound Agent are ready";
      },
      async () => {
        const warning = page.getByRole("dialog", { name: /Embedding model not configured|尚未配置向量模型/ });
        if (await warning.isVisible()) {
          await warning.getByRole("button", { name: /^(关闭|Close)$/, exact: true }).click();
          await expect(warning).toBeHidden();
        }
        await expect(chat.composerInput()).toBeEditable();
        return "composer is usable; any missing-embedding warning was dismissed without changing settings";
      },
    ],
    steps: [
      async () => {
        const controlled = await page.request.post(`${cfg.provider}/__control`, { data: { responses: [
          `</think><code>skill_content = read_skill_md(skill_name="${cfg.skill_name}")\nprint(skill_content)</code>`,
          "</think><final_answer>TPC_SKILL_READ_OK</final_answer>",
        ] } });
        expect(controlled.status()).toBe(200);
        await chat.selectMode("执行");
        await chat.startMessage(`Read ${cfg.skill_name} and reply with exactly TPC_SKILL_READ_OK`);
        conversationId = chat.currentConversationId();
        await chat.waitForCompletion();
        await expandExecution();
        expect(await chat.messageText(chat.assistantMessages().last())).toBe("TPC_SKILL_READ_OK");
        title = await chat.currentThreadTitle();
        return "real Skill action executed once and explicit final answer displayed";
      },
      async () => {
        await page.reload({ waitUntil: "domcontentloaded" });
        await chat.openThread(title);
        await expandExecution();
        return "reopened the saved conversation and expanded the same Skill execution evidence";
      },
    ],
    assertions: [async () => {
      await expect(page.locator("body")).toContainText(cfg.skill_name);
      const history = await page.request.get(`/api/conversation/${conversationId}`);
      expect(history.status()).toBe(200);
      const payload = await history.json();
      expect(payload.code).toBe(0);
      const units = payload.data.flatMap((thread: any) => thread.message.flatMap((message: any) =>
        message.role === "assistant" && Array.isArray(message.message) ? message.message : []));
      expect(units.filter((unit: any) => unit.type === "execution_logs" && String(unit.content).includes("TPC_REAL_SKILL_CONTENT"))).toHaveLength(1);
      expect(units.filter((unit: any) => unit.type === "parse")).toHaveLength(1);
      expect(units.filter((unit: any) => unit.type === "final_answer").map((unit: any) => unit.content)).toEqual(["TPC_SKILL_READ_OK"]);
      expect(await chat.messageText(chat.assistantMessages().last())).toBe("TPC_SKILL_READ_OK");
      await expect(code()).toHaveCount(1);
      await expect(skill()).toHaveCount(1);
      await expect(page.locator("body")).not.toContainText("Connecting");
      await expect(page.locator("body")).not.toContainText("Thinking...");
      return "one persisted Skill action and final answer survive reload with no pending state";
    }],
  });
});
