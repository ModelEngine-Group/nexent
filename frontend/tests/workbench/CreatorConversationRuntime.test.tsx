// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import { AssistantRuntimeProvider, useLocalRuntime } from "@assistant-ui/react";
import { ReadableStream } from "node:stream/web";
import { Nl2AgentFlowProvider } from "@/contexts/nl2AgentFlow";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThreadMessages } from "@/app/newchat/assistant-ui/thread";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";

const service = vi.hoisted(() => ({ runAgent: vi.fn() }));
afterEach(() => vi.unstubAllGlobals());
vi.mock("@/services/conversationService", () => ({
  conversationService: service,
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));
vi.mock("@/app/newchat/ui/markdown-text", () => ({ MarkdownText: () => null }));
vi.mock("react-shiki", () => ({
  default: () => null,
  ShikiHighlighter: () => null,
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { id: "user", tenantId: "tenant" } }),
}));

const runConfig = {
  custom: { runtimeMode: "nl2agent", agentId: 42, threadId: "91" },
};
const card = (title: string, option: string) => ({
  subtype: "requirement_clarification",
  agent_id: 42,
  questions: [
    {
      question_id: "goal",
      question_type: "single_choice",
      title,
      required: true,
      options: [{ option_id: "yes", label: option }],
      allow_other: false,
      other_input_expanded: false,
    },
  ],
});
function reply(payload: unknown) {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(
        new TextEncoder().encode(
          `data: ${JSON.stringify({ type: "nl2a", content: JSON.stringify(payload) })}\n\n`
        )
      );
      controller.close();
    },
  }).getReader();
}
function Scenario() {
  const runtime = useLocalRuntime(remoteChatModelAdapter);
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <Nl2AgentFlowProvider>
        <TooltipProvider>
          <button
            onClick={() => {
              runtime.thread.composer.setRunConfig(runConfig);
              runtime.thread.append({
                role: "user",
                content: [{ type: "text", text: "Create an Agent" }],
                runConfig,
              });
            }}
          >
            Start
          </button>
          <ThreadMessages
            agent={
              {
                id: "42",
                name: "Creator",
                display_name: "Creator",
              } as unknown as ComponentProps<typeof ThreadMessages>["agent"]
            }
          />
        </TooltipProvider>
      </Nl2AgentFlowProvider>
    </AssistantRuntimeProvider>
  );
}
it("renders a second metadata-only clarification through the actual runtime and message renderer", async () => {
  // Intranet HTTP pages may not expose crypto.randomUUID.
  vi.stubGlobal("crypto", {});
  service.runAgent
    .mockResolvedValueOnce(reply(card("Round one", "First choice")))
    .mockResolvedValueOnce(reply(card("Round two", "Second choice")));
  render(<Scenario />);
  fireEvent.click(screen.getByRole("button", { name: "Start" }));
  const first = await screen.findByRole("radio", { name: "First choice" });
  expect(first).toBeEnabled();
  fireEvent.click(first);
  fireEvent.click(screen.getByRole("button", { name: "Submit" }));
  await waitFor(() => expect(service.runAgent).toHaveBeenCalledTimes(2));
  const second = await screen.findByRole("radio", { name: "Second choice" });
  expect(second).toBeEnabled();
  expect(first).toBeDisabled();
  const requestIds = service.runAgent.mock.calls.map(
    ([request]) => request.request_id
  );
  expect(
    requestIds.every((id) => typeof id === "string" && id.length > 0)
  ).toBe(true);
  expect(new Set(requestIds).size).toBe(2);
});
