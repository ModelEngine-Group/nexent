// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Form } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  agentId: 157,
  focus: null as null | Record<string, unknown>,
  models: [] as unknown[],
  specs: [] as unknown[],
  agent: {
    prompt: "Complete prompt with constraints and examples",
    constraint_prompt: "LEGACY_RULE_POISON",
    few_shots_prompt: "LEGACY_EXAMPLE_POISON",
    model_ids: [] as number[],
  },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (state: unknown) => unknown) =>
    selector({
      agentId: mocks.agentId,
      editedAgent: mocks.agent,
      updateDraft: mocks.updateDraft,
      updateAgentConfig: mocks.updateAgent,
      reconcileUnavailableModels: vi.fn(),
      defaultLlmConfig: null,
    }),
}));
vi.mock("@/hooks/model/useModelList", () => ({
  useModelList: () => ({
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
vi.mock("@/components/resource-picker/ModelDrawer", () => ({
  ModelDrawer: () => null,
}));
vi.mock("@/components/resource-picker/ModelParamsModal", () => ({
  ModelParamsModal: () => null,
}));
vi.mock("@/components/common/ExpandEditModal", () => ({ default: () => null }));
vi.mock(
  "../../app/[locale]/agents/[agentId]/components/HighFidelityPromptEditModal",
  () => ({ default: () => null })
);

beforeEach(() => {
  mocks.focus = null;
  mocks.agent.model_ids = [];
  mocks.models = [];
  mocks.modelListLoaded = false;
  mocks.configLoaded = true;
  mocks.defaultModelId = 2;
  mocks.readOnly = false;
  mocks.agentId = 157;
  mocks.updateAgent.mockReset();
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
  const view = render(<Editor />);
  return {
    ...view,
    refresh: () => view.rerender(<Editor />),
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
