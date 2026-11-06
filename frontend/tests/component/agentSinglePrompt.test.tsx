// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App, Form } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { StrictMode } from "react";
import AgentPrompt from "../../app/[locale]/agents/[agentId]/components/agent-prompt";

const mocks = vi.hoisted(() => ({
  updateDraft: vi.fn(),
  updateAgent: vi.fn(),
  modelListLoaded: false,
  configLoaded: true,
  defaultModelId: 2 as number | undefined,
  readOnly: false,
  promptsHidden: false,
  agentId: 157,
  focus: null as null | Record<string, unknown>,
  models: [] as unknown[],
  specs: [] as unknown[],
  agent: {
    prompt: "Complete prompt with constraints and examples",
    constraint_prompt: "LEGACY_RULE_POISON",
    few_shots_prompt: "LEGACY_EXAMPLE_POISON",
    model_ids: [] as number[],
    model_params_override: null as Record<string, Record<string, unknown>> | null,
  },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (state: unknown) => unknown) =>
    selector({
      agentId: mocks.agentId,
      promptsHidden: mocks.promptsHidden,
      editedAgent: mocks.agent,
      updateDraft: mocks.updateDraft,
      updateAgentConfig: mocks.updateAgent,
      reconcileUnavailableModels: vi.fn(),
      defaultLlmConfig: null,
    }),
}));
vi.mock("@/hooks/model/useModelList", () => ({
  useModelList: () => ({
    llmModels: mocks.models,
    availableLlmModels: mocks.models,
    isSuccess: mocks.modelListLoaded,
  }),
}));
vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({
    defaultLlmModelConfig: { id: mocks.defaultModelId },
    isSuccess: mocks.configLoaded,
  }),

}));
vi.mock("@/hooks/model/useInferenceFieldSpecs", () => ({
  useInferenceFieldSpecs: () => ({ specs: mocks.specs }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: null }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({ isSpeedMode: true }),
}));
vi.mock("@/contexts/nl2AgentFlow", () => ({
  useNl2AgentFlow: () => ({ configFocusRequest: mocks.focus }),
}));
vi.mock("@/hooks/agent/useAgentReadOnly", () => ({
  useAgentReadOnly: () => mocks.readOnly,
}));
vi.mock("@/services/modelProfileService", () => ({
  getModelOutlet: vi.fn(async () => ({ config_revision: 7, profile: {
    parameter_values: { temperature: 0.8 }, capabilities: { reasoning: { status: "unknown" } },
    parameter_rules: [{ key: "temperature", visible: true, editable: true, required: false,
      allowed_scopes: ["outlet", "conversation"], schema: { type: "number", minimum: 0, maximum: 2 } }],
  }})),
}));
vi.mock("@/components/resource-picker/ModelDrawer", () => ({
  ModelDrawer: () => null,
}));
vi.mock("@/components/resource-picker/ModelParamsModal", () => ({
  ModelParamsModal: () => null,
}));
vi.mock("@/components/common/ExpandEditModal", () => ({ default: () => null }));

beforeEach(() => {
  mocks.agent.prompt = "Complete prompt with constraints and examples";
  mocks.focus = null;
  mocks.agent.model_ids = [];
  mocks.agent.model_params_override = null;
  mocks.models = [];
  mocks.modelListLoaded = false;
  mocks.configLoaded = true;
  mocks.defaultModelId = 2;
  mocks.readOnly = false;
  mocks.promptsHidden = false;
  mocks.agentId = 157;
  mocks.updateAgent.mockReset();
  mocks.updateDraft.mockReset();
});

function renderEditor() {
  let editorForm: ReturnType<typeof Form.useForm>[0];
  function Editor() {
    const [form] = Form.useForm();
    editorForm = form;
    return (
      <Form form={form}>
        <AgentPrompt highFidelity />
      </Form>
    );
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = () => <QueryClientProvider client={client}><App><Editor /></App></QueryClientProvider>;
  const view = render(tree());
  return {
    ...view,
    refresh: () => view.rerender(tree()),
    getForm: () => editorForm,
  };
}

function loadModels() {
  mocks.models = [1, 2].map((id) => ({
    id,
    name: `model-${id}`,
    displayName: `Model ${id}`,
    type: "llm",
    connect_status: "available",
  }));
  mocks.modelListLoaded = true;
}

test.each(["", " \n\t "])(
  "marks a blank prompt invalid and clears the hint after filling: %j",
  async (prompt) => {
    mocks.agent.prompt = prompt;
    const view = renderEditor();
    const input = screen.getByRole("textbox", {
      name: /agent.highFidelity.prompt$/,
    });
    expect(input).toHaveAttribute("aria-required", "true");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input.closest(".ant-input-textarea-affix-wrapper")).toHaveClass(
      "ant-input-status-error"
    );
    const hint = screen.getByText("agent.validation.promptRequired");
    expect(hint).toHaveClass("text-xs");
    expect(hint.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(input).toHaveAttribute("aria-describedby", hint.id);
    fireEvent.change(input, { target: { value: "A complete prompt" } });
    expect(mocks.updateDraft).toHaveBeenCalledWith({
      prompt: "A complete prompt",
    });
    mocks.agent.prompt = "A complete prompt";
    view.refresh();
    await waitFor(() =>
      expect(
        screen.queryByText("agent.validation.promptRequired")
      ).not.toBeInTheDocument()
    );
    expect(input).toHaveAttribute("aria-invalid", "false");
  }
);

test("initializes form and autosave from the configured default rather than the first model", async () => {
  loadModels();
  const view = renderEditor();
  await waitFor(() =>
    expect(mocks.updateAgent).toHaveBeenCalledExactlyOnceWith({
      model_ids: [2],
      model: "Model 2",
      model_names: ["Model 2"],
    })
  );
  expect(view.getForm().getFieldValue("model_ids")).toEqual([2]);
});

test.each(["config", "models"])(
  "waits for late %s data before initializing",
  async (late) => {
    loadModels();
    mocks.configLoaded = late !== "config";
    mocks.modelListLoaded = late !== "models";
    const view = renderEditor();
    expect(mocks.updateAgent).not.toHaveBeenCalled();
    mocks.configLoaded = true;
    mocks.modelListLoaded = true;
    view.refresh();
    await waitFor(() =>
      expect(mocks.updateAgent).toHaveBeenCalledWith(
        expect.objectContaining({ model_ids: [2] })
      )
    );
  }
);

test.each([undefined, 999])(
  "leaves selection empty for missing or unavailable default %s",
  (id) => {
    loadModels();
    mocks.defaultModelId = id;
    renderEditor();
    expect(mocks.updateAgent).not.toHaveBeenCalled();
  }
);

test("does not initialize while config is failed/loading", () => {
  loadModels();
  mocks.configLoaded = false;
  renderEditor();
  expect(mocks.updateAgent).not.toHaveBeenCalled();
});

test("preserves existing ordered selections and read-only Agents", () => {
  loadModels();
  mocks.agent.model_ids = [1, 2];
  const view = renderEditor();
  expect(mocks.updateAgent).not.toHaveBeenCalled();
  mocks.agent.model_ids = [];
  mocks.agentId = 158;
  mocks.readOnly = true;
  view.refresh();
  expect(mocks.updateAgent).not.toHaveBeenCalled();
});

test("preserves manual clearing and initializes again when switching Agents", () => {
  loadModels();
  mocks.agent.model_ids = [1];
  function Editor() {
    return (
      <Form>
        <AgentPrompt highFidelity />
      </Form>
    );
  }
  const view = render(<Editor />);
  mocks.agent.model_ids = [];
  view.rerender(<Editor />);
  expect(mocks.updateAgent).not.toHaveBeenCalled();
  mocks.agentId = 158;
  view.rerender(<Editor />);
  expect(mocks.updateAgent).toHaveBeenCalledExactlyOnceWith(
    expect.objectContaining({ model_ids: [2] })
  );
});

test("does not duplicate initialization when React replays effects", () => {
  loadModels();
  render(
    <StrictMode>
      <Form>
        <AgentPrompt highFidelity />
      </Form>
    </StrictMode>
  );
  expect(mocks.updateAgent).toHaveBeenCalledExactlyOnceWith(
    expect.objectContaining({ model_ids: [2] })
  );
});

test("preserves a manual selection made before configuration finishes loading", () => {
  loadModels();
  mocks.configLoaded = false;
  const view = renderEditor();
  mocks.agent.model_ids = [1];
  view.refresh();
  mocks.configLoaded = true;
  view.refresh();
  expect(mocks.updateAgent).not.toHaveBeenCalled();
});

test("edits only the complete prompt and renders no legacy fields or tabs", () => {
  render(
    <Form>
      <AgentPrompt highFidelity />
    </Form>
  );
  const input = screen.getByDisplayValue(mocks.agent.prompt);
  expect(screen.queryByDisplayValue("LEGACY_RULE_POISON")).toBeNull();
  expect(screen.queryByDisplayValue("LEGACY_EXAMPLE_POISON")).toBeNull();
  expect(screen.queryByRole("tab")).toBeNull();
  fireEvent.change(input, { target: { value: "Updated complete prompt" } });
  expect(mocks.updateDraft).toHaveBeenCalledExactlyOnceWith({
    prompt: "Updated complete prompt",
  });
});

test("saved prompt focus targets the complete editor without opening a legacy modal", async () => {
  mocks.focus = {
    agentId: 157,
    target: { section: "role_model" },
    id: 1,
  };
  render(
    <Form>
      <AgentPrompt highFidelity />
    </Form>
  );
  await waitFor(() =>
    expect(screen.getByDisplayValue(mocks.agent.prompt)).toHaveFocus()
  );
  expect(screen.queryByRole("dialog")).toBeNull();
});

test.each(["", "Long prompt\n".repeat(1000)])(
  "expands the current prompt and confirms edits without losing content",
  async (content) => {
    renderEditor();
    fireEvent.click(
      screen.getByRole("button", { name: "systemPrompt.button.expand" })
    );
    const dialog = await screen.findByRole("dialog");
    const input = within(dialog).getByRole("textbox");
    expect(input).toHaveValue(mocks.agent.prompt);
    fireEvent.change(input, { target: { value: content } });
    expect(mocks.updateDraft).not.toHaveBeenCalled();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "common.confirm" })
    );
    expect(mocks.updateDraft).toHaveBeenCalledExactlyOnceWith({
      prompt: content,
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  }
);

test.each(["common.cancel", "common.close"])(
  "discards modal edits on %s and reopens with the current prompt",
  async (action) => {
    renderEditor();
    const expand = screen.getByRole("button", {
      name: "systemPrompt.button.expand",
    });
    fireEvent.click(expand);
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), {
      target: { value: "Unsaved edits" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: action }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(mocks.updateDraft).not.toHaveBeenCalled();
    fireEvent.click(expand);
    expect(
      within(await screen.findByRole("dialog")).getByRole("textbox")
    ).toHaveValue(mocks.agent.prompt);
  }
);

test("disables prompt expansion for read-only Agents", () => {
  mocks.readOnly = true;
  renderEditor();
  const expand = screen.getByRole("button", {
    name: "systemPrompt.button.expand",
  });
  expect(expand).toBeDisabled();
  fireEvent.click(expand);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(mocks.updateDraft).not.toHaveBeenCalled();
});


test("the actual Agent page reopens saved canonical parameters and confirms without losing custom overrides", async () => {
  loadModels();
  mocks.models = [{ id: 2, name: "Profile model", displayName: "Profile model", type: "llm",
    connect_status: "available", profileSchemaVersion: 1 }];
  mocks.agent.model_ids = [2];
  const saved = { parameter_values: { temperature: 0.2 }, custom_overrides: { nullable: null, flag: false } };
  mocks.agent.model_params_override = { "2": saved };
  const view = renderEditor();
  fireEvent.click(await screen.findByRole("button", { name: "agent.modelParamsOverride.button" }));
  let dialog = await screen.findByRole("dialog");
  await waitFor(() => expect(within(dialog).getByRole("spinbutton")).toHaveValue("0.2"));
  fireEvent.click(within(dialog).getByRole("button", { name: "common.confirm" }));
  await waitFor(() => expect(mocks.updateAgent).toHaveBeenCalledWith({ model_params_override: { "2": saved } }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  view.refresh();
  fireEvent.click(screen.getByRole("button", { name: "agent.modelParamsOverride.button" }));
  dialog = await screen.findByRole("dialog");
  await waitFor(() => expect(within(dialog).getByRole("spinbutton")).toHaveValue("0.2"));
  expect(mocks.agent.model_params_override).toEqual({ "2": saved });
});


test.each([true, false])("renders a confidential prompt without empty validation or editing controls (highFidelity=%s)", (highFidelity) => {
  mocks.readOnly = true;
  mocks.promptsHidden = true;
  mocks.agent.prompt = "";
  render(<Form><AgentPrompt highFidelity={highFidelity} onOptimizePrompt={vi.fn()} /></Form>);
  expect(screen.getByText("agent.promptVisibility.hidden")).toBeVisible();
  expect(screen.getByText("agent.promptVisibility.explanation")).toBeVisible();
  expect(document.querySelector("#agent-primary-prompt")).toBeNull();
  expect(screen.queryByText("agent.validation.promptRequired")).toBeNull();
  expect(screen.queryByRole("button", { name: "agent.highFidelity.optimizePrompt" })).toBeNull();
  expect(screen.queryByRole("button", { name: "systemPrompt.button.expand" })).toBeNull();
  expect(mocks.updateDraft).not.toHaveBeenCalled();
});

test.each(["", "   "])("keeps required validation for editable blank prompts (%j)", (prompt) => {
  mocks.agent.prompt = prompt;
  renderEditor();
  expect(screen.getByText("agent.validation.promptRequired")).toBeVisible();
  expect(document.querySelector("#agent-primary-prompt")).toHaveAttribute("aria-invalid", "true");
  expect(screen.queryByText("agent.promptVisibility.explanation")).toBeNull();
});
