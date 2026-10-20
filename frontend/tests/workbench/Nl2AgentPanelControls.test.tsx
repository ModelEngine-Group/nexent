// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { createRef, type ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ChatModelAdapter } from "@assistant-ui/react";
import type { ThreadProps } from "@/app/newchat/assistant-ui/thread";
import {
  Nl2AgentChatPanel,
  type Nl2AgentChatPanelHandle,
} from "@/app/newchat/assistant-ui/nl2agent-chat-panel";

const fixture = vi.hoisted(() => {
  const state = { isRunning: false };
  return {
    state,
    controls: {
      selectedModelId: "3",
      onModelChange: vi.fn(),
      deepThinking: true,
      onDeepThinkingChange: vi.fn(),
      thinkingEffort: "xhigh",
      onThinkingEffortChange: vi.fn(),
      reasoningBudgetTokens: 2048,
      onReasoningBudgetTokensChange: vi.fn(),
      modelParameterSettings: {
        value: { temperature: 0.7, top_p: 0.9 },
      },
      snapshot: {
        model_id: 3,
        generation_config: {
          deep_thinking: true,
          thinking_effort: "xhigh",
          temperature: 0.7,
          top_p: 0.9,
        },
      },
      canCreate: true,
      canSend: true,
    },
    runtime: {
      thread: {
        subscribe: () => () => {},
        getState: () => state,
        cancelRun: vi.fn(),
        append: vi.fn(),
        composer: { setText: vi.fn() },
      },
    },
    thread: vi.fn(),
    remoteRun: vi.fn(async function* () {
      yield { content: [] };
    }),
    adapter: undefined as ChatModelAdapter | undefined,
  };
});

vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@assistant-ui/react", () => ({
  AssistantRuntimeProvider: ({ children }: { children: ReactNode }) => children,
  useLocalRuntime: (adapter: ChatModelAdapter) => {
    fixture.adapter = adapter;
    return fixture.runtime;
  },
}));
vi.mock("@/components/ui/tooltip", () => ({
  TooltipProvider: ({ children }: { children: ReactNode }) => children,
}));
vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({ modelConfig: { stt: {} } }),
}));
vi.mock("@/features/model-controls/useCreatorModelControls", () => ({
  useCreatorModelControls: () => fixture.controls,
}));
vi.mock("@/app/newchat/adapter/attachment-adapter", () => ({
  compositeAttachmentAdapter: {},
}));
vi.mock("@/app/newchat/adapter/server-dictation-adapter", () => ({
  ServerDictationAdapter: class {},
}));
vi.mock("@/app/newchat/adapter/remote-chat-model-adapter", () => ({
  remoteChatModelAdapter: { run: fixture.remoteRun },
}));
vi.mock("@/app/newchat/assistant-ui/thread", () => ({
  Thread: (props: ThreadProps) => {
    fixture.thread(props);
    return <>{props.welcomeContent}</>;
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  fixture.state.isRunning = false;
  fixture.controls.canCreate = true;
  fixture.controls.canSend = true;
});

it("keeps tenant model controls connected while shared suggestions only fill input", () => {
  render(<Nl2AgentChatPanel agentId={42} />);
  const props = fixture.thread.mock.calls.at(-1)![0] as ThreadProps;
  expect(props).toMatchObject({
    modelSelectionScope: "tenant",
    showModelSelector: true,
    readOnly: false,
    selectedModelId: "3",
    onModelChange: fixture.controls.onModelChange,
    deepThinking: true,
    thinkingEffort: "xhigh",
    reasoningBudgetTokens: 2048,
    onDeepThinkingChange: fixture.controls.onDeepThinkingChange,
    onThinkingEffortChange: fixture.controls.onThinkingEffortChange,
    onReasoningBudgetTokensChange:
      fixture.controls.onReasoningBudgetTokensChange,
    modelParameterSettings: fixture.controls.modelParameterSettings,
  });
  expect(props.composerTools).toBeUndefined();
  expect(props.onChatModeChange).toBeUndefined();
  expect(props.workbenchResources).toBeUndefined();
  expect(screen.getByText("nl2agent.configuration.title")).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", {
      name: /nl2agent.suggestions.generatePrompts.title/,
    })
  );
  expect(fixture.runtime.thread.composer.setText).toHaveBeenCalledWith(
    "nl2agent.suggestions.generatePrompts.prompt"
  );
  expect(fixture.runtime.thread.append).not.toHaveBeenCalled();
  expect(fixture.remoteRun).not.toHaveBeenCalled();
});

it.each(["permission", "disabled", "running"])(
  "blocks welcome actions when %s",
  (condition) => {
    fixture.controls.canCreate = condition !== "permission";
    fixture.state.isRunning = condition === "running";
    render(<Nl2AgentChatPanel disabled={condition === "disabled"} />);
    for (const button of screen.getAllByRole("button"))
      expect(button).toBeDisabled();
    const props = fixture.thread.mock.calls.at(-1)![0] as ThreadProps;
    if (condition !== "running") expect(props.readOnly).toBe(true);
  }
);

it("retains per-turn model snapshots in the creation adapter including canonical sampling", async () => {
  render(<Nl2AgentChatPanel agentId={42} />);
  const result = fixture.adapter!.run({
    messages: [],
    runConfig: { custom: { retained: true } },
  } as never);
  for await (const chunk of result as AsyncIterable<unknown>) {
    void chunk;
  }
  expect(fixture.remoteRun).toHaveBeenCalledWith(
    expect.objectContaining({
      runConfig: {
        custom: expect.objectContaining({
          retained: true,
          runtimeMode: "nl2agent",
          agentId: 42,
          turnModelControls: fixture.controls.snapshot,
        }),
      },
    })
  );
  expect(JSON.stringify(fixture.remoteRun.mock.calls)).toContain("temperature");
});

it("blocks invalid-model sends and imperative prompts without a creation target", async () => {
  const ref = createRef<Nl2AgentChatPanelHandle>();
  fixture.controls.canSend = false;
  const view = render(
    <Nl2AgentChatPanel
      ref={ref}
      agentId={42}
      showOptimizationSuggestions={false}
    />
  );
  ref.current!.sendPrompt("create");
  const result = fixture.adapter!.run({ messages: [] } as never);
  for await (const chunk of result as AsyncIterable<unknown>) {
    void chunk;
  }
  expect(fixture.remoteRun).not.toHaveBeenCalled();
  expect(fixture.runtime.thread.append).not.toHaveBeenCalled();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  fixture.controls.canSend = true;
  view.rerender(<Nl2AgentChatPanel ref={ref} agentId={null} />);
  ref.current!.sendPrompt("create");
  expect(fixture.runtime.thread.append).not.toHaveBeenCalled();
});
