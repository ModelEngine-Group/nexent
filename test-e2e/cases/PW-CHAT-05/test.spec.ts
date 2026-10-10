import { existsSync, readFileSync } from "node:fs";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { runToken } from "../../infra/automation/d4/runner/runtime-config";
import { appPath } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

journey("PW-CHAT-05", async (context) => {
  const { page, expect, contract } = context;
  const chat = new ChatPage(page);
  const token = runToken("PW-CHAT-05");
  let title = "";
  const wire = process.env.NEXENT_TEST_MCP_WIRE_LOG || "";
  let agent = "";
  let knowledge = "";
  let offset = 0;
  let conversationId: number | undefined;
  contract.deferCleanup(async () => { if (conversationId) await chat.deleteConversationById(conversationId); });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { agent = resolveReadyAsset("agents", "d4_scope_display_name", "PW-CHAT-05"); return `scope Agent ${agent} is bound to the controlled MCP tools`;
      },
      async () => { knowledge = resolveReadyAsset("knowledge", "d4_local_name", "PW-CHAT-05"); return `READY distinguishable knowledge base ${knowledge}`; },
      async () => { expect(wire).not.toBe(""); offset = existsSync(wire) ? readFileSync(wire, "utf8").length : 0; return "real LLM and controlled metadata Tool wire are available"; },
    ],
    steps: [
      async () => { await loginCurrent(page, "tenant_a_admin"); await chat.openAgent(agent); return `opened /newchat with ${agent}`; },
      async () => { await chat.setRuntimeMetadata({ test_run_id: token }); return `saved test_run_id=${token} through Metadata editor`;
      },
      async () => { await chat.assertRuntimeMetadata({ test_run_id: token }); return "reopened Metadata and recovered the current-conversation value"; },
      async () => { await chat.selectKnowledge(knowledge); return `selected conversation knowledge scope ${knowledge}`; },
      async () => { const response = await chat.startMessage(`调用 require_metadata，参数test_run_id必须来自Metadata；同时检索知识库并回复 METADATA_OK:${token}。`); conversationId = chat.currentConversationId(); await chat.waitForCompletion(); await expect(response).toContainText(`METADATA_OK:${token}`); return "sent a real knowledge/metadata run"; },
      async () => { const delta = readFileSync(wire, "utf8").slice(offset); expect(delta).toContain(token); expect(delta).toContain("require_metadata"); return "answer marker and MCP wire prove runtime metadata use"; },
      async () => { title = await chat.currentThreadTitle(); await chat.newConversation(agent); await chat.assertRuntimeMetadata({}); await chat.assertKnowledgeSelected(knowledge, false); return "new conversation reset Metadata and did not inherit the previous conversation's selected knowledge base"; },
      async () => { await page.goto(appPath(`/newchat?conversation_id=${conversationId}`)); await expect(chat.userMessages().filter({hasText:token})).toHaveCount(1); await chat.assertRuntimeMetadata({ test_run_id: token }); await chat.assertKnowledgeSelected(knowledge, true); return "reopened the captured conversation ID and restored both Metadata and selected knowledge base after navigation"; },
      async () => { const changed = `${token}-changed`; await chat.setRuntimeMetadata({ test_run_id: changed }); const response = await chat.sendAndWait(`调用 require_metadata 并只回复返回值。`); await expect(response).toContainText(`METADATA_OK:${changed}`); return "a later turn consumed the changed metadata value"; },
    ],
    assertions: [
      async () => { await expect(page.getByRole("button", { name: /Metadata/ })).toBeVisible(); await expect(page.getByRole("button", { name: /知识库：/ })).toBeVisible(); return "Metadata and Knowledge Scope are real Composer controls"; },
      async () => { await chat.assertRuntimeMetadata({ test_run_id: `${token}-changed` }); return "conversation-scoped metadata persisted independently"; },
      async () => { await expect(page.getByText(/tool_params/i)).toHaveCount(0); return "Northbound tool_params was not invented as a Composer field"; },
    ],
  });
});
