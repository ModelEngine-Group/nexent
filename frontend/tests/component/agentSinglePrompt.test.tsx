// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Form } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import AgentPrompt from "../../app/[locale]/agents/[agentId]/components/agent-prompt";

const mocks = vi.hoisted(() => ({
  updateDraft: vi.fn(),
  focus: null as null | Record<string, unknown>,
  models: [] as unknown[],
  specs: [] as unknown[],
  agent: {
    duty_prompt: "Complete prompt with constraints and examples",
    constraint_prompt: "LEGACY_RULE_POISON",
    few_shots_prompt: "LEGACY_EXAMPLE_POISON",
    model_ids: [],
  },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (state: unknown) => unknown) =>
    selector({
      agentId: 157,
      editedAgent: mocks.agent,
      updateDraft: mocks.updateDraft,
      updateAgentConfig: vi.fn(),
      reconcileUnavailableModels: vi.fn(),
      defaultLlmConfig: null,
    }),
}));
vi.mock("@/hooks/model/useModelList", () => ({
  useModelList: () => ({ availableLlmModels: mocks.models, isSuccess: false }),
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
  useAgentReadOnly: () => false,
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
});

test("edits only the complete prompt and renders no legacy fields or tabs", () => {
  render(
    <Form>
      <AgentPrompt highFidelity />
    </Form>
  );
  const input = screen.getByDisplayValue(mocks.agent.duty_prompt);
  expect(screen.queryByDisplayValue("LEGACY_RULE_POISON")).toBeNull();
  expect(screen.queryByDisplayValue("LEGACY_EXAMPLE_POISON")).toBeNull();
  expect(screen.queryByRole("tab")).toBeNull();
  fireEvent.change(input, { target: { value: "Updated complete prompt" } });
  expect(mocks.updateDraft).toHaveBeenCalledExactlyOnceWith({
    duty_prompt: "Updated complete prompt",
  });
});

test("saved prompt focus targets the complete editor without opening a legacy modal", async () => {
  mocks.focus = {
    agentId: 157,
    target: { section: "role_model", promptTab: "duty" },
    id: 1,
  };
  render(
    <Form>
      <AgentPrompt highFidelity />
    </Form>
  );
  await waitFor(() =>
    expect(screen.getByDisplayValue(mocks.agent.duty_prompt)).toHaveFocus()
  );
  expect(screen.queryByRole("dialog")).toBeNull();
});
