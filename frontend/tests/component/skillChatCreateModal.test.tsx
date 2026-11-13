// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, expect, test, vi } from "vitest";
import SkillChatCreateModal from "@/components/skill/SkillChatCreateModal";
import type {
  SkillCreationEvent,
  SkillChatPayload,
} from "@/lib/skillChatDraft";

const chat = vi.hoisted(() => ({ snapshot: {} as Record<string, unknown> }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "zh" } }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { id: "u", tenantId: "t" } }),
}));
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn(), warn: vi.fn() } }));
vi.mock("@/app/newchat/assistant-ui/nl2skill-chat-panel", () => ({
  Nl2SkillChatPanel: ({
    onStreamEvent,
    getDraftSnapshot,
    onSkillFileSelect,
  }: {
    onStreamEvent: (event: SkillCreationEvent) => void;
    getDraftSnapshot: () => Record<string, unknown>;
    onSkillFileSelect: (path: string) => void;
  }) => (
    <div>
      <button
        onClick={() => {
          onStreamEvent({ type: "agent_new_run" });
          onStreamEvent({
            type: "skill_body",
            content:
              "---\nname: generated-skill\ndescription: Generated instructions\ntags: []\n---\n# Body",
          });
          onStreamEvent({ type: "done" });
        }}
      >
        Generate skill
      </button>
      <button
        onClick={() => {
          chat.snapshot = getDraftSnapshot();
        }}
      >
        Read snapshot
      </button>
      <button onClick={() => onStreamEvent({ type: "agent_new_run" })}>
        Start generation
      </button>
      <button
        onClick={() => {
          onStreamEvent({ type: "skill_body", content: "broken" });
          onStreamEvent({ type: "error" });
        }}
      >
        Fail generation
      </button>
      <button onClick={() => onSkillFileSelect("references/guide.txt")}>
        Open reference
      </button>
    </div>
  ),
}));
vi.mock("@/components/skill/SkillChatEditor", () => ({
  default: ({
    payload,
    open,
    running,
    selectedPath,
    onNew,
    onDraftChange,
    onSaved,
    onBusyChange,
  }: {
    payload: SkillChatPayload | null;
    open: boolean;
    running: boolean;
    selectedPath: string;
    onNew: () => void;
    onDraftChange: (payload: SkillChatPayload) => void;
    onSaved: (payload: SkillChatPayload) => void;
    onBusyChange: (value: boolean) => void;
  }) => (
    <div>
      <output aria-label="Generated name">{payload?.name ?? "empty"}</output>
      <output aria-label="Selected file">{selectedPath}</output>
      <output aria-label="Run status">{String(running)}</output>
      <output aria-label="Editor open">{String(open)}</output>
      <button
        disabled={!payload}
        onClick={() =>
          onDraftChange({
            ...payload!,
            description: "Manual description",
            content: "Edited body",
          })
        }
      >
        Edit draft
      </button>
      <button disabled={!payload} onClick={() => onSaved(payload!)}>
        Save skill
      </button>
      <button onClick={onNew}>New skill</button>
      <button onClick={() => onBusyChange(true)}>Start saving</button>
    </div>
  ),
}));
beforeEach(() => {
  sessionStorage.clear();
  chat.snapshot = {};
});
function show() {
  const props = {
    open: true,
    onClose: vi.fn(),
    onSuccess: vi.fn(),
    onOpenSkill: vi.fn(),
  };
  const result = render(
    <App>
      <SkillChatCreateModal {...props} />
    </App>
  );
  return { ...result, props };
}
test("opens an independent dialog and feeds generated content to its editor", async () => {
  const { props } = show();
  await waitFor(() => expect(screen.getByRole("dialog")).toBeVisible());
  expect(screen.getByLabelText("Generated name")).toHaveTextContent("empty");
  fireEvent.click(screen.getByText("Generate skill"));
  expect(screen.getByLabelText("Generated name")).toHaveTextContent(
    "generated-skill"
  );
  expect(screen.getByText("skillChat.summary")).toBeVisible();
  fireEvent.click(screen.getByText("Open reference"));
  expect(screen.getByLabelText("Selected file")).toHaveTextContent(
    "references/guide.txt"
  );
  expect(props.onClose).not.toHaveBeenCalled();
});
test("passes manual edits back to the next conversation draft snapshot", () => {
  show();
  fireEvent.click(screen.getByText("Generate skill"));
  fireEvent.click(screen.getByText("Edit draft"));
  fireEvent.click(screen.getByText("Read snapshot"));
  expect(chat.snapshot).toMatchObject({
    name: "generated-skill",
    description: "Manual description",
    content: "Edited body",
  });
  expect(chat.snapshot.files).toEqual([
    {
      path: "SKILL.md",
      content: expect.stringContaining("Manual description"),
    },
  ]);
});
test("refreshes Mine after saving and opens the result without leaving for the workbench", async () => {
  const { props } = show();
  fireEvent.click(screen.getByText("Generate skill"));
  fireEvent.click(screen.getByText("Save skill"));
  await waitFor(() => expect(props.onSuccess).toHaveBeenCalledTimes(1));
  fireEvent.click(
    screen.getByRole("button", { name: "skillChat.openRepository" })
  );
  expect(props.onOpenSkill).toHaveBeenCalledWith("generated-skill");
});
test("closing an empty dialog returns directly to the repository", () => {
  const { props } = show();
  fireEvent.click(screen.getByRole("button", { name: "common.close" }));
  expect(props.onClose).toHaveBeenCalledTimes(1);
});
test("requires explicit confirmation before discarding generated edits", async () => {
  const { props } = show();
  fireEvent.click(screen.getByText("Generate skill"));
  fireEvent.click(screen.getByRole("button", { name: "common.close" }));
  expect(props.onClose).not.toHaveBeenCalled();
  fireEvent.click(
    await screen.findByRole("button", { name: "common.confirm" })
  );
  await waitFor(() => expect(props.onClose).toHaveBeenCalledTimes(1));
});
test("prevents closing while generation or saving is active", () => {
  const { props } = show();
  fireEvent.click(screen.getByText("Start generation"));
  fireEvent.click(screen.getByRole("button", { name: "common.close" }));
  expect(props.onClose).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Fail generation"));
  fireEvent.click(screen.getByText("Start saving"));
  fireEvent.click(screen.getByRole("button", { name: "common.close" }));
  expect(props.onClose).not.toHaveBeenCalled();
});
test("rolls back a failed continuation to the last usable draft", () => {
  show();
  fireEvent.click(screen.getByText("Generate skill"));
  fireEvent.click(screen.getByText("Edit draft"));
  fireEvent.click(screen.getByText("Start generation"));
  fireEvent.click(screen.getByText("Fail generation"));
  fireEvent.click(screen.getByText("Read snapshot"));
  expect(chat.snapshot).toMatchObject({
    description: "Manual description",
    content: "Edited body",
  });
  expect(screen.getByLabelText("Run status")).toHaveTextContent("false");
});
