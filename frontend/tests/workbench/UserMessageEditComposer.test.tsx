// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  AssistantRuntimeProvider,
  ThreadPrimitive,
  useLocalRuntime,
  type AssistantRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { ThreadMessages } from "@/app/newchat/assistant-ui/thread";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { Agent } from "@/types/agentConfig";

vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en", resolvedLanguage: "en" },
  }),
}));
vi.mock("@/app/newchat/assistant-ui/composer", () => ({
  Composer: () => null,
}));
vi.mock("react-shiki", () => ({ useShikiHighlighter: vi.fn() }));
vi.mock("@/app/newchat/adapter/remote-chat-model-adapter", () => ({
  searchSourcesRegistry: new Map(),
  searchImagesRegistry: new Map(),
  conversationSourcesRegistry: new Map(),
  skillFileUploadsRegistry: new Map(),
  stepTokenCounts: [],
}));

const originalQuestion = "Original question";
const originalAnswer = "Original answer";
const agent = { id: 1, name: "Fixture Agent" } as unknown as Agent;
const run = vi.fn<ChatModelAdapter["run"]>(async () => ({
  content: [{ type: "text", text: "Edited answer" }],
}));
let runtime: AssistantRuntime;

function Harness({ readOnly = false, shareMode = false } = {}) {
  const localRuntime = useLocalRuntime(
    { run },
    {
      initialMessages: [
        { id: "question", role: "user", content: originalQuestion },
        { id: "answer", role: "assistant", content: originalAnswer },
      ],
    }
  );
  useEffect(() => {
    runtime = localRuntime;
  }, [localRuntime]);
  return (
    <AssistantRuntimeProvider runtime={localRuntime}>
      <TooltipProvider>
        <ThreadPrimitive.Root>
          <ThreadMessages
            agent={agent}
            readOnly={readOnly}
            shareMode={shareMode}
          />
        </ThreadPrimitive.Root>
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
}

beforeEach(() => run.mockClear());

async function openEditor(user: ReturnType<typeof userEvent.setup>) {
  await user.hover(screen.getByText(originalQuestion));
  await user.click(
    await screen.findByRole("button", { name: "chat.thread.edit" })
  );
  return screen.getByRole("textbox", { name: "chat.thread.edit" });
}

it("opens the original message in the registered inline edit composer", async () => {
  const user = userEvent.setup();
  const { container } = render(<Harness />);
  expect(screen.getByText(originalQuestion)).toBeVisible();
  const input = await openEditor(user);
  expect(input).toHaveValue(originalQuestion);
  expect(container.querySelectorAll("textarea")).toHaveLength(1);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByText(originalAnswer)).toBeVisible();
  expect(run).not.toHaveBeenCalled();
});

it.each(["button", "Escape"])(
  "cancels with %s without changing the original conversation",
  async (method) => {
    const user = userEvent.setup();
    render(<Harness />);
    const originalMessages = runtime.thread.getState().messages;
    const input = await openEditor(user);
    await user.clear(input);
    await user.type(input, "Discard this edit");
    if (method === "button") {
      await user.click(screen.getByRole("button", { name: "common.cancel" }));
    } else {
      await user.keyboard("{Escape}");
    }
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByText(originalQuestion)).toBeVisible();
    expect(screen.getByText(originalAnswer)).toBeVisible();
    expect(runtime.thread.getState().messages).toEqual(originalMessages);
    expect(run).not.toHaveBeenCalled();
  }
);

it("keeps plain Enter multiline and sends the edited branch exactly once", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  const input = await openEditor(user);
  await user.clear(input);
  expect(
    screen.getByRole("button", { name: "chat.composer.send" })
  ).toBeDisabled();
  await user.type(input, "Edited question{Enter}Second line");
  expect(input).toHaveValue("Edited question\nSecond line");
  expect(run).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "chat.composer.send" }));
  await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
  expect(run.mock.calls[0][0].messages.at(-1)?.content).toEqual([
    { type: "text", text: "Edited question\nSecond line" },
  ]);
  await waitFor(() => expect(screen.getByText("Edited answer")).toBeVisible());
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(
    runtime.thread.getState().messages.map((message) => message.role)
  ).toEqual(["user", "assistant"]);
});

it("ignores Escape during IME composition", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  const input = await openEditor(user);
  fireEvent.keyDown(input, { key: "Escape", isComposing: true });
  expect(input).toBeInTheDocument();
  expect(run).not.toHaveBeenCalled();
});

it.each([{ readOnly: true }, { readOnly: true, shareMode: true }])(
  "does not offer message editing in restricted mode %j",
  async (props) => {
    const user = userEvent.setup();
    render(<Harness {...props} />);
    await user.hover(screen.getByText(originalQuestion));
    expect(
      screen.queryByRole("button", { name: "chat.thread.edit" })
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(run).not.toHaveBeenCalled();
  }
);
