// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";

journey("PW-PROMPT-01", async (context) => {
  const { page, expect } = context;
  const token = runToken("PW-PROMPT-01");
  const baseDuty = `D4 prompt duty ${token}`;
  const agents = new AgentPage(page);
  const prompt = page.locator("#agent-primary-prompt");
  const generationPanel = page.getByTestId("agent-config-conversation-panel");
  let targetAgent = "";
  let alternateAgent = "";
  let modelName = "";
  let generatedDuty = "";
  let finalDuty = "";
  let originalConfig: Record<string, unknown> = {};
  let aiCalls = 0;

  const unrelatedConfig = async () => {
    const agentId = Number(new URL(page.url()).pathname.split("/").at(-1));
    const response = await page.request.post("/api/agent/search_info", { data: { agent_id: agentId, version_no: 0 } });
    expect(response.ok()).toBeTruthy();
    const payload = await response.json();
    const body = payload.data || payload;
    expect(Number(body.agent_id || body.id)).toBe(agentId);
    const fields = ["name", "display_name", "author", "description", "model_ids", "tools", "skills", "related_agent_ids", "greeting_message", "example_questions"];
    return Object.fromEntries(fields.map((field) => [field, body[field]]));
  };

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        targetAgent = resolveReadyAsset("agents", "d4_llm_agent_display_name", "PW-PROMPT-01");
        alternateAgent = resolveReadyAsset("agents", "d4_basic_display_name", "PW-PROMPT-01");
        await agents.open();
        await agents.select(targetAgent);
        await agents.openSection("基础信息");
        expect((await page.getByRole("textbox", { name: "智能体描述", exact: true }).inputValue()).trim()).not.toBe("");
        originalConfig = await unrelatedConfig();
        return `selected editable Draft ${targetAgent}; alternate=${alternateAgent}`;
      },
      async () => {
        modelName = resolveReadyAsset("models", "d4_llm_display_name", "PW-PROMPT-01");
        await expect(await agents.openSection("模型与提示词")).toContainText(modelName);
        return `selected Draft exposes configured real Prompt model ${modelName}`;
      },
      async () => {
        expect(baseDuty).toContain(token);
        return "prepared a run-scoped Prompt and captured unrelated persisted configuration";
      },
    ],
    steps: [
      async () => {
        await agents.openSection("模型与提示词");
        await expect(prompt).toBeVisible();
        if (!(await generationPanel.isVisible())) await page.getByRole("button", { name: "智能生成", exact: true }).click();
        await expect(generationPanel).toBeVisible();
        await expect(generationPanel.getByRole("button", { name: /生成提示词/ })).toBeVisible();
        return "located the current single Prompt editor and intelligent-generation suggestion";
      },
      async () => {
        await agents.setPrompts({ duty: baseDuty });
        expect(await unrelatedConfig()).toEqual(originalConfig);
        return "persisted the base Prompt without changing unrelated configuration";
      },
      async () => {
        await generationPanel.getByRole("button", { name: /生成提示词/ }).click();
        const composer = generationPanel.getByRole("textbox", { name: "对话输入", exact: true });
        await expect(composer).toBeEditable();
        await expect(composer).not.toBeEmpty();
        await composer.fill(`仅修改当前智能体的职责提示词，用清晰中文描述职责并保留字面标记 ${token}。不要修改模型、作者、描述、工具、技能、开场白、示例问题或其他配置，不新增资源。`);
        return "constrained the revision to the current Prompt";
      },
      async () => {
        const response = page.waitForResponse((r) => r.request().method() === "POST" && r.url().includes("/api/agent/nl2agent/run") && String(r.request().postDataJSON()?.query || "").includes(token), { timeout: 120000 });
        await generationPanel.getByRole("textbox", { name: "对话输入", exact: true }).press("Enter");
        const completed = await response;
        expect(completed.ok()).toBeTruthy();
        const error = await completed.finished();
        if (error) throw error;
        aiCalls += 1;
        return "one real NL2Agent Prompt revision completed through the product UI";
      },
      async () => {
        await agents.openSection("模型与提示词");
        await expect(prompt).not.toHaveValue(baseDuty, { timeout: 300000 });
        await expect(prompt).toHaveValue(new RegExp(token));
        generatedDuty = await prompt.inputValue();
        expect(generatedDuty.trim()).not.toBe("");
        expect(await unrelatedConfig()).toEqual(originalConfig);
        return "the generated Prompt changed and retained its marker without altering unrelated fields";
      },
      async () => {
        finalDuty = `${generatedDuty}\nD4_PROMPT_REFINED_${token}`;
        await agents.setPrompts({ duty: finalDuty });
        expect(await unrelatedConfig()).toEqual(originalConfig);
        return "manually refined the current Prompt editor and observed autosave";
      },
      async () => {
        await agents.select(alternateAgent);
        await agents.select(targetAgent);
        await agents.openSection("模型与提示词");
        await expect(prompt).toHaveValue(finalDuty);
        return "switching Agents retained the generated and manually refined Prompt";
      },
      async () => {
        await page.reload({ waitUntil: "domcontentloaded" });
        await agents.openSection("模型与提示词");
        await expect(prompt).toHaveValue(finalDuty);
        return "full reload retained the final server-backed Prompt";
      },
    ],
    assertions: [
      async () => {
        expect(aiCalls).toBe(1);
        expect(generatedDuty).not.toBe(baseDuty);
        expect(generatedDuty).toContain(token);
        return "one real generation changed the Prompt and preserved its required marker";
      },
      async () => {
        expect(await unrelatedConfig()).toEqual(originalConfig);
        await expect(await agents.openSection("模型与提示词")).toContainText(modelName);
        return "generation and manual refinement preserved unrelated persisted fields and bindings";
      },
      async () => {
        await expect(prompt).toHaveValue(finalDuty);
        return "autosave survived Agent reselection and full refresh";
      },
    ],
  });
});
