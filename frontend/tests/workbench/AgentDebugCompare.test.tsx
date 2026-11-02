// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  useAui,
  useAuiState,
} from "@assistant-ui/react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ComponentProps, ReactNode } from "react";
import { AgentDebugComparePanel } from "@/app/agents/[agentId]/components/debug/compare-panel";
import { DebugConversation } from "@/app/agents/[agentId]/components/debug/debug-conversation";
import type { Thread } from "@/app/newchat/assistant-ui/thread";
import type { Agent } from "@/types/agentConfig";

const fixture = vi.hoisted(() => ({
  draft: {
    name: "Draft agent",
    greeting_message: "Debug greeting",
    model_ids: [1, 2],
    example_questions: ["Example question"],
  },
  models: [
    { id: 1, name: "model-one", displayName: "Model One" },
    { id: 2, name: "model-two", displayName: "Model Two" },
    { id: 3, name: "model-three", displayName: "Model Three" },
  ],
}));

vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/services/api", () => ({
  API_ENDPOINTS: { agent: { icon: (id: number) => `/fixture/icon/${id}` } },
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: () => ({ editedAgent: fixture.draft }),
}));
vi.mock("@/hooks/model/useModelList", () => ({
  useModelList: () => ({ availableLlmModels: fixture.models }),
}));
vi.mock("@/hooks/useConfig", () => ({ useConfig: () => ({}) }));
vi.mock("@/app/newchat/adapter/attachment-adapter", () => ({
  compositeAttachmentAdapter: {},
}));
vi.mock("@/app/newchat/adapter/server-dictation-adapter", () => ({
  ServerDictationAdapter: class {},
}));
vi.mock("@/app/newchat/adapter/remote-chat-model-adapter", () => ({
  remoteChatModelAdapter: { run: vi.fn() },
}));
vi.mock("@/app/newchat/assistant-ui/composer-tools", () => ({
  ComposerAttachment: () => null,
  ComposerDictation: () => null,
}));
vi.mock("@/app/newchat/assistant-ui/thread", () => ({
  Thread: (props: ComponentProps<typeof Thread>) => (
    <section
      data-testid="thread"
      data-debug-layout={String(props.debugLayout)}
      data-composer={String(props.showComposer)}
      data-model-selector={String(props.showModelSelector)}
    >
      {props.welcomeContent ?? "Default chat welcome"}
    </section>
  ),
}));
vi.mock("@/app/newchat/assistant-ui/composer", () => ({
  Composer: function ComposerProbe({
    showModelSelector,
    children,
  }: {
    showModelSelector: boolean;
    children: ReactNode;
  }) {
    const aui = useAui();
    const text = useAuiState((state) => state.thread.composer.text);
    return (
      <div
        data-testid="shared-composer"
        data-model-selector={String(showModelSelector)}
      >
        <input
          aria-label="Shared draft"
          value={text}
          onChange={(event) => aui.composer().setText(event.target.value)}
        />
        {children}
      </div>
    );
  },
}));

beforeEach(() => vi.clearAllMocks());

it("uses the shared debug welcome/layout in both columns with one model-free composer", () => {
  render(<AgentDebugComparePanel agentId={42} />);
  const threads = screen.getAllByTestId("thread");
  expect(threads).toHaveLength(2);
  for (const thread of threads) {
    expect(thread).toHaveAttribute("data-debug-layout", "true");
    expect(thread).toHaveAttribute("data-composer", "false");
    expect(thread).toHaveAttribute("data-model-selector", "false");
    expect(
      within(thread).getByTestId("agent-debug-welcome")
    ).toBeInTheDocument();
    expect(within(thread).getByText("Debug greeting")).toBeInTheDocument();
  }
  expect(screen.getAllByTestId("shared-composer")).toHaveLength(1);
  expect(screen.getByTestId("shared-composer")).toHaveAttribute(
    "data-model-selector",
    "false"
  );
  for (const question of screen.getAllByRole("button", {
    name: "Example question",
  })) {
    fireEvent.change(screen.getByLabelText("Shared draft"), {
      target: { value: "" },
    });
    fireEvent.click(question);
    expect(screen.getByLabelText("Shared draft")).toHaveValue(
      "Example question"
    );
  }
});

it("reuses composer picker primitives and excludes the other column when switching models", async () => {
  render(<AgentDebugComparePanel agentId={42} />);
  const pickers = screen.getAllByRole("combobox");
  const selectorRow = screen.getByTestId("compare-model-selectors");
  const results = screen.getByTestId("compare-results");
  expect(within(selectorRow).getAllByRole("combobox")).toEqual(pickers);
  expect(within(results).queryByRole("combobox")).not.toBeInTheDocument();
  expect(
    results.compareDocumentPosition(selectorRow) &
      Node.DOCUMENT_POSITION_FOLLOWING
  ).toBeTruthy();
  expect(
    selectorRow.compareDocumentPosition(screen.getByTestId("shared-composer")) &
      Node.DOCUMENT_POSITION_FOLLOWING
  ).toBeTruthy();
  expect(pickers[0]).toHaveTextContent("Model One");
  expect(pickers[1]).toHaveTextContent("Model Two");
  expect(pickers[0]).toHaveAttribute("data-slot", "model-selector-trigger");
  expect(pickers[0]).toHaveClass("hover:bg-accent", "h-8");
  fireEvent.click(pickers[0]);
  expect(
    await screen.findByRole("option", { name: "Model Three" })
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("option", { name: "Model Two" })
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("option", { name: "Model Three" }));
  expect(pickers[0]).toHaveTextContent("Model Three");
  expect(pickers[1]).toHaveTextContent("Model Two");
  fireEvent.click(pickers[1]);
  expect(
    await screen.findByRole("option", { name: "Model One" })
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("option", { name: "Model Three" })
  ).not.toBeInTheDocument();
});

it("keeps the ordinary conversation composer and model picker enabled", () => {
  function OrdinaryConversation() {
    const runtime = useLocalRuntime({ run: vi.fn() });
    return (
      <AssistantRuntimeProvider runtime={runtime}>
        <DebugConversation
          agent={{ id: "42", ...fixture.draft } as unknown as Agent}
          chatMode="execution"
          onChatModeChange={vi.fn()}
        />
      </AssistantRuntimeProvider>
    );
  }
  render(<OrdinaryConversation />);
  const thread = screen.getByTestId("thread");
  expect(thread).toHaveAttribute("data-debug-layout", "true");
  expect(thread).toHaveAttribute("data-composer", "true");
  expect(thread).toHaveAttribute("data-model-selector", "true");
  expect(within(thread).getByTestId("agent-debug-welcome")).toBeInTheDocument();
});

it("handles the missing draft boundary without mounting a composer", () => {
  render(<AgentDebugComparePanel />);
  expect(screen.queryByTestId("shared-composer")).not.toBeInTheDocument();
  expect(
    screen.getByText("systemPrompt.nonEditing.subtitle")
  ).toBeInTheDocument();
});
