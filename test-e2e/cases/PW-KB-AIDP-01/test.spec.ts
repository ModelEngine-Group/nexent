// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";
import { AidpKnowledgePage } from "../../infra/automation/d4/pages/aidp-knowledge.page";

/**
 * PW-KB-AIDP-01 — AIDP knowledge branch, end to end, mode-exclusive.
 *
 * The journey always runs against the controlled AIDP served by the
 * ext-knowledge mock (logical service knowledge-provider, seed
 * aidp-kb-product); there is no profile selection and no real AIDP
 * environment. The oracle is the stable seed text, its source document and
 * the selected KB id — a name filter match never impersonates retrieval
 * here.
 */

const ORACLE = {
  kbName: "AIDP Product Handbook",
  kbId: "aidp-kb-product",
  query: "AIDP Search 提供了什么能力？请引用原文回答。",
  // The model may translate around the sentence; this seed-only phrase is
  // preserved in both the debug recall and the released conversation.
  expectedText: "low-latency retrieval",
  expectedSource: "AIDP产品介绍.pdf",
};

interface JourneyOracle {
  kbName: string;
  kbId: string;
  query: string;
  expectedText: string;
  expectedSource: string;
}

const oracle: JourneyOracle = ORACLE;

journey("PW-KB-AIDP-01", async (context) => {
  const { page, expect } = context;
  const aidp = new AidpKnowledgePage(page);
  const agents = new AgentPage(page);
  const chat = new ChatPage(page);
  let agentDisplay = "";
  let bindingPayload = "";
  let bindingToolVerified = false;
  let debugAnswer = "";
  let conversationAnswer = "";

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        return `using the built-in mock oracle (ext-knowledge seed ${oracle.kbId})`;
      },
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        return "signed in as the configured tenant admin";
      },
      async () => {
        // The AIDP branch is proven by its own page markers; the Local-only
        // personal capacity bar must never render.
        await aidp.open();
        return "opened /knowledges on the AIDP branch with no Local quota controls";
      },
      async () => {
        agentDisplay = resolveReadyAsset("agents", "d4_llm_agent_display_name", "PW-KB-AIDP-01");
        return `resolved READY agent ${agentDisplay} for the binding journey`;
      },
    ],
    steps: [
      async () => {
        await aidp.selectKnowledgeBase(oracle.kbName);
        return `entered file management for ${oracle.kbName} and verified the selected resource`;
      },
      async () => {
        await agents.open();
        await agents.select(agentDisplay);
        const payload = await agents.bindKnowledgeBase(oracle.kbName, "aidp_search");
        bindingPayload = JSON.stringify(payload ?? {});
        // The tool-config autosave body carries the numeric tool id, not the
        // semantic name; the id is proven against the product's own tool list
        // so the saved params can only belong to aidp_search.
        const aidpToolId = await agents.toolIdBySemanticName("aidp_search");
        expect(Number(payload?.tool_id)).toBe(aidpToolId);
        expect(bindingPayload).toContain(oracle.kbId);
        bindingToolVerified = true;
        return `bound AIDP KB ${oracle.kbName} (${oracle.kbId}) through the real drawer and verified the aidp_search autosave`;
      },
      async () => {
        debugAnswer = await agents.debug(oracle.query, oracle.expectedText);
        return "Agent Debug completed a real AIDP tool recall stream";
      },
      async () => {
        expect(debugAnswer).toContain(oracle.expectedText);
        return `debug answer contained the oracle text fragment`;
      },
      async () => {
        // The answer renders citation chips (data-citation-marker); each
        // chip's accessible name carries the resolved source document, so a
        // chip naming the oracle document proves the recall came from the
        // selected KB rather than another source.
        const chips = page.locator("[data-testid='agent-debug-panel'] [data-citation-marker]");
        await expect(chips.first()).toBeVisible({ timeout: 30_000 });
        const labels = await chips.evaluateAll((nodes) =>
          nodes.map((node) => node.getAttribute("aria-label") || ""),
        );
        expect(labels.join("\n")).toContain(oracle.expectedSource);
        return `citation named the oracle source ${oracle.expectedSource}`;
      },
      async () => {
        await page.reload({ waitUntil: "domcontentloaded" });
        await agents.select(agentDisplay);
        await agents.openBasic();
        await agents.openSection("知识库管理");
        await expect(
          page.getByTestId("agent-selected-knowledge-base-name").filter({ hasText: oracle.kbName }),
        ).toBeVisible();
        return "full Agent-page refresh retained the AIDP knowledge binding";
      },
      async () => {
        // The knowledge binding lives on the agent draft; conversations run
        // the released version, so release the edit through the real 发布
        // action before starting a brand-new conversation.
        await agents.publishDraft("d4-aidp-journey", "AIDP knowledge binding journey");
        await chat.openAgent(agentDisplay);
        await chat.startMessage(oracle.query);
        await chat.waitForCompletion();
        const messages = await chat.assistantMessages().allInnerTexts();
        conversationAnswer = messages.join("\n");
        expect(conversationAnswer).toContain(oracle.expectedText);
        return "released the edited agent and a brand-new conversation recalled the same oracle through the agent-scoped AIDP knowledge";
      },
    ],
    assertions: [
      async () => {
        expect(bindingToolVerified).toBe(true);
        expect(bindingPayload).toContain(oracle.kbId);
        return `the autosaved aidp_search tool config carried the KB id ${oracle.kbId}`;
      },
      async () => {
        expect(debugAnswer).toContain(oracle.expectedText);
        return "Agent Debug produced a real AIDP retrieval answer with the oracle text";
      },
      async () => {
        expect(conversationAnswer).toContain(oracle.expectedText);
        return "the knowledge scope survived into a new conversation";
      },
      async () => {
        // The run is mock-backed by contract: the suite worker's attach to
        // the controlled AIDP mock (identity, lock, reset) must be recorded
        // for this case in runtime/ext-knowledge-attach.json.
        const resultDir = process.env.RESULT_DIR || "";
        const evidencePath = join(resultDir, "runtime", "ext-knowledge-attach.json");
        const evidence = JSON.parse(readFileSync(evidencePath, "utf-8")) as { attached?: boolean };
        expect(evidence.attached).toBe(true);
        return "the ext mock attach evidence was recorded for this case";
      },
    ],
  });
});
