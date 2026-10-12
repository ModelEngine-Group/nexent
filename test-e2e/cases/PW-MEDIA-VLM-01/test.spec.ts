import { existsSync, statSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath, configuredModel } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";
import { ModelPage } from "../../infra/automation/d4/pages/model.page";

const root = () => process.env.TEST_ROOT || "";
const fixture = (name: string) => join(root(), "assets", "d4", name);

journey("PW-MEDIA-VLM-01", async (context) => {
  const { page, expect, contract } = context;
  const chat = new ChatPage(page);
  const image = fixture("vlm_number_7429.png");
  const agent = process.env.NEXENT_TEST_VLM_AGENT || "";
  const vlmConfig = configuredModel("vlm");
  const configuredVlmModel = vlmConfig.displayName;
  const preparedVlmModel = process.env.NEXENT_TEST_VLM_MODEL || "";
  let answer = "";
  let imageThreadTitle = "";
  let imageConversationId = 0;
  let emptyConversationId = 0;
  let imageBoundToOriginalMessage = false;
  contract.deferCleanup(async () => {
    if (emptyConversationId) await chat.deleteConversationById(emptyConversationId);
    if (imageConversationId) await chat.deleteConversationById(imageConversationId);
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        expect(agent).not.toBe("");
        expect(configuredVlmModel).not.toBe("");
        expect(preparedVlmModel).toBe(configuredVlmModel);
        return `explicit VLM Agent ${agent} is bound to the exact models.yaml model/display name ${configuredVlmModel}`;
      },
      async () => { expect(existsSync(image)).toBe(true); return `deterministic image fixture exists: ${image}`; },
      async () => { await loginCurrent(page, "tenant_a_admin"); return "tenant administrator session is ready for model and chat verification"; },
    ],
    steps: [
      async () => {
        const models = new ModelPage(page);
        await models.open();
        // Multimodal Agent chat uses an LLM registry record, as prepared by
        // _resolve_multimodal_chat_model; the vision oracle remains the image answer.
        const modelRow = models.libraryRow(configuredVlmModel);
        await expect(modelRow).toBeVisible();
        return `confirmed the configured multimodal chat model has the exact UI name ${configuredVlmModel}; connectivity was preflighted`;
      },
      async () => { await chat.openAgent(agent); return `opened chat with VLM Agent ${agent}`; },
      async () => { await chat.uploadAttachment(image); return "clicked the Composer attachment entry and uploaded vlm_number_7429.png through its file chooser"; },
      async () => { await expect(page.getByText("vlm_number_7429.png", { exact: true })).toBeVisible({ timeout: 120000 }); return "image upload completed and its attachment card appeared"; },
      async () => { await chat.startMessage("图片中的测试编号是什么？只回复编号。"); return "sent the fixed image question with the uploaded attachment and captured its server conversation ID"; },
      async () => { const response = chat.assistantMessages().last(); await expect(response).toContainText("7429", { timeout: 300000 }); answer = await response.innerText(); imageThreadTitle = await chat.currentThreadTitle(); imageConversationId = chat.currentConversationId(); return `real multimodal streaming completed in conversation ${imageConversationId}`; },
      async () => { expect(answer).toContain("7429"); await expect(page.getByRole("button", { name: "预览 vlm_number_7429.png", exact: true })).toBeVisible(); imageBoundToOriginalMessage = true; return "VLM answer contains 7429 and the image remains bound to its original message"; },
      async () => { await chat.newConversation(agent); const response = await chat.sendAndWait("图片中的测试编号是什么？如果当前没有图片，只回复NO_IMAGE。"); emptyConversationId = chat.currentConversationId(); await expect(response).toContainText("NO_IMAGE", { timeout: 300000 }); return `conversation ${emptyConversationId} did not inherit the prior image context`; },
    ],
    assertions: [
      async () => { expect(imageBoundToOriginalMessage).toBe(true); expect(imageThreadTitle).not.toBe(""); expect(imageConversationId).toBeGreaterThan(0); return "image attachment binding was observed before switching away from the original server conversation"; },
      async () => { expect(answer).toContain("7429"); return "real VLM marker oracle passed"; },
      async () => { await expect(chat.assistantMessages().filter({ hasText: "7429" })).toHaveCount(0); return "the current no-image conversation contains no 7429 marker, so the prior image context did not leak"; },
    ],
  });
});

