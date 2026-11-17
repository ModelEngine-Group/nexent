// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import en from "@/public/locales/en/common.json";

import { PromptGenerationCard } from "@/app/newchat/ui/prompt-generation-card";
import { Nl2AgentFlowProvider } from "@/contexts/nl2AgentFlow";
import {
  parseNl2aMessage,
  type Nl2aPromptGenerationPayload,
} from "@/app/newchat/adapter/remote-chat-model-adapter";

const { append } = vi.hoisted(() => ({ append: vi.fn() }));
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({
    t: (key: string) => en[key as keyof typeof en] ?? key,
  }),
}));
vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({
    thread: () => ({
      append,
      composer: () => ({ getState: () => ({ runConfig: {} }) }),
    }),
  }),
  useAuiState: () => false,
}));

const payload: Nl2aPromptGenerationPayload = {
  subtype: "prompt_generation",
  agent_id: 42,
  conversation_id: "7",
  run_id: "run",
  card_id: "card",
  prompt_revision: "revision",
  proposed_prompt: "Full prompt\nPreserved instructions",
  status: "pending",
};

it("previews without writes and applies only an identity-scoped action once", async () => {
  append.mockClear();
  render(
    <Nl2AgentFlowProvider>
      <PromptGenerationCard payload={payload} />
    </Nl2AgentFlowProvider>
  );
  expect(append).not.toHaveBeenCalled();
  expect(screen.getByText(/Full prompt/).textContent).toBe(
    payload.proposed_prompt
  );
  fireEvent.click(screen.getByRole("button", { name: "View full prompt" }));
  expect(screen.getByRole("button", { name: "Collapse" })).toHaveAttribute(
    "aria-expanded",
    "true"
  );
  fireEvent.click(screen.getByRole("button", { name: "Confirm and apply" }));
  expect(append).toHaveBeenCalledTimes(1);
  const request = append.mock.calls[0][0];
  expect(request.metadata.custom.nl2agentCardAction).toEqual({
    type: "nl2agent_card_action",
    subtype: "prompt_generation",
    agent_id: 42,
    action: "apply",
    result: {
      card_id: "card",
      prompt_revision: "revision",
      prompt: payload.proposed_prompt,
    },
  });
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  request.runConfig.custom.onRunStarted();
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent("Applied")
  );
});

it("retains a failed proposal for retry and cancels without a text payload", async () => {
  append.mockClear();
  render(
    <Nl2AgentFlowProvider>
      <PromptGenerationCard payload={payload} />
    </Nl2AgentFlowProvider>
  );
  fireEvent.click(screen.getByRole("button", { name: "Confirm and apply" }));
  append.mock.calls[0][0].runConfig.custom.onRunRejected();
  await waitFor(() => expect(screen.getByRole("alert")).toBeVisible());
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(
    append.mock.calls[1][0].metadata.custom.nl2agentCardAction.action
  ).toBe("cancel");
  append.mock.calls[1][0].runConfig.custom.onRunStarted();
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent("Cancelled")
  );
});

it("restores terminal cards read-only and rejects malformed preview payloads", () => {
  render(
    <Nl2AgentFlowProvider>
      <PromptGenerationCard payload={{ ...payload, status: "applied" }} />
    </Nl2AgentFlowProvider>
  );
  expect(screen.getByRole("status")).toHaveTextContent("Applied");
  expect(
    screen.queryByRole("button", { name: "Confirm and apply" })
  ).toBeNull();
  expect(
    parseNl2aMessage({ type: "nl2a", content: JSON.stringify(payload) })
      ?.content
  ).toEqual(payload);
  for (const invalid of [
    { ...payload, agent_id: 0 },
    { ...payload, proposed_prompt: " " },
    { ...payload, status: "fake" },
  ]) {
    expect(
      parseNl2aMessage({ type: "nl2a", content: JSON.stringify(invalid) })
    ).toBeNull();
  }
});

it("edits multiline text locally, retains it after rejection and applies the exact edit", async () => {
  append.mockClear();
  render(
    <Nl2AgentFlowProvider>
      <PromptGenerationCard payload={payload} />
    </Nl2AgentFlowProvider>
  );
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  const editor = screen.getByRole("textbox", { name: "Prompt content" });
  const edited = " User changes\nPreserved constraints \n";
  fireEvent.change(editor, { target: { value: edited } });
  expect(append).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Confirm and apply" }));
  expect(
    append.mock.calls[0][0].metadata.custom.nl2agentCardAction.result.prompt
  ).toBe(edited);
  append.mock.calls[0][0].runConfig.custom.onRunRejected();
  await waitFor(() => expect(editor).toBeEnabled());
  expect(editor).toHaveValue(edited);
  fireEvent.click(screen.getByRole("button", { name: /Confirm and apply/ }));
  expect(
    append.mock.calls[1][0].metadata.custom.nl2agentCardAction.result.prompt
  ).toBe(edited);
  append.mock.calls[1][0].runConfig.custom.onRunStarted();
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent("Applied")
  );
  expect(screen.getByText(/User changes/).textContent).toBe(edited);
  expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
});

it("blocks empty edits, restores generated content, and never sends cancelled edits", () => {
  append.mockClear();
  render(
    <Nl2AgentFlowProvider>
      <PromptGenerationCard payload={payload} />
    </Nl2AgentFlowProvider>
  );
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  const editor = screen.getByRole("textbox", { name: "Prompt content" });
  fireEvent.change(editor, { target: { value: " \n" } });
  expect(
    screen.getByRole("button", { name: "Confirm and apply" })
  ).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "Restore generated content" })
  );
  expect(editor).toHaveValue(payload.proposed_prompt);
  fireEvent.change(editor, { target: { value: "Do not save this" } });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(
    append.mock.calls[0][0].metadata.custom.nl2agentCardAction.result
  ).toEqual({
    card_id: "card",
    prompt_revision: "revision",
  });
});
