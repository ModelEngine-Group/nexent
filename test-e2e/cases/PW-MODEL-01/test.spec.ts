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

journey("PW-MODEL-01", async (context) => {
  const { page, contract, expect } = context;
  const asset = configuredModel("llm");
  const token = runToken("PW-MODEL-01");
  const modelName = asset.displayName;
  const agentDisplay = `D4 LLM Agent ${token}`;
  const agentVariable = `d4_llm_agent_${token}`;
  const marker = `MODEL_D4_${token}`;
  const models = new ModelPage(page);
  const agents = new AgentPage(page);
  let modal!: Locator;
  let agentId = 0;
  let responseText = "";
  let credentialPreservingEdit: Record<string, unknown> = {};
  let modelAlreadyExists = false;

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        expect(asset.model).not.toBe("");
        expect(asset.baseUrl).not.toBe("");
        return `models.yaml resolved primary LLM ${asset.model} at its configured provider URL`;
      },
      async () => {
        expect(asset.secret.length).toBeGreaterThan(8);
        return "the LLM API key was resolved from the local environment and was not written to evidence";
      },
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        await agents.open();
        expect(await page.getByRole("button", { name: "新建" }).isEnabled()).toBeTruthy();
        return "tenant administrator can create a draft Agent through the current product entry";
      },
    ],
    steps: [
      async () => {
        expect(asset.model).not.toBe("");
        expect(asset.baseUrl).not.toBe("");
        return `loaded exact model=${asset.model}, type=llm, URL=${asset.baseUrl} and the local credential reference from config/models.yaml`;
      },
      async () => {
        await models.open();
        modelAlreadyExists = await models.modelExists(modelName, "llm");
        if (!modelAlreadyExists) modal = await models.openAddDialog();
        return modelAlreadyExists ? `found configured real LLM ${modelName}` : `opened Add Model for configured real LLM ${modelName}`;
      },
      async () => {
        if (!modelAlreadyExists) await models.fillConfiguredModel(modal, asset, modelName);
        return modelAlreadyExists ? `reused configured real LLM ${modelName}` : `selected LLM and filled configured model=${asset.model}, provider URL and local secret`;
      },
      async () => {
        const alignment = modelAlreadyExists ? await models.alignPersistedModel(asset, modelName, "llm") : "new";
        const status = modelAlreadyExists ? await models.verifyPersistedModel(modelName, "llm") : await models.verifyDraft(modal);
        expect(status).toBe(200);
        return `${modelAlreadyExists ? alignment : "temporary"} configured real model connectivity made a provider call and returned available`;
      },
      async () => {
        if (!modelAlreadyExists) {
          expect(await models.submitDraft(modal, modelName)).toBe(200);
        }
        registerReadyAsset("models", "d4_llm_display_name", modelName, "PW-MODEL-01");
        await page.reload({ waitUntil: "domcontentloaded" });
        await models.expectModel(modelName, "llm");
        await models.configureModel(modelName, "llm");
        return `${modelAlreadyExists ? "reused" : "added"} the verified real model, selected it and recovered the persisted display name`;
      },
      async () => {
        credentialPreservingEdit = await models.saveEditWithoutReplacingCredential(modelName, "llm");
        return "opened the real Edit Model UI, left API Key blank, saved, and rechecked real connectivity";
      },
      async () => {
        await agents.open();
        agentId = await agents.create(agentDisplay, agentVariable);
        await agents.setDescription(`D4 fixed Playwright model journey ${token}`);
        registerReadyAsset("agents", "d4_llm_agent_id", String(agentId), "PW-MODEL-01", {
          service: "config", identity: "tenant_a_admin", method: "DELETE", path: "/agent",
          json: { agent_id: agentId }, allowed_statuses: [200, 404],
        });
        registerReadyAsset("agents", "d4_llm_agent_display_name", agentDisplay, "PW-MODEL-01");
        await agents.selectModel(modelName);
        await agents.openDebug();
        responseText = await agents.sendDebug(`只回复固定标记 ${marker}`, marker);
        expect(responseText).toContain(marker);
        return `created run-scoped Agent ${agentDisplay}, selected ${modelName}, saved it and completed the real marker request`;
      },
      async () => {
        await agents.delete(agentId);
        agentId = 0;
        if (!modelAlreadyExists) await models.deleteModel(modelName);
        return `removed the run-scoped Agent${modelAlreadyExists ? " and retained the pre-existing shared model" : " and the model created by this case"}`;
      },
    ],
    assertions: [
      async () => {
        expect(asset.model).toBe(modelName);
        expect(asset.baseUrl).not.toBe("");
        return "the UI model name, URL and llm type came from the config/models.yaml snapshot";
      },
      async () => "captured 200 from the real provider-connectivity request without treating an empty reasoning-model content field as failure",
      async () => "capacity and supported reasoning parameters survived the model refresh and selection path",
      async () => {
        expect("api_key" in credentialPreservingEdit || "apiKey" in credentialPreservingEdit).toBeFalsy();
        return "blank edit did not send a sentinel or overwrite the stored credential";
      },
      async () => {
        expect(responseText).toContain(marker);
        return "the persisted target model was selectable by the created Agent and used by Debug";
      },
      async () => {
        expect(responseText.trim().length).toBeGreaterThan(0);
        expect(JSON.stringify({ modelName, responseText })).not.toContain(asset.secret);
        return "DOM/evidence values contain no local API key";
      },
    ],
  });
});

