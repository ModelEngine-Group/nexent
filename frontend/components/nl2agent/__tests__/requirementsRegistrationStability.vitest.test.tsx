import React from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MarkdownRenderer } from "@/components/common/markdownRenderer";
import {
  getNl2AgentSessionState,
  registerRequirementsSummary,
  type Nl2AgentSessionState,
} from "@/services/nl2agentService";
import { validateNl2AgentCards } from "../cardValidation";
import {
  EMPTY_NL2AGENT_ONLINE_CARD_IDENTITY_SIGNATURE,
  resolveActionableNl2AgentOnlineCardIdentitySignature,
} from "../finalMessageCardDelivery";
import {
  Nl2AgentWorkflowProvider,
  useNl2AgentWorkflow,
} from "../Nl2AgentWorkflowContext";

vi.mock("@/services/nl2agentService", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/nl2agentService")>()),
  getNl2AgentSessionState: vi.fn(),
  registerRequirementsSummary: vi.fn(),
}));

vi.mock("@/lib/utils", () => ({
  cn: (...values: Array<string | undefined>) =>
    values.filter(Boolean).join(" "),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

const requirementsContent = `\`\`\`nl2agent-requirements-summary
${JSON.stringify({
  agent_id: 202,
  goal: "Build presentations",
  audience_or_scenario: "Office users",
  primary_input: "DOCX files",
  expected_output: "PPT files",
  key_constraints: "Preserve source facts",
})}
\`\`\``;

const validatedCards = validateNl2AgentCards(requirementsContent, 202).cards;

const sessionState = {
  agent_id: 202,
  resource_review: {
    online_configuration_confirmed: false,
    online_recommendation_batches: {},
  },
} as unknown as Nl2AgentSessionState;

const onRegistered = vi.fn(async () => undefined);
const onContinue = vi.fn(async () => undefined);

const RequirementsMarkdownHarness = () => {
  const workflow = useNl2AgentWorkflow();
  const interactionSignature =
    resolveActionableNl2AgentOnlineCardIdentitySignature(
      validatedCards,
      {},
      workflow.sessionState,
      workflow.active
    );

  return (
    <MarkdownRenderer
      content={requirementsContent}
      nl2AgentDraftAgentId={202}
      nl2AgentCards={validatedCards}
      nl2AgentCardRenderMode="interactive"
      nl2AgentCardRegistrationEnabled
      nl2AgentInteractiveCardIdentitySignature={interactionSignature}
      onNl2AgentCardRegistered={onRegistered}
    />
  );
};

describe("requirements summary registration stability", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getNl2AgentSessionState).mockImplementation(async () =>
      structuredClone(sessionState)
    );
    vi.mocked(registerRequirementsSummary).mockResolvedValue({
      agent_id: 202,
      status: "awaiting_confirmation",
      fingerprint: "a".repeat(64),
      is_current: true,
      summary: {
        goal: "Build presentations",
        audience_or_scenario: "Office users",
        primary_input: "DOCX files",
        expected_output: "PPT files",
        key_constraints: "Preserve source facts",
      },
    });
  });

  afterEach(cleanup);

  it("registers once when equivalent session state objects refresh", async () => {
    expect(
      resolveActionableNl2AgentOnlineCardIdentitySignature(
        validatedCards,
        {},
        sessionState,
        true
      )
    ).toBe(EMPTY_NL2AGENT_ONLINE_CARD_IDENTITY_SIGNATURE);

    const view = render(
      <Nl2AgentWorkflowProvider
        enabled
        agentId={202}
        scopeKey="conversation:1:draft:202"
        onContinue={onContinue}
      >
        <RequirementsMarkdownHarness />
      </Nl2AgentWorkflowProvider>
    );

    await waitFor(() =>
      expect(registerRequirementsSummary).toHaveBeenCalledTimes(1)
    );
    await waitFor(() =>
      expect(getNl2AgentSessionState).toHaveBeenCalledTimes(2)
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(registerRequirementsSummary).toHaveBeenCalledTimes(1);
    expect(onRegistered).toHaveBeenCalledTimes(1);
    await act(async () => view.unmount());
  });
});
