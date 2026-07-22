import { describe, expect, it } from "vitest";

import type { ChatMessageType } from "@/types/chat";
import type { Nl2AgentSessionState } from "@/services/nl2agentService";
import { validateNl2AgentCards } from "../cardValidation";
import {
  isNl2AgentCardExplicitlyInteractive,
  parseNl2AgentOnlineCardIdentitySignature,
  resolveActionableNl2AgentOnlineCardIdentitySignature,
  resolveLatestNl2AgentOnlineCardKeys,
  resolveNl2AgentCardPresentation,
} from "../finalMessageCardDelivery";

const onlineCardMessage = (
  cardType: "mcp" | "skill",
  batchId: string,
  options: { complete?: boolean; valid?: boolean } = {}
): ChatMessageType => ({
  id: `${cardType}-${batchId}`,
  role: "assistant",
  content:
    options.valid === false
      ? `\`\`\`nl2agent-web-${cardType}s\n{invalid}\n\`\`\``
      : `\`\`\`nl2agent-web-${cardType}s\n${JSON.stringify({
          agent_id: 202,
          recommendation_batch_id: batchId,
          items: [],
        })}\n\`\`\``,
  isComplete: options.complete ?? true,
  timestamp: new Date(0),
});

const textMessage = (id: string): ChatMessageType => ({
  id,
  role: "assistant",
  content: "Continue configuring resources.",
  isComplete: true,
  timestamp: new Date(0),
});

describe("NL2AGENT final-message card delivery presentation", () => {
  it("preserves card rendering while delaying registration until delivery is safe", () => {
    expect(
      resolveNl2AgentCardPresentation({
        isComplete: true,
        isStreaming: true,
        hasMessageId: true,
        hasValidationFailure: false,
        isLatestMessage: true,
        readOnly: false,
      })
    ).toEqual({ renderMode: "interactive", registrationEnabled: false });

    expect(
      resolveNl2AgentCardPresentation({
        isComplete: true,
        isStreaming: false,
        hasMessageId: false,
        hasValidationFailure: false,
        isLatestMessage: true,
        readOnly: false,
      })
    ).toEqual({ renderMode: "interactive", registrationEnabled: false });
  });

  it("enables registration only for a ready latest interactive message", () => {
    const readyMessage = {
      isComplete: true,
      isStreaming: false,
      hasMessageId: true,
      hasValidationFailure: false,
      isLatestMessage: true,
      readOnly: false,
    };
    expect(resolveNl2AgentCardPresentation(readyMessage)).toEqual({
      renderMode: "interactive",
      registrationEnabled: true,
    });
    expect(
      resolveNl2AgentCardPresentation({ ...readyMessage, readOnly: true })
    ).toEqual({ renderMode: "readonly", registrationEnabled: false });
    expect(
      resolveNl2AgentCardPresentation({
        isComplete: true,
        isStreaming: true,
        hasMessageId: true,
        hasValidationFailure: false,
        isLatestMessage: false,
        readOnly: false,
      })
    ).toEqual({ renderMode: "readonly", registrationEnabled: false });
  });

  it("keeps invalid cards as placeholders", () => {
    expect(
      resolveNl2AgentCardPresentation({
        isComplete: true,
        isStreaming: false,
        hasMessageId: true,
        hasValidationFailure: true,
        isLatestMessage: true,
        readOnly: false,
      })
    ).toEqual({ renderMode: "placeholder", registrationEnabled: false });
  });

  it("tracks the latest valid completed card independently by online resource type", () => {
    const latest = resolveLatestNl2AgentOnlineCardKeys(
      [
        onlineCardMessage("mcp", "mcp_1"),
        textMessage("newer-text"),
        onlineCardMessage("skill", "skill_1"),
        onlineCardMessage("mcp", "mcp_incomplete", { complete: false }),
        onlineCardMessage("mcp", "mcp_invalid", { valid: false }),
        onlineCardMessage("mcp", "mcp_2"),
      ],
      202
    );

    expect(latest).toEqual({ web_mcp: "mcp_2", web_skill: "skill_1" });
  });

  it("makes only the latest matching ready batch explicitly interactive", () => {
    const oldCard = validateNl2AgentCards(
      onlineCardMessage("mcp", "mcp_1").content,
      202
    ).cards[0];
    const latestCard = validateNl2AgentCards(
      onlineCardMessage("mcp", "mcp_2").content,
      202
    ).cards[0];
    const skillCard = validateNl2AgentCards(
      onlineCardMessage("skill", "skill_1").content,
      202
    ).cards[0];
    const sessionState = {
      agent_id: 202,
      resource_review: {
        online_configuration_confirmed: false,
        recommendations: {
          mcp_1: {
            resource_type: "mcp",
            status: "presented",
          },
          mcp_2: {
            resource_type: "mcp",
            status: "presented",
          },
          skill_1: {
            resource_type: "skill",
            status: "presented",
          },
        },
      },
    } as unknown as Nl2AgentSessionState;

    const signature = resolveActionableNl2AgentOnlineCardIdentitySignature(
      [oldCard, latestCard, skillCard],
      { web_mcp: "mcp_2", web_skill: "skill_1" },
      sessionState,
      true
    );
    const interactive = parseNl2AgentOnlineCardIdentitySignature(signature);

    expect(isNl2AgentCardExplicitlyInteractive(oldCard, interactive)).toBe(
      false
    );
    expect(isNl2AgentCardExplicitlyInteractive(latestCard, interactive)).toBe(
      true
    );
    expect(isNl2AgentCardExplicitlyInteractive(skillCard, interactive)).toBe(
      true
    );
  });

  it("keeps completed and read-only online cards locked", () => {
    const card = validateNl2AgentCards(
      onlineCardMessage("skill", "skill_1").content,
      202
    ).cards[0];
    const sessionState = {
      agent_id: 202,
      resource_review: {
        online_configuration_confirmed: true,
        recommendations: {
          skill_1: { resource_type: "skill", status: "completed" },
        },
      },
    } as unknown as Nl2AgentSessionState;

    expect(
      parseNl2AgentOnlineCardIdentitySignature(
        resolveActionableNl2AgentOnlineCardIdentitySignature(
          [card],
          { web_skill: "skill_1" },
          sessionState,
          true
        )
      ).size
    ).toBe(0);
    expect(
      parseNl2AgentOnlineCardIdentitySignature(
        resolveActionableNl2AgentOnlineCardIdentitySignature(
          [card],
          { web_skill: "skill_1" },
          {
            ...sessionState,
            resource_review: {
              ...sessionState.resource_review,
              online_configuration_confirmed: false,
            },
          },
          false
        )
      ).size
    ).toBe(0);
  });

  it("returns the same primitive signature for equivalent session states", () => {
    const card = validateNl2AgentCards(
      onlineCardMessage("mcp", "mcp_1").content,
      202
    ).cards[0];
    const state = {
      agent_id: 202,
      resource_review: {
        online_configuration_confirmed: false,
        recommendations: {
          mcp_1: {
            resource_type: "mcp",
            status: "presented",
          },
        },
      },
    } as unknown as Nl2AgentSessionState;

    const first = resolveActionableNl2AgentOnlineCardIdentitySignature(
      [card],
      { web_mcp: "mcp_1" },
      state,
      true
    );
    const second = resolveActionableNl2AgentOnlineCardIdentitySignature(
      [card],
      { web_mcp: "mcp_1" },
      structuredClone(state),
      true
    );

    expect(first).toBe('["web_mcp:mcp_1"]');
    expect(second).toBe(first);
  });
});
