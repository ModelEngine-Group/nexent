import type { Locator } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { configuredModel, runToken, testAssetPath } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { ModelPage } from "../../infra/automation/d4/pages/model.page";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";
import { registerReadyAsset } from "../../infra/automation/d4/runner/assets";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { KnowledgePage } from "../../infra/automation/d4/pages/knowledge.page";

journey("PW-PROMPT-01", async (context) => {
  const { page, expect } = context;
  const token = runToken("PW-PROMPT-01");
  const baseDuty = `D4 prompt duty ${token}`;
  const constraint = `D4 constraint keep unrelated fields ${token}`;
  const fewShots = `Q: marker?\nA: D4_FEWSHOT_${token}`;
  const agents = new AgentPage(page);
  let targetAgent = "";
  let alternateAgent = "";
  let modelName = "";
  let generatedDuty = "";
  let finalDuty = "";
  let originalDescription = "";
  let aiCalls = 0;

  const assertUnrelatedPrompts = async () => {
    await agents.openSection("模型与提示词");
    await page.getByRole("tab", { name: "使用要求", exact: true }).click();
    await expect(page.getByPlaceholder(/请输入此智能体的使用要求或约束条件/)).toHaveValue(constraint);
    await page.getByRole("tab", { name: "示例", exact: true }).click();
    await expect(page.getByPlaceholder(/请输入示例问答，帮助智能体理解预期行为/)).toHaveValue(fewShots);
  };

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        targetAgent = resolveReadyAsset("agents", "d4_llm_agent_display_name", "PW-PROMPT-01");
        alternateAgent = resolveReadyAsset("agents", "d4_basic_display_name", "PW-PROMPT-01");
        await agents.open();
        await agents.select(targetAgent);
        await agents.openSection("展示信息");
        originalDescription = await page.getByPlaceholder("请输入智能体描述").inputValue();
        expect(originalDescription.trim()).not.toBe("");
        return `selected editable Draft ${targetAgent} with a persisted real LLM; alternate=${alternateAgent}`;
      },
      async () => {
        modelName = resolveReadyAsset("models", "d4_llm_display_name", "PW-PROMPT-01");
        const section = await agents.openSection("模型与提示词");
        await expect(section).toContainText(modelName);
        return `selected Draft exposes configured real Prompt model ${modelName}`;
      },
      async () => {
        expect(baseDuty).toContain(token);
        expect(constraint).toContain(token);
        expect(fewShots).toContain(token);
        return "prepared independent run-scoped duty, constraint and few-shots values for a scoped NL2Agent Prompt revision";
      },
    ],
    steps: [
      async () => {
        await agents.openSection("模型与提示词");
        await expect(page.getByRole("tab", { name: "智能体角色", exact: true })).toBeVisible();
        await expect(page.getByRole("tab", { name: "使用要求", exact: true })).toBeVisible();
        await expect(page.getByRole("tab", { name: "示例", exact: true })).toBeVisible();
        await page.getByRole("button", { name: "智能生成", exact: true }).click();
        const generationPanel = page.locator("section").filter({ has: page.getByRole("heading", { name: "智能生成", exact: true }) }).first();
        await expect(generationPanel).toBeVisible();
        await expect(generationPanel.getByRole("button", { name: /生成提示词/ })).toBeVisible();
        return "located the three Prompt tabs and the current intelligent-generation suggestion";
      },
      async () => {
        await agents.setPrompts({ duty: baseDuty, constraint, fewShots });
        return "entered the fixed base Prompt and preserved constraint/few-shots fields through autosave";
      },
      async () => {
        const generationPanel = page.locator("section").filter({ has: page.getByRole("heading", { name: "智能生成", exact: true }) }).first();
        await generationPanel.getByRole("button", { name: /生成提示词/ }).click();
        const composer = generationPanel.locator("textarea:visible").first();
        await expect(composer).toBeEnabled();
        await expect(composer).not.toHaveValue("");
        await composer.fill(`仅修改当前智能体的“智能体角色”职责提示词：用清晰中文描述职责并保留字面标记 ${token}。不要修改使用要求、示例、模型、作者、描述、工具或其他配置；不需要新增资源。`);
        return "used the mounted Generate Prompts suggestion and constrained the revision to the role Prompt";
      },
      async () => {
        const generationPanel = page.locator("section").filter({ has: page.getByRole("heading", { name: "智能生成", exact: true }) }).first();
        const response = page.waitForResponse((r) => r.request().method() === "POST" && r.url().includes("/api/agent/nl2agent/run") && String(r.request().postDataJSON()?.query || "").includes(token), { timeout: 120000 });
        await generationPanel.locator("textarea:visible").first().press("Enter");
        const completed = await response;
        if (!completed.ok()) throw new Error(`NL2Agent Prompt request returned ${completed.status()}`);
        aiCalls += 1;
        return "the real NL2Agent Prompt revision was submitted through the product UI";
      },
      async () => {
        await agents.openSection("模型与提示词");
        await page.getByRole("tab", { name: "智能体角色", exact: true }).click();
        const duty = page.getByPlaceholder(/请输入智能体的角色、职责和能力/);
        await expect(duty).not.toHaveValue(baseDuty, { timeout: 300000 });
        generatedDuty = await duty.inputValue();
        expect(generatedDuty.trim()).not.toBe("");
        expect(generatedDuty).toContain(token);
        await assertUnrelatedPrompts();
        return "the real model changed the role Prompt while retaining unrequested Prompt fields";
      },
      async () => {
        finalDuty = `${generatedDuty}\nD4_PROMPT_EXPANDED_${token}`;
        await agents.expandDutyPrompt(finalDuty);
        await assertUnrelatedPrompts();
        return "manually refined the generated role Prompt in the current expanded editor and observed autosave";
      },
      async () => {
        await agents.select(alternateAgent);
        await agents.select(targetAgent);
        await agents.openSection("模型与提示词");
        await page.getByRole("tab", { name: "智能体角色", exact: true }).click();
        await expect(page.getByPlaceholder(/请输入智能体的角色、职责和能力/)).toHaveValue(finalDuty);
        return "switching to another Agent and back retained the generated and manually refined Prompt";
      },
      async () => {
        await page.reload({ waitUntil: "domcontentloaded" });
        await agents.select(targetAgent);
        await agents.openSection("模型与提示词");
        await page.getByRole("tab", { name: "智能体角色", exact: true }).click();
        await expect(page.getByPlaceholder(/请输入智能体的角色、职责和能力/)).toHaveValue(finalDuty);
        return "full reload retained the final Prompt in the server-backed Draft";
      },
    ],
    assertions: [
      async () => {
        expect(aiCalls).toBe(1);
        expect(generatedDuty).not.toBe(baseDuty);
        expect(generatedDuty).toContain(token);
        return "one real NL2Agent run generated a changed role Prompt through the current UI";
      },
      async () => {
        await assertUnrelatedPrompts();
        await agents.openSection("展示信息");
        await expect(page.getByPlaceholder("请输入智能体描述")).toHaveValue(originalDescription);
        await agents.openSection("模型与提示词");
        await expect(page.getByText(modelName, { exact: true }).first()).toBeVisible();
        return "generation and manual refinement did not overwrite unrelated Prompt, description, or model fields";
      },
      async () => {
        await agents.openSection("模型与提示词");
        await page.getByRole("tab", { name: "智能体角色", exact: true }).click();
        await expect(page.getByPlaceholder(/请输入智能体的角色、职责和能力/)).toHaveValue(finalDuty);
        return "server autosave retained the AI-generated and locally refined Prompt after reselection and refresh";
      },
    ],
  });
});

