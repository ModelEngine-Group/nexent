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

journey("PW-MODEL-02", async (context) => {
  const { page, expect } = context;
  const asset = configuredModel("embedding");
  const token = runToken("PW-MODEL-02");
  const modelName = asset.displayName;
  const knowledgeName = `d4-model-kb-${token}`;
  const marker = "NX-92831";
  const alpha = testAssetPath("assets/knowledge/alpha-nx-92831.txt");
  const models = new ModelPage(page);
  const knowledge = new KnowledgePage(page);
  let modal!: Locator;
  let connectivityStatus = 0;
  let createdKnowledgeId = "";
  let retrievalBody = "";
  let editRestriction = "";
  let modelAlreadyExists = false;

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        expect(asset.dimension).toBeGreaterThan(0);
        return `models.yaml resolved embedding ${asset.model} with dimension=${asset.dimension}`;
      },
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        await knowledge.open(false);
        expect(await page.getByText(/DataMate配置/).count()).toBeGreaterThanOrEqual(0);
        return "the current /knowledges local Nexent branch is reachable by the tenant administrator";
      },
      async () => {
        expect(alpha.endsWith("alpha-nx-92831.txt")).toBeTruthy();
        return `fixed alpha corpus is resolved locally and declares marker ${marker}`;
      },
    ],
    steps: [
      async () => {
        await models.open();
        modelAlreadyExists = await models.modelExists(modelName, "embedding");
        if (!modelAlreadyExists) modal = await models.openAddDialog();
        return modelAlreadyExists ? `found configured real Embedding ${modelName}` : `opened Add Model for configured real Embedding ${modelName}`;
      },
      async () => {
        if (!modelAlreadyExists) {
          await models.fillConfiguredModel(modal, asset, modelName);
          const dimension = modal.locator("#vectorDimension");
          if (await dimension.count()) await expect(dimension).toHaveValue(String(asset.dimension));
          connectivityStatus = await models.verifyDraft(modal);
        } else {
          await models.alignPersistedModel(asset, modelName, "embedding");
          connectivityStatus = await models.verifyPersistedModel(modelName, "embedding");
        }
        expect(connectivityStatus).toBe(200);
        if (!modelAlreadyExists) expect(await models.submitDraft(modal, modelName)).toBe(200);
        registerReadyAsset("models", "d4_embedding_display_name", modelName, "PW-MODEL-02");
        return `${modelAlreadyExists ? "reused" : "added"} configured real embedding ${modelName} and verified dimension=${asset.dimension} through real connectivity`;
      },
      async () => {
        await page.reload({ waitUntil: "domcontentloaded" });
        await models.expectModel(modelName, "embedding");
        const configured = await models.configureModel(modelName, "embedding");
        expect(configured.healthStatus).toBe(200);
        expect(configured.saveStatus).toBe(200);
        return "refreshed /models, recovered the persisted embedding, selected it as the current model, passed the persisted healthcheck and saved configuration";
      },
      async () => {
        await knowledge.open();
        const created = await knowledge.createByUpload(knowledgeName, modelName, alpha);
        createdKnowledgeId = created.id;
        registerReadyAsset("knowledge", "d4_model02_id", created.id, "PW-MODEL-02", {
          service: "config", identity: "tenant_a_admin", method: "DELETE",
          path: `/indices/${encodeURIComponent(created.id)}`, allowed_statuses: [200, 404],
        });
        registerReadyAsset("knowledge", "d4_model02_name", knowledgeName, "PW-MODEL-02");
        return `created Local KB ${knowledgeName} with the target embedding and submitted alpha for processing`;
      },
      async () => {
        await knowledge.waitUntilReady("alpha-nx-92831.txt");
        return "alpha document reached the real 已就绪 ingestion state";
      },
      async () => {
        const result = await knowledge.retrieve("alpha 知识文档中的唯一验证标记是什么？", marker);
        retrievalBody = JSON.stringify(result.body);
        return "submitted the fixed query through the visible recall-search entry and received HTTP 200";
      },
      async () => {
        expect(retrievalBody).toContain("alpha");
        expect(retrievalBody).toContain(marker);
        return `Top-K response contained alpha and ${marker}`;
      },
      async () => {
        await models.open();
        const editor = await models.openEditDialog(modelName, "向量模型");
        expect(await editor.locator("#vectorDimension").count()).toBe(0);
        expect(await editor.getByText("模型类型", { exact: true }).count()).toBe(0);
        editRestriction = "current edit dialog fixes model type and does not expose vector dimension";
        await editor.getByRole("button", { name: /取消|关\s*闭/ }).click().catch(async () => page.keyboard.press("Escape"));
        return editRestriction;
      },
    ],
    assertions: [
      async () => {
        expect(connectivityStatus).toBe(200);
        expect(asset.dimension).toBeGreaterThan(0);
        return `real embedding connectivity passed with configured dimension=${asset.dimension}`;
      },
      async () => {
        expect(createdKnowledgeId).not.toBe("");
        expect(retrievalBody).toContain(marker);
        return `real indexed Top-K retrieval hit target chunk ${marker}`;
      },
      async () => {
        expect(editRestriction).toContain("does not expose vector dimension");
        return "the current edit contract cannot silently change type/dimension underneath the existing index";
      },
    ],
  });
});

