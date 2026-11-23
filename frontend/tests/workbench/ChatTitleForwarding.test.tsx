import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Chat } from "@/app/newchat/assistant-ui/chat";

vi.mock("@/app/newchat/assistant-ui/thread", () => ({
  Thread: ({
    generatedTitle,
    conversationId,
  }: {
    generatedTitle?: string;
    conversationId?: number;
  }) => (
    <div
      data-testid="thread"
      data-title={generatedTitle}
      data-conversation-id={conversationId}
    />
  ),
}));

vi.mock("@/app/newchat/assistant-ui/agent-landing", () => ({
  AgentLandingPage: () => <div>Agent landing</div>,
}));

it("forwards the generated title and conversation ID in generic Workbench mode", () => {
  render(
    <Chat
      selectedAgent={null}
      landingContent={<div>Workbench</div>}
      generatedTitle="构建智能客服应用"
      conversationId={42}
    />
  );
  expect(screen.getByTestId("thread")).toHaveAttribute(
    "data-title",
    "构建智能客服应用"
  );
  expect(screen.getByTestId("thread")).toHaveAttribute(
    "data-conversation-id",
    "42"
  );
});
