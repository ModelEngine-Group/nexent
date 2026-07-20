import { describe, expect, it } from "vitest";

import { resolveNl2AgentCardPresentation } from "../finalMessageCardDelivery";

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
    ).toEqual({ renderMode: "interactive", registrationEnabled: false });
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
});
