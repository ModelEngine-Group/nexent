// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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
 * The profile is selected by the machine-local aidp-journey configuration
 * through the suite worker (never guessed in the script):
 *  - mock: the real product runs against the controlled AIDP (ext-knowledge
 *    instance, seed aidp-kb-product). The oracle is the stable seed text,
 *    its source document and the selected KB id — a name filter match never
 *    impersonates retrieval here.
 *  - real_smoke: the real product runs against an explicitly configured
 *    real AIDP; the oracle comes from the same configuration. Mock results
 *    never count as real_smoke.
 */

const MOCK_ORACLE = {
  kbName: "AIDP Product Handbook",
  kbId: "aidp-kb-product",
  query: "AIDP Search 提供了什么能力？请引用原文回答。",
  expectedText: "AIDP Search provides low-latency retrieval",
  expectedSource: "AIDP产品介绍.pdf",
};

interface JourneyOracle {
  profile: string;
  kbName: string;
  kbId: string;
  docName?: string;
  query: string;
  expectedText: string;
  expectedSource: string;
}

function oracleForProfile(): JourneyOracle {
  const profile = (process.env.NEXENT_TEST_SELECTED_PROFILE || "").trim();
  if (profile === "mock") {
    return { profile, ...MOCK_ORACLE };
  }
  if (profile === "real_smoke") {
    const required = [
      "NEXENT_TEST_AIDP_REAL_KB_ID",
      "NEXENT_TEST_AIDP_REAL_KB_NAME",
      "NEXENT_TEST_AIDP_REAL_QUERY",
      "NEXENT_TEST_AIDP_REAL_EXPECTED_TEXT",
      "NEXENT_TEST_AIDP_REAL_EXPECTED_SOURCE",
    ] as const;
    const missing = required.filter((name) => !(process.env[name] || "").trim());
    if (missing.length) {
      throw new Error(
        `real_smoke profile is not configured: missing ${missing.join(", ")}; ` +
          "fill config/aidp-journey.yaml or stay on the mock profile",
      );
    }
    return {
      profile,
      kbId: process.env.NEXENT_TEST_AIDP_REAL_KB_ID!.trim(),
      kbName: process.env.NEXENT_TEST_AIDP_REAL_KB_NAME!.trim(),
      docName: (process.env.NEXENT_TEST_AIDP_REAL_DOC_NAME || "").trim() || undefined,
      query: process.env.NEXENT_TEST_AIDP_REAL_QUERY!.trim(),
      expectedText: process.env.NEXENT_TEST_AIDP_REAL_EXPECTED_TEXT!.trim(),
      expectedSource: process.env.NEXENT_TEST_AIDP_REAL_EXPECTED_SOURCE!.trim(),
    };
  }
  throw new Error(
    "NEXENT_TEST_SELECTED_PROFILE is required: run this case through the suite " +
      "worker so the aidp-journey profile selection resolves mock or real_smoke",
  );
}

journey("PW-KB-AIDP-01", async (context) => {
  const { page, expect } = context;
  const aidp = new AidpKnowledgePage(page);
  const agents = new AgentPage(page);
  const chat = new ChatPage(page);
  let oracle: JourneyOracle | null = null;
  let agentDisplay = "";
  let bindingPayload = "";
  let bindingToolVerified = false;
  let debugAnswer = "";
  let conversationAnswer = "";

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        oracle = oracleForProfile();
        return `profile ${oracle.profile} resolved from the aidp-journey configuration`;
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
        await aidp.selectKnowledgeBase(oracle!.kbName);
        if (oracle!.docName) {
          await aidp.expectDocument(oracle!.docName);
          return `entered file management for ${oracle!.kbName} and verified document ${oracle!.docName}`;
        }
        return `entered file management for ${oracle!.kbName} and verified the selected resource`;
      },
      async () => {
        await agents.open();
        await agents.select(agentDisplay);
        const payload = await agents.bindKnowledgeBase(oracle!.kbName, "aidp_search");
        bindingPayload = JSON.stringify(payload ?? {});
        // The tool-config autosave body carries the numeric tool id, not the
        // semantic name; the id is proven against the product's own tool list
        // so the saved params can only belong to aidp_search.
        const aidpToolId = await agents.toolIdBySemanticName("aidp_search");
        expect(Number(payload?.tool_id)).toBe(aidpToolId);
        expect(bindingPayload).toContain(oracle!.kbId);
        bindingToolVerified = true;
        return `bound AIDP KB ${oracle!.kbName} (${oracle!.kbId}) through the real drawer and verified the aidp_search autosave`;
      },
      async () => {
        debugAnswer = await agents.debug(oracle!.query, oracle!.expectedText);
        return "Agent Debug completed a real AIDP tool recall stream";
      },
      async () => {
        expect(debugAnswer).toContain(oracle!.expectedText);
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
        expect(labels.join("\n")).toContain(oracle!.expectedSource);
        return `citation named the oracle source ${oracle!.expectedSource}`;
      },
      async () => {
        await page.reload({ waitUntil: "domcontentloaded" });
        await agents.select(agentDisplay);
        await agents.openBasic();
        await agents.openSection("知识库管理");
        await expect(
          page.getByTestId("agent-selected-knowledge-base-name").filter({ hasText: oracle!.kbName }),
        ).toBeVisible();
        return "full Agent-page refresh retained the AIDP knowledge binding";
      },
      async () => {
        // The knowledge binding lives on the agent draft; conversations run
        // the released version, so release the edit through the real 发布
        // action before starting a brand-new conversation.
        await agents.publishDraft("d4-aidp-journey", "AIDP knowledge binding journey");
        await chat.openAgent(agentDisplay);
        await chat.startMessage(oracle!.query);
        await chat.waitForCompletion();
        const messages = await chat.assistantMessages().allInnerTexts();
        conversationAnswer = messages.join("\n");
        expect(conversationAnswer).toContain(oracle!.expectedText);
        return "released the edited agent and a brand-new conversation recalled the same oracle through the agent-scoped AIDP knowledge";
      },
    ],
    assertions: [
      async () => {
        expect(bindingToolVerified).toBe(true);
        expect(bindingPayload).toContain(oracle!.kbId);
        return `the autosaved aidp_search tool config carried the KB id ${oracle!.kbId}`;
      },
      async () => {
        expect(debugAnswer).toContain(oracle!.expectedText);
        return "Agent Debug produced a real AIDP retrieval answer with the oracle text";
      },
      async () => {
        expect(conversationAnswer).toContain(oracle!.expectedText);
        return "the knowledge scope survived into a new conversation";
      },
      async () => {
        expect(oracle!.profile).toMatch(/^(mock|real_smoke)$/);
        return `journey executed under the explicitly selected ${oracle!.profile} profile`;
      },
    ],
  });
});
