import { describe, expect, it } from "vitest";

import { resolveNl2AgentSendRequest } from "@/lib/chat/nl2agentSendRequest";

const activeScope = {
  activeConversationId: 10,
  activeDraftAgentId: 202,
  expectedConversationId: 10,
  expectedDraftAgentId: 202,
};

describe("resolveNl2AgentSendRequest", () => {
  it("sends CARD_RETRY as hidden automatic continuation even with empty input", () => {
    const result = resolveNl2AgentSendRequest({
      autoContinueText:
        "[[NL2AGENT_CARD_RETRY]]\nRegenerate the invalid card only.",
      input: "",
      attachments: [{ name: "user-draft.txt" }],
      ...activeScope,
    });

    expect(result).toEqual({
      isAutoContinue: true,
      outgoingText:
        "[[NL2AGENT_CARD_RETRY]]\nRegenerate the invalid card only.",
      outgoingAttachments: [],
    });
  });

  it("does not replace CARD_RETRY with a pending user draft", () => {
    const result = resolveNl2AgentSendRequest({
      autoContinueText: "[[NL2AGENT_CARD_RETRY]]\nRetry.",
      input: "Do not send this user draft",
      attachments: [],
      ...activeScope,
    });

    expect(result.outgoingText).toBe("[[NL2AGENT_CARD_RETRY]]\nRetry.");
  });

  it("applies conversation and draft anti-crosstalk checks to CARD_RETRY", () => {
    expect(() =>
      resolveNl2AgentSendRequest({
        autoContinueText: "[[NL2AGENT_CARD_RETRY]]\nRetry.",
        input: "",
        attachments: [],
        ...activeScope,
        activeConversationId: 11,
      })
    ).toThrow("conversation changed");
  });

  it("preserves ordinary user sends", () => {
    const attachments = [{ name: "document.txt" }];
    expect(
      resolveNl2AgentSendRequest({
        input: "  User message  ",
        attachments,
        ...activeScope,
      })
    ).toEqual({
      isAutoContinue: false,
      outgoingText: "User message",
      outgoingAttachments: attachments,
    });
  });
});
