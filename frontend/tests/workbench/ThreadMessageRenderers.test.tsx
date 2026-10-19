// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import {
  ThreadMessageRenderProvider,
  threadMessageRenderers,
} from "@/app/newchat/assistant-ui/thread-message-renderers";
import type { Agent, PublishedAgent } from "@/types/agentConfig";

const agent = { id: 1, name: "First Agent" } as unknown as Agent;
function UserLeaf({ readOnly }: { readOnly?: boolean }) {
  const [value, setValue] = useState("");
  return (
    <input
      aria-label="Message local draft"
      disabled={readOnly}
      value={value}
      onChange={(event) => setValue(event.target.value)}
    />
  );
}
function AssistantLeaf({
  agent,
  readOnly,
  onSkillFileSelect,
}: {
  agent: Agent | PublishedAgent;
  readOnly?: boolean;
  onSkillFileSelect?: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div>
      <span>{agent.name}</span>
      <button
        disabled={readOnly}
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        Expand message
      </button>
      <button onClick={() => onSkillFileSelect?.("fixture.md")}>
        Select file
      </button>
    </div>
  );
}
it("keeps message state and DOM while applying current save locks, Agent and callback props", () => {
  const first = vi.fn(),
    second = vi.fn();
  const User = threadMessageRenderers.UserMessage,
    Assistant = threadMessageRenderers.AssistantMessage;
  const view = (
    readOnly: boolean,
    currentAgent: Agent,
    callback: (path: string) => void
  ) => (
    <ThreadMessageRenderProvider
      agent={currentAgent}
      readOnly={readOnly}
      UserMessage={UserLeaf}
      AssistantMessage={AssistantLeaf}
      onSkillFileSelect={callback}
    >
      <User />
      <Assistant />
    </ThreadMessageRenderProvider>
  );
  const { rerender } = render(view(false, agent, first));
  const draft = screen.getByRole("textbox", { name: "Message local draft" });
  const expand = screen.getByRole("button", { name: "Expand message" });
  fireEvent.change(draft, { target: { value: "Preserved message state" } });
  fireEvent.click(expand);
  rerender(view(true, agent, first));
  expect(screen.getByRole("textbox", { name: "Message local draft" })).toBe(
    draft
  );
  expect(draft).toHaveValue("Preserved message state");
  expect(draft).toBeDisabled();
  expect(expand).toHaveAttribute("aria-expanded", "true");
  expect(expand).toBeDisabled();
  rerender(view(false, { ...agent, name: "Updated Agent" }, second));
  expect(screen.getByText("Updated Agent")).toBeVisible();
  expect(draft).toBeEnabled();
  expect(screen.getByRole("button", { name: "Expand message" })).toBe(expand);
  expect(expand).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(screen.getByRole("button", { name: "Select file" }));
  expect(second).toHaveBeenCalledWith("fixture.md");
  expect(first).not.toHaveBeenCalled();
});

it("rejects rendering outside the message context", () => {
  const User = threadMessageRenderers.UserMessage;
  expect(() => render(<User />)).toThrow(
    "Thread message renderer provider is missing"
  );
});
