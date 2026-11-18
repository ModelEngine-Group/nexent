// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  ConversationModelParameters,
  ConversationModelParameterSummary,
} from "@/components/model/ConversationModelParameters";
import { ApiError } from "@/services/api";
import { readModelDraft } from "@/lib/conversationModelDrafts";

const api = vi.hoisted(() => ({
  getModelOutlet: vi.fn(),
  getConversationModelPreferences: vi.fn(),
  patchConversationModelPreferences: vi.fn(),
}));
vi.mock("@/services/modelProfileService", () => api);
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const rule = (key: string, schema: Record<string, unknown>) => ({
  key,
  schema,
  visible: true,
  editable: true,
  required: false,
  allowed_scopes: ["conversation"],
});
const view = () => ({
  parameter_values: {},
  defaults: { enable_thinking: false, temperature: 0, top_p: 0.9 },
  field_specs: [
    rule("enable_thinking", { type: "boolean" }),
    {
      ...rule("reasoning_effort", {
        type: "string",
        enum: ["low", "medium", "high"],
      }),
      condition: { key: "enable_thinking", op: "eq", value: true },
    },
    rule("temperature", { type: "number", minimum: 0, maximum: 2 }),
  ],
  issues: [],
  reasoning_status: "supported",
  output_limit: 102400,
});
function setup(conversationId?: number) {
  const props = {
    conversationId,
    draftScope: "saved-default-regression",
    modelId: 129,
    agentDefaults: {
      enable_thinking: true,
      reasoning_effort: "auto",
      temperature: 1,
    },
  };
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <App>
        <ConversationModelParameterSummary {...props} />
        <ConversationModelParameters {...props} />
      </App>
    </QueryClientProvider>
  );
}
beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.getConversationModelPreferences.mockResolvedValue(view());
  api.getModelOutlet.mockResolvedValue({
    config_revision: 10,
    profile: {
      parameter_values: view().defaults,
      parameter_rules: view().field_specs,
      capabilities: { reasoning: { status: "supported" } },
    },
  });
  api.patchConversationModelPreferences.mockResolvedValue({});
});

it("saved normalized false hides summary and degree; enabling prefills a declared effort, never legacy auto", async () => {
  setup(766);
  const toggle = await screen.findByRole("switch");
  await waitFor(() => expect(toggle).toBeEnabled());
  expect(toggle).not.toBeChecked();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(
    screen.queryByText("modelProfile.thinkingLevel.auto")
  ).not.toBeInTheDocument();
  expect(api.patchConversationModelPreferences).not.toHaveBeenCalled();
  fireEvent.click(toggle);
  await waitFor(() =>
    expect(api.patchConversationModelPreferences).toHaveBeenCalledWith(
      766,
      129,
      {
        parameter_values: { enable_thinking: true, reasoning_effort: "low" },
        delete_parameters: [],
      }
    )
  );
  expect(view().defaults.enable_thinking).toBe(false);
});

it("unsaved drafts still merge local Agent values without writing or resetting preferences", async () => {
  const before = readModelDraft("saved-default-regression", 129);
  setup();
  await waitFor(() => expect(screen.getByRole("switch")).toBeChecked());
  expect(
    await screen.findByText("modelProfile.thinkingLevel.auto")
  ).toBeVisible();
  expect(readModelDraft("saved-default-regression", 129)).toEqual(before);
  expect(api.getConversationModelPreferences).not.toHaveBeenCalled();
  expect(api.patchConversationModelPreferences).not.toHaveBeenCalled();
});

it("quick edits show the structured dependency error and retain server state", async () => {
  api.patchConversationModelPreferences.mockRejectedValue(
    new ApiError("PARAMETER_DEPENDENCY", "private details", {
      field: "/reasoning_effort",
    })
  );
  setup(766);
  const toggle = await screen.findByRole("switch");
  await waitFor(() => expect(toggle).toBeEnabled());
  fireEvent.click(toggle);
  expect(
    await screen.findByText("modelProfile.validation.dependency")
  ).toBeVisible();
  expect(toggle).not.toBeChecked();
  expect(
    screen.queryByText("modelProfile.preferencesConflict")
  ).not.toBeInTheDocument();
  expect(screen.queryByText("private details")).not.toBeInTheDocument();
});

it("advanced edits display the validation category and preserve explicit server zero on failure", async () => {
  api.patchConversationModelPreferences.mockRejectedValue(
    new ApiError("FIXED_PARAMETER", "private", { field: "/temperature" })
  );
  setup(766);
  const advanced = await screen.findByRole("button", {
    name: "workbench.controls.advanced",
  });
  await waitFor(() => expect(advanced).toBeEnabled());
  fireEvent.click(advanced);
  const input = await screen.findByRole("spinbutton", {
    name: "workbench.controls.temperature",
  });
  expect(input).toHaveValue(0);
  fireEvent.change(input, { target: { value: "0.5" } });
  fireEvent.blur(input);
  await waitFor(() =>
    expect(api.patchConversationModelPreferences).toHaveBeenCalledWith(
      766,
      129,
      { parameter_values: { temperature: 0.5 }, delete_parameters: [] }
    )
  );
  expect(
    (await screen.findAllByText("modelProfile.validation.fixed")).length
  ).toBeGreaterThan(0);
  expect(input).toHaveValue(0.5);
  const saved = await api.getConversationModelPreferences.mock.results[0].value;
  expect(saved.defaults.temperature).toBe(0);
  expect(saved.parameter_values).toEqual({});
});
