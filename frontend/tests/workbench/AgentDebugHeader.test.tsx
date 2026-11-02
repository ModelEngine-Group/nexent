// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState, type ReactNode } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import AgentDebugPanel from "@/app/agents/[agentId]/components/debug/agent-debug";
import type { AgentDraft } from "@/stores/agentStore";
import type { ChatMode } from "@/app/newchat/assistant-ui/composer";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
import zh from "@/public/locales/zh/common.json";
import en from "@/public/locales/en/common.json";

const fixture = vi.hoisted(() => ({
  locale: "zh" as "zh" | "en",
  agentId: 42 as number | null,
  editedAgent: {
    name: "Internal name",
    display_name: "Draft name",
    model_ids: [3],
  } as AgentDraft | null,
  runtime: {
    thread: {
      cancelRun: vi.fn(),
      reset: vi.fn(),
      composer: { setRunConfig: vi.fn() },
    },
  },
}));

vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({
    t: (key: string) =>
      (
        (fixture.locale === "zh" ? zh : en) as unknown as Record<string, string>
      )[key] ?? key,
  }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (state: typeof fixture) => unknown) =>
    selector(fixture),
}));
vi.mock("@assistant-ui/react", () => ({
  AssistantRuntimeProvider: ({ children }: { children: ReactNode }) => children,
  useLocalRuntime: () => fixture.runtime,
  useAui: () => ({}),
  useAuiState: () => false,
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
  Thread: ({
    chatMode,
    onChatModeChange,
  }: {
    chatMode: ChatMode;
    onChatModeChange?: (mode: ChatMode) => void;
  }) => (
    <>
      <input aria-label="Single draft" defaultValue="unsent draft" />
      <output data-testid="single-chat-mode">{chatMode}</output>
      <button
        onClick={() =>
          onChatModeChange?.(
            chatMode === "execution" ? "planning" : "execution"
          )
        }
      >
        Switch single mode
      </button>
    </>
  ),
}));
vi.mock("@/app/agents/[agentId]/components/debug/compare-panel", () => ({
  AgentDebugComparePanel: ({
    clearEpoch,
    chatMode,
    onChatModeChange,
  }: {
    clearEpoch: number;
    chatMode: ChatMode;
    onChatModeChange: (mode: ChatMode) => void;
  }) => (
    <>
      <output data-testid="compare-clear-epoch">{clearEpoch}</output>
      <output data-testid="compare-chat-mode">{chatMode}</output>
      <button
        onClick={() =>
          onChatModeChange(chatMode === "execution" ? "planning" : "execution")
        }
      >
        Switch compare mode
      </button>
    </>
  ),
}));

beforeEach(() => {
  vi.clearAllMocks();
  fixture.locale = "zh";
  fixture.agentId = 42;
  fixture.editedAgent = {
    name: "Internal name",
    display_name: "Draft name",
    model_ids: [3],
  } as AgentDraft;
});

function ControlledPanel() {
  const [compare, setCompare] = useState(false);
  const [open, setOpen] = useState(true);
  return (
    <>
      <style>{".hidden { display: none; }"}</style>
      {open && (
        <AgentDebugPanel
          isCompareMode={compare}
          onCompareModeChange={setCompare}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

it("switches ordinary debug mode both ways and updates the runtime planning flag", () => {
  render(<ControlledPanel />);
  const mode = screen.getByTestId("single-chat-mode");
  const toggle = screen.getByRole("button", { name: "Switch single mode" });
  expect(mode).toHaveTextContent("execution");
  expect(fixture.runtime.thread.composer.setRunConfig).toHaveBeenLastCalledWith(
    {
      custom: { agentId: 42, enablePlan: false, modelId: "3" },
    }
  );
  fireEvent.click(toggle);
  expect(mode).toHaveTextContent("planning");
  expect(fixture.runtime.thread.composer.setRunConfig).toHaveBeenLastCalledWith(
    {
      custom: { agentId: 42, enablePlan: true, modelId: "3" },
    }
  );
  fireEvent.click(toggle);
  expect(mode).toHaveTextContent("execution");
  expect(fixture.runtime.thread.composer.setRunConfig).toHaveBeenLastCalledWith(
    {
      custom: { agentId: 42, enablePlan: false, modelId: "3" },
    }
  );
  expect(fixture.runtime.thread.reset).not.toHaveBeenCalled();
  expect(fixture.runtime.thread.cancelRun).not.toHaveBeenCalled();
  expect(remoteChatModelAdapter.run).not.toHaveBeenCalled();
});

it("shares the mode across ordinary and compare views without clearing unsent text", () => {
  render(<ControlledPanel />);
  const draft = screen.getByRole("textbox", { name: "Single draft" });
  fireEvent.change(draft, { target: { value: "Keep this draft" } });
  fireEvent.click(screen.getByRole("button", { name: "Switch single mode" }));
  fireEvent.click(screen.getByRole("button", { name: "切换对比模式" }));
  expect(screen.getByTestId("compare-chat-mode")).toHaveTextContent("planning");
  fireEvent.click(screen.getByRole("button", { name: "Switch compare mode" }));
  fireEvent.click(screen.getByRole("button", { name: "切换对比模式" }));
  expect(screen.getByTestId("single-chat-mode")).toHaveTextContent("execution");
  expect(draft).toBeVisible();
  expect(draft).toHaveValue("Keep this draft");
  expect(fixture.runtime.thread.reset).not.toHaveBeenCalled();
  expect(fixture.runtime.thread.cancelRun).not.toHaveBeenCalled();
  expect(remoteChatModelAdapter.run).not.toHaveBeenCalled();
});

it("shows a static name and toggles comparison both ways without replacing the single draft", async () => {
  render(<ControlledPanel />);
  const name = screen.getByText("Draft name");
  expect(name.closest("button")).toBeNull();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  const toggle = screen.getByRole("button", { name: "切换对比模式" });
  expect(name.nextElementSibling?.contains(toggle)).toBe(true);
  expect(toggle).toHaveAttribute("aria-pressed", "false");
  fireEvent.mouseOver(toggle);
  expect(await screen.findByRole("tooltip")).toHaveTextContent("切换对比模式");
  fireEvent.mouseOut(toggle);
  const draft = screen.getByRole("textbox", { name: "Single draft" });
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("compare-clear-epoch")).toBeVisible();
  expect(draft).not.toBeVisible();
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-pressed", "false");
  expect(draft).toBeVisible();
  expect(draft).toHaveValue("unsent draft");
  expect(fixture.runtime.thread.reset).not.toHaveBeenCalled();
});

it("clears only the active mode using the new-conversation icon", () => {
  render(<ControlledPanel />);
  const clear = screen.getByRole("button", { name: zh["agent.debug.clear"] });
  expect(clear.querySelector("svg.lucide-square-pen")).toBeInTheDocument();
  fireEvent.click(clear);
  expect(fixture.runtime.thread.cancelRun).toHaveBeenCalledTimes(1);
  expect(fixture.runtime.thread.reset).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "切换对比模式" }));
  fireEvent.click(clear);
  expect(screen.getByTestId("compare-clear-epoch")).toHaveTextContent("1");
  expect(fixture.runtime.thread.reset).toHaveBeenCalledTimes(1);
});

it("closes debug from the rightmost X with its localized tooltip", async () => {
  render(<ControlledPanel />);
  const panel = screen.getByTestId("agent-debug-panel");
  const close = within(panel).getByRole("button", { name: "关闭调试" });
  expect(
    within(panel.querySelector("header")!).getAllByRole("button").at(-1)
  ).toBe(close);
  expect(close.querySelector("svg.lucide-x")).toBeInTheDocument();
  fireEvent.mouseOver(close);
  expect(await screen.findByRole("tooltip")).toHaveTextContent("关闭调试");
  fireEvent.click(close);
  expect(screen.queryByTestId("agent-debug-panel")).not.toBeInTheDocument();
});

it("keeps fullscreen controls and English labels", () => {
  fixture.locale = "en";
  const onToggleFullscreen = vi.fn();
  const view = render(
    <AgentDebugPanel onToggleFullscreen={onToggleFullscreen} />
  );
  expect(
    screen.getByRole("button", { name: "Switch comparison mode" })
  ).toHaveAttribute("aria-pressed", "false");
  expect(
    screen.getByRole("button", { name: en["agent.page.panel.debug.closeAria"] })
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: en["agent.debug.maximize"] })
  );
  expect(onToggleFullscreen).toHaveBeenCalledTimes(1);
  view.rerender(
    <AgentDebugPanel isFullscreen onToggleFullscreen={onToggleFullscreen} />
  );
  fireEvent.click(
    screen.getByRole("button", { name: en["agent.debug.restore"] })
  );
  expect(onToggleFullscreen).toHaveBeenCalledTimes(2);
});

it("uses the internal name fallback and tolerates omitted optional callbacks", () => {
  fixture.editedAgent!.display_name = "";
  render(<AgentDebugPanel />);
  expect(screen.getByText("Internal name")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "切换对比模式" }));
  fireEvent.click(screen.getByRole("button", { name: "关闭调试" }));
  expect(screen.getByTestId("agent-debug-panel")).toBeInTheDocument();
});

it("renders the empty state without active header controls when no agent is selected", () => {
  fixture.agentId = null;
  fixture.editedAgent = null;
  render(<AgentDebugPanel />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(
    screen.getByText(zh["systemPrompt.nonEditing.subtitle"])
  ).toBeInTheDocument();
});
