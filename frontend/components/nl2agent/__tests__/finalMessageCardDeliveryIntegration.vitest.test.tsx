import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatMessageType } from "@/types/chat";
import { ChatStreamFinalMessage } from "../../../app/[locale]/chat/streaming/chatStreamFinalMessage";

const testState = vi.hoisted(() => ({
  markdownProps: undefined as
    | {
        nl2AgentCardRenderMode?: string;
        nl2AgentCardRegistrationEnabled?: boolean;
        nl2AgentInteractiveCardIdentitySignature?: string;
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
    sessionState: undefined as unknown,
  },
  validation: { cards: [], failure: undefined } as {
    cards: Array<{
      agentId: number;
      cardType: "web_mcp";
      cardKey: string;
      language: "nl2agent-web-mcps";
      payload: {
        agent_id: number;
        recommendation_batch_id: string;
        items: [];
      };
      requiresRegistration: true;
    }>;
    failure: undefined;
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
  validateNl2AgentCards: () => testState.validation,
}));

vi.mock("@/components/nl2agent/Nl2AgentWorkflowContext", () => ({
  useNl2AgentWorkflow: () => testState.workflow,
}));

vi.mock("@/services/nl2agentService", () => ({
  getNl2AgentSessionState: serviceMocks.getSessionState,
  isNl2AgentStaleCard: (error: unknown) =>
    Boolean(
      error &&
      typeof error === "object" &&
      "code" in error &&
      error.code === "030203"
    ),
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
    testState.workflow.sessionState = undefined;
    testState.validation.cards = [];
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

  it("passes only a latest unresolved historical online card through the read-only gate", () => {
    testState.workflow.active = true;
    testState.workflow.sessionState = {
      agent_id: 202,
      resource_review: {
        online_configuration_confirmed: false,
        online_recommendation_batches: {
          mcp_2: {
            resource_type: "mcp",
            status: "recommendations_ready",
          },
        },
      },
    };
    testState.validation.cards = [
      {
        agentId: 202,
        cardType: "web_mcp",
        cardKey: "mcp_2",
        language: "nl2agent-web-mcps",
        payload: {
          agent_id: 202,
          recommendation_batch_id: "mcp_2",
          items: [],
        },
        requiresRegistration: true,
      },
    ];
    const message: ChatMessageType = {
      id: "assistant-73",
      message_id: 73,
      role: "assistant",
      content: "restored MCP card",
      isComplete: true,
      timestamp: new Date(0),
    };

    render(
      <ChatStreamFinalMessage
        message={message}
        nl2AgentDraftAgentId={202}
        isLatestMessage={false}
        isStreaming={false}
        latestNl2AgentOnlineCardKeys={{ web_mcp: "mcp_2" }}
      />
    );

    expect(testState.markdownProps?.nl2AgentCardRenderMode).toBe("readonly");
    expect(
      testState.markdownProps?.nl2AgentInteractiveCardIdentitySignature
    ).toBe('["web_mcp:mcp_2"]');
    expect(testState.markdownProps?.nl2AgentCardRegistrationEnabled).toBe(
      false
    );
  });

  it("silently retires a stale delivery receipt without offering retry", async () => {
    testState.workflow.active = true;
    testState.workflow.claimCardDelivery.mockReturnValue(true);
    testState.validation.cards = [
      {
        agentId: 202,
        cardType: "final_review" as never,
        language: "nl2agent-finalize" as never,
        payload: { agent_id: 202 } as never,
        requiresRegistration: false,
      } as never,
    ];
    serviceMocks.reportCardDelivery.mockRejectedValueOnce({
      status: 409,
      code: "030203",
      message: "The NL2AGENT card delivery receipt is stale.",
    });
    const message: ChatMessageType = {
      id: "assistant-74",
      message_id: 74,
      role: "assistant",
      content: "stale final card",
      isComplete: true,
      timestamp: new Date(0),
    };

    render(
      <ChatStreamFinalMessage
        message={message}
        nl2AgentDraftAgentId={202}
        isLatestMessage
        isStreaming={false}
        enableNl2AgentCardRecovery
      />
    );

    await waitFor(() =>
      expect(testState.workflow.completeCardDelivery).toHaveBeenCalled()
    );
    expect(screen.queryByText(/stale/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Retry receipt/i })
    ).not.toBeInTheDocument();
  });
});
