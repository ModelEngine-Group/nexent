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

journey("PW-AGENT-02", async (context) => {
  const { page, expect } = context;
  const token = runToken("PW-AGENT-02");
  const opening = `D4 Advanced greeting ${token}`;
  const example = `知识库标记是什么 ${token}`;
  const guardrailPattern = `D4_FORBIDDEN_${token}`;
  const marker = "NX-92831";
  const agents = new AgentPage(page);
  let mainAgent = "";
  let collaborator = "";
  let knowledgeName = "";
  let answer = "";

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        mainAgent = resolveReadyAsset("agents", "d4_llm_agent_display_name", "PW-AGENT-02");
        collaborator = resolveReadyAsset("agents", "d4_chat_display_name", "PW-AGENT-02");
        await agents.open();
        await agents.select(mainAgent);
        return `resolved main Agent ${mainAgent} and internally published collaborator ${collaborator}`;
      },
      async () => {
        knowledgeName = resolveReadyAsset("knowledge", "d4_local_name", "PW-AGENT-02");
        expect(knowledgeName).not.toBe("");
        return `resolved READY Local knowledge base ${knowledgeName}`;
      },
      async () => {
        expect(configuredModel("llm").secret.length).toBeGreaterThan(8);
        return "a real configured LLM and its local secret are available for Advanced Debug";
      },
    ],
    steps: [
      async () => {
        await agents.openBasic();
        return `selected main Agent ${mainAgent}; Config opened on the Basic tab`;
      },
      async () => {
        await agents.bindKnowledgeBase(knowledgeName);
        return `bound READY knowledge base ${knowledgeName}`;
      },
      async () => {
        await agents.setConversationGuide(opening, example);
        return "configured the run-scoped greeting and example question through current Conversation Guide inputs";
      },
      async () => {
        await agents.openAdvanced();
        return "switched to the Advanced tab and opened Collaborative Agent configuration";
      },
      async () => {
        await agents.bindInternalCollaborator(collaborator, "daily-baseline");
        return `selected published internal collaborator ${collaborator} with its visible version; no external A2A discovery was used`;
      },
      async () => {
        await agents.ensureGuardrailRule(guardrailPattern);
        return `enabled Guardrail and persisted a stable non-triggering regex ${guardrailPattern}`;
      },
      async () => {
        await agents.openBasic();
        await expect(page.getByText(knowledgeName, { exact: true }).first()).toBeVisible();
        await agents.openAdvanced();
        await expect(page.getByText(collaborator, { exact: true }).first()).toBeVisible();
        return "Basic→Advanced round trip retained collaborator and knowledge selections";
      },
      async () => {
        await agents.openDebug();
        return "Debug waited for the autosave/save guard and opened the real composer";
      },
      async () => {
        answer = await agents.sendDebug(`请读取知识库并让内部协作智能体确认，只回复固定标记 ${marker}`, marker);
        return "Debug sent the fixed KB-plus-collaboration question and waited for the real stream to finish";
      },
      async () => {
        expect(answer).toContain(marker);
        await page.reload({ waitUntil: "domcontentloaded" });
        await agents.select(mainAgent);
        await agents.openAdvanced();
        await agents.openSection("协作智能体");
        await expect(page.getByText(collaborator, { exact: true }).first()).toBeVisible();
        await agents.openBasic();
        await agents.openSection("知识库");
        await expect(page.getByText(knowledgeName, { exact: true }).first()).toBeVisible();
        await agents.openSection("会话引导");
        await expect(page.getByPlaceholder("请输入用户首次进入会话时看到的开场白")).toHaveValue(opening);
        return "full refresh recovered collaborator, knowledge and Conversation Guide from persisted Advanced config";
      },
    ],
    assertions: [
      async () => {
        await agents.openAdvanced();
        await expect(page.getByText(collaborator, { exact: true }).first()).toBeVisible();
        await agents.openBasic();
        await expect(page.getByText(knowledgeName, { exact: true }).first()).toBeVisible();
        return "all Advanced modules used product autosave and survived refresh";
      },
      async () => {
        await agents.openAdvanced();
        await agents.openSection("协作智能体");
        await expect(page.getByText(collaborator, { exact: true }).first()).toBeVisible();
        expect(await page.getByText("外部", { exact: true }).count()).toBe(0);
        return "the relation is an internal published Agent and is not an external A2A relation";
      },
      async () => {
        expect(answer).toContain(marker);
        return `real Debug returned the fixed knowledge oracle ${marker} with the configured Advanced state visible`;
      },
    ],
  });
});

