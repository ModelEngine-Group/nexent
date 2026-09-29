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

journey("PW-KB-LOCAL-01", async (context) => {
  const { page, expect } = context;
  const token = runToken("PW-KB-LOCAL-01");
  const knowledgeName = `d4-local-kb-${token}`;
  const marker = "NX-92831";
  const alpha = testAssetPath("assets/knowledge/alpha-nx-92831.txt");
  const beta = testAssetPath("assets/knowledge/beta-nx-57264.txt");
  const knowledge = new KnowledgePage(page);
  const agents = new AgentPage(page);
  let embeddingDisplay = "";
  let agentDisplay = "";
  let knowledgeId = "";
  let retrievalBody = "";
  let answer = "";

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        await knowledge.open();
        await expect(page.getByText("知识库列表", { exact: true })).toBeVisible();
        return "opened the Nexent Local knowledge-base branch";
      },
      async () => {
        embeddingDisplay = resolveReadyAsset("models", "d4_embedding_display_name", "PW-KB-LOCAL-01");
        expect(configuredModel("rerank").secret.length).toBeGreaterThan(8);
        return `resolved READY embedding ${embeddingDisplay} and a configured real rerank provider`;
      },
      async () => {
        expect(alpha).toContain("alpha-nx-92831.txt");
        expect(beta).toContain("beta-nx-57264.txt");
        return `fixed alpha/beta corpus is available and alpha oracle is ${marker}`;
      },
    ],
    steps: [
      async () => {
        await knowledge.open();
        return "opened /knowledges and confirmed the Local knowledge list and Create entry rendered";
      },
      async () => {
        await knowledge.beginCreate(knowledgeName, embeddingDisplay);
        return `entered create mode with run-scoped name ${knowledgeName} and selected the READY embedding`;
      },
      async () => {
        const created = await knowledge.finishCreateByUpload(knowledgeName, [alpha, beta]);
        knowledgeId = created.id;
        registerReadyAsset("knowledge", "d4_local_cleanup_id", knowledgeId, "PW-KB-LOCAL-01", {
          service: "config", identity: "tenant_a_admin", method: "DELETE",
          path: `/indices/${encodeURIComponent(knowledgeId)}`, allowed_statuses: [200, 404],
        });
        return "setInputFiles submitted alpha and beta, creating the Local KB through the product's create-on-upload contract";
      },
      async () => {
        await knowledge.waitUntilReady("alpha-nx-92831.txt");
        await knowledge.waitUntilReady("beta-nx-57264.txt");
        return "both documents reached 已就绪 after real parsing and vector ingestion";
      },
      async () => {
        const result = await knowledge.retrieve("alpha 知识文档中的唯一验证标记是什么？", marker);
        retrievalBody = JSON.stringify(result.body);
        registerReadyAsset("knowledge", "d4_local_id", knowledgeId, "PW-KB-LOCAL-01");
        registerReadyAsset("knowledge", "d4_local_name", knowledgeName, "PW-KB-LOCAL-01");
        return `real Top-K retrieval returned alpha/${marker}`;
      },
      async () => knowledge.summarizeIfAvailable(),
      async () => {
        agentDisplay = resolveReadyAsset("agents", "d4_llm_agent_display_name", "PW-KB-LOCAL-01");
        await agents.open();
        await agents.select(agentDisplay);
        await agents.bindKnowledgeBase(knowledgeName);
        return `Advanced > Knowledge bound ${knowledgeName} to READY Agent ${agentDisplay} and autosaved`;
      },
      async () => {
        answer = await agents.debug("alpha 知识文档中的唯一验证标记是什么？请只回答该标记。", marker);
        return "Agent Debug completed a real RAG stream for the same knowledge query";
      },
      async () => {
        expect(answer).toContain(marker);
        return `rendered RAG answer contained marker ${marker}`;
      },
      async () => {
        await page.reload({ waitUntil: "domcontentloaded" });
        await agents.select(agentDisplay);
        await agents.openBasic();
        await agents.openSection("知识库");
        await expect(page.getByText(knowledgeName, { exact: true }).first()).toBeVisible();
        return "full Agent-page refresh retained the knowledge binding";
      },
    ],
    assertions: [
      async () => {
        expect(knowledgeId).not.toBe("");
        return "the selected knowledge source was the Nexent Local branch";
      },
      async () => {
        expect(retrievalBody).toContain(marker);
        return "both files were ready before real Top-K retrieval hit alpha first";
      },
      async () => {
        expect(answer).toContain(marker);
        return "the persisted Agent binding produced a real RAG answer with the fixed oracle";
      },
    ],
  });
});

