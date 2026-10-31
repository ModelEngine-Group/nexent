// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App, Form } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentPrompt from "../../../frontend/app/[locale]/agents/[agentId]/components/agent-prompt";

const mocks = vi.hoisted(() => ({
  updateDraft: vi.fn(),
  updateAgentConfig: vi.fn(),
  reconcileUnavailableModels: vi.fn(),
  flushDraft: vi.fn(),
  optimize: vi.fn(),
  readOnly: false,
  focus: null as null | {
    agentId: number;
    target: { section: string };
  },
  draft: {
    model_ids: [7],
    prompt: "duty-value",
    model_params_override: null,
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (state: unknown) => unknown) =>
    selector({
      agentId: 42,
      editedAgent: mocks.draft,
      updateDraft: mocks.updateDraft,
      updateAgentConfig: mocks.updateAgentConfig,
      reconcileUnavailableModels: mocks.reconcileUnavailableModels,
      flushDraft: mocks.flushDraft,
      defaultLlmConfig: null,
    }),
}));
vi.mock("@/hooks/agent/useAgentReadOnly", () => ({
  useAgentReadOnly: () => mocks.readOnly,
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { role: "SPEED" } }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({ isSpeedMode: true }),
}));
vi.mock("@/hooks/model/useModelList", () => ({
  useModelList: () => ({
    availableLlmModels: [{ id: 7, displayName: "Fixture Model", type: "llm" }],
    isSuccess: true,
  }),
}));
vi.mock("@/hooks/model/useInferenceFieldSpecs", () => ({
  useInferenceFieldSpecs: () => ({ specs: {} }),
}));
vi.mock("@/contexts/nl2AgentFlow", () => ({
  useNl2AgentFlow: () => ({ configFocusRequest: mocks.focus }),
}));

function promptTree(highFidelity = true) {
  return (
    <App>
      <Form initialValues={{ model_ids: [7] }}>
        <AgentPrompt
          highFidelity={highFidelity}
          onOptimizePrompt={mocks.optimize}
        />
      </Form>
    </App>
  );
}

describe("AGENT-CONFIG-D1-001 actual nested prompt capability", () => {
  beforeEach(() => {
    mocks.readOnly = false;
    mocks.focus = null;
    mocks.optimize.mockReset();
    mocks.updateDraft.mockReset();
    mocks.updateAgentConfig.mockReset();
    mocks.reconcileUnavailableModels.mockReset();
  });

  it("focuses the complete prompt without opening split-field tabs or writing", async () => {
    const view = render(promptTree());
    mocks.focus = { agentId: 42, target: { section: "role_model" } };
    view.rerender(promptTree());
    const input = document.getElementById("agent-primary-prompt")!;
    await waitFor(() => expect(input).toHaveFocus());
    expect(input).toHaveValue(mocks.draft.prompt);
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mocks.updateDraft).not.toHaveBeenCalled();
    expect(mocks.updateAgentConfig).not.toHaveBeenCalled();
    expect(mocks.reconcileUnavailableModels).not.toHaveBeenCalled();
  });

  it("routes optimization only on click and disables it for read-only drafts", () => {
    const view = render(promptTree());
    expect(mocks.optimize).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "agent.highFidelity.optimizePrompt" }),
    );
    expect(mocks.optimize).toHaveBeenCalledOnce();
    mocks.readOnly = true;
    view.rerender(promptTree());
    const optimizeButton = screen.getByRole("button", {
      name: "agent.highFidelity.optimizePrompt",
    });
    expect(optimizeButton).toBeDisabled();
    fireEvent.click(optimizeButton);
    expect(mocks.optimize).toHaveBeenCalledOnce();
  });
});

describe("AGENT-CONFIG-D1-004 complete prompt boundaries", () => {
  beforeEach(() => {
    mocks.readOnly = false;
    mocks.focus = null;
    mocks.draft.prompt = "";
    mocks.updateDraft.mockReset();
    mocks.updateAgentConfig.mockReset();
  });

  it("accepts an exact 1000-character complete prompt", () => {
    render(promptTree());
    const duty = document.getElementById("agent-primary-prompt")!;
    expect(duty).toHaveAttribute("maxlength", "1000");
    const boundary = "d".repeat(1000);
    fireEvent.change(duty, { target: { value: boundary } });
    expect(mocks.updateDraft).toHaveBeenLastCalledWith({
      prompt: boundary,
    });
  });

  it("shows all saved long text without writing and permits shortening", () => {
    const legacy = "d".repeat(1001);
    mocks.draft.prompt = legacy;
    const view = render(promptTree());
    const duty = document.getElementById("agent-primary-prompt")!;
    expect(duty).toHaveValue(legacy);
    expect(mocks.updateDraft).not.toHaveBeenCalled();
    fireEvent.change(duty, { target: { value: "d".repeat(1002) } });
    expect(mocks.updateDraft).not.toHaveBeenCalled();
    const shortened = "d".repeat(999);
    fireEvent.change(duty, { target: { value: shortened } });
    expect(mocks.updateDraft).toHaveBeenLastCalledWith({
      prompt: shortened,
    });
    mocks.draft.prompt = shortened;
    view.rerender(promptTree());
    expect(duty).toHaveAttribute("maxlength", "1000");
  });

  it("keeps the default prompt field without the high-fidelity limit", () => {
    render(promptTree(false));
    expect(
      screen.getByPlaceholderText("agent.field.promptPlaceholder"),
    ).not.toHaveAttribute("maxlength");
  });
});
