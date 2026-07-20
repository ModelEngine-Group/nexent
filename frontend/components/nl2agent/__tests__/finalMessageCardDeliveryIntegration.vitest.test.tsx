import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatMessageType } from "@/types/chat";
import { ChatStreamFinalMessage } from "../../../app/[locale]/chat/streaming/chatStreamFinalMessage";

const testState = vi.hoisted(() => ({
  markdownProps: undefined as
    | {
        nl2AgentCardRenderMode?: string;
        nl2AgentCardRegistrationEnabled?: boolean;
        onNl2AgentCardRegistered?: (receipt: {
          cardType: "local_resources";
          cardKey?: string;
        }) => Promise<void>;
      }
    | undefined,
  workflow: {
    active: false,
    claimCardDelivery: vi.fn(),
    completeCardDelivery: vi.fn(),
    failCardDelivery: vi.fn(),
    notifyStateChanged: vi.fn(),
    continueWithText: vi.fn(),
  },
}));

const serviceMocks = vi.hoisted(() => ({
  getSessionState: vi.fn(async () => ({ expected_card_types: [] })),
  reportCardDelivery: vi.fn(async () => ({})),
}));

vi.mock("@/components/common/markdownRenderer", () => ({
  MarkdownRenderer: (props: typeof testState.markdownProps) => {
    testState.markdownProps = props;
    return null;
  },
}));

vi.mock("@/components/nl2agent/cardValidation", () => ({
  validateNl2AgentCards: () => ({ cards: [], failure: undefined }),
}));

vi.mock("@/components/nl2agent/Nl2AgentWorkflowContext", () => ({
  useNl2AgentWorkflow: () => testState.workflow,
}));

vi.mock("@/services/nl2agentService", () => ({
  getNl2AgentSessionState: serviceMocks.getSessionState,
  reportNl2AgentCardDelivery: serviceMocks.reportCardDelivery,
}));

vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({ modelConfig: undefined }),
}));

vi.mock("@/lib/utils", () => ({
  cn: (...values: Array<string | undefined>) =>
    values.filter(Boolean).join(" "),
}));

vi.mock("@/services/conversationService", () => ({
  conversationService: {
    tts: {
      createTTSService: () => ({
        cleanup: vi.fn(),
        playAudio: vi.fn(),
        stopAudio: vi.fn(),
      }),
    },
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("ChatStreamFinalMessage NL2AGENT delivery gate", () => {
  afterEach(() => {
    testState.markdownProps = undefined;
    testState.workflow.active = false;
    vi.clearAllMocks();
  });

  it("rerenders the same message when streaming eligibility changes", () => {
    const message: ChatMessageType = {
      id: "assistant-71",
      message_id: 71,
      role: "assistant",
      content: "requirements card",
      isComplete: true,
      timestamp: new Date(0),
    };
    const { rerender } = render(
      <ChatStreamFinalMessage
        message={message}
        nl2AgentDraftAgentId={202}
        isLatestMessage
        isStreaming
        enableNl2AgentCardRecovery
      />
    );

    expect(testState.markdownProps).toMatchObject({
      nl2AgentCardRenderMode: "interactive",
      nl2AgentCardRegistrationEnabled: false,
    });

    rerender(
      <ChatStreamFinalMessage
        message={message}
        nl2AgentDraftAgentId={202}
        isLatestMessage
        isStreaming={false}
        enableNl2AgentCardRecovery
      />
    );

    expect(testState.markdownProps).toMatchObject({
      nl2AgentCardRenderMode: "interactive",
      nl2AgentCardRegistrationEnabled: true,
    });
  });

  it("enables restored registration without repeating the delivery receipt", async () => {
    testState.workflow.active = true;
    const message: ChatMessageType = {
      id: "assistant-72",
      message_id: 72,
      role: "assistant",
      content: "restored requirements card",
      isComplete: true,
      timestamp: new Date(0),
    };

    render(
      <ChatStreamFinalMessage
        message={message}
        nl2AgentDraftAgentId={202}
        isLatestMessage
        isStreaming={false}
      />
    );

    expect(testState.markdownProps).toMatchObject({
      nl2AgentCardRenderMode: "interactive",
      nl2AgentCardRegistrationEnabled: true,
    });
    await act(async () => {
      await testState.markdownProps?.onNl2AgentCardRegistered?.({
        cardType: "local_resources",
        cardKey: "local_1",
      });
    });
    expect(serviceMocks.reportCardDelivery).not.toHaveBeenCalled();
  });
});
