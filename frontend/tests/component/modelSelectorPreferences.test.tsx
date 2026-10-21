// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { readModelDraft } from "../../lib/conversationModelDrafts";
import { ModelSelector } from "../../app/[locale]/newchat/ui/model-selector";
import type {
  ConversationModelPreferenceView,
  ModelParameterRule,
} from "../../types/modelProfile";

const api = vi.hoisted(() => ({
  getModelOutlet: vi.fn(),
  getConversationModelPreferences: vi.fn(),
  patchConversationModelPreferences: vi.fn(),
}));
vi.mock("../../services/modelProfileService", () => api);
vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({ modelContext: () => ({ register: () => () => undefined }) }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const numeric = (key: string): ModelParameterRule => ({
  key,
  visible: true,
  editable: true,
  required: false,
  ui_group: "sampling",
  allowed_scopes: ["conversation"],
  schema: {
    type: "number",
    minimum: 0,
    maximum: key === "temperature" ? 2 : 1,
  },
});
let saved: ConversationModelPreferenceView;
beforeEach(() => {
  vi.clearAllMocks();
  saved = {
    version: 3,
    config_revision: 7,
    parameter_values: {},
    defaults: { temperature: 0.7, top_p: 1, enable_thinking: false },
    issues: [],
    field_specs: [
      numeric("temperature"),
      numeric("top_p"),
      {
        key: "enable_thinking",
        required: false,
        ui_group: "thinking",
        visible: true,
        editable: true,
        allowed_scopes: ["conversation"],
        schema: { type: "boolean" },
      },
    ],
  };
  api.getModelOutlet.mockImplementation(async () => ({
    config_revision: 7,
    profile: { parameter_values: saved.defaults },
    field_specs: saved.field_specs,
  }));
  api.getConversationModelPreferences.mockImplementation(async () =>
    structuredClone(saved)
  );
  api.patchConversationModelPreferences.mockImplementation(
    async (_cid, _mid, patch) => {
      saved.version++;
      saved.parameter_values = {
        ...saved.parameter_values,
        ...patch.parameter_values,
      };
      patch.delete_parameters.forEach(
        (key: string) => delete saved.parameter_values[key]
      );
    }
  );
});
function setup(conversationId: number | undefined) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <App>
        <ModelSelector
          conversationId={conversationId}
          parameterSettingsScopeKey="fresh-thread"
          defaultOpen
          models={[
            {
              id: "42",
              name: "Profile model",
              profileSchemaVersion: 1,
              agentParameterDefaults: { temperature: 0.5 },
            },
          ]}
          value="42"
        />
      </App>
    </QueryClientProvider>
  );
}
const temperatureName = "workbench.controls.temperature";
const advancedName = "workbench.controls.advanced";
async function openAdvanced() {
  if (!screen.queryByRole("button", { name: advancedName }))
    fireEvent.click(screen.getByRole("combobox"));
  const advanced = await screen.findByRole("button", { name: advancedName });
  await waitFor(() => expect(advanced).toBeEnabled());
  fireEvent.click(advanced);
  return screen.findByRole("spinbutton", { name: temperatureName });
}
async function changeSampling(name: string, value: string) {
  const field = await screen.findByRole("spinbutton", { name });
  await waitFor(() => expect(field).toBeEnabled());
  fireEvent.change(field, { target: { value } });
  fireEvent.blur(field);
}
it("UI-SESSION-15 reuses upstream sliders, persists native values and resets by deletion", async () => {
  setup(11);
  expect(
    screen.queryByRole("button", { name: "modelProfile.parameters" })
  ).not.toBeInTheDocument();
  const thinking = screen.getByRole("switch", {
    name: "chat.modelSelector.deepThinking",
  });
  await waitFor(() => expect(thinking).toBeEnabled());
  fireEvent.click(thinking);
  await waitFor(() => expect(thinking).toHaveAttribute("aria-checked", "true"));
  expect(await openAdvanced()).toHaveValue(0.5);
  expect(screen.getAllByRole("slider")).toHaveLength(2);
  await changeSampling(temperatureName, "0.31");
  await waitFor(() => expect(saved.parameter_values.temperature).toBe(0.31));
  await changeSampling("Top P", "0.72");
  await waitFor(() => expect(saved.parameter_values.top_p).toBe(0.72));
  expect(api.patchConversationModelPreferences).toHaveBeenLastCalledWith(
    11,
    42,
    {
      expected_version: 5,
      parameter_values: { temperature: 0.31, top_p: 0.72 },
      delete_parameters: [],
    }
  );
  const panel = await screen.findByRole("region", { name: advancedName });
  fireEvent.keyDown(panel, { key: "Escape" });
  expect(await openAdvanced()).toHaveValue(0.31);
  expect(screen.getByRole("spinbutton", { name: "Top P" })).toHaveValue(0.72);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "workbench.controls.restore" })
    ).toBeEnabled()
  );
  fireEvent.click(
    screen.getByRole("button", { name: "workbench.controls.restore" })
  );
  await waitFor(() =>
    expect(saved.parameter_values).toEqual({ enable_thinking: true })
  );
  expect(api.patchConversationModelPreferences).toHaveBeenLastCalledWith(
    11,
    42,
    {
      expected_version: 6,
      parameter_values: {},
      delete_parameters: ["temperature", "top_p"],
    }
  );
});
it("UI-SESSION-15 edits unsent conversation drafts without creating server preferences", async () => {
  setup(undefined);
  const thinking = screen.getByRole("switch", {
    name: "chat.modelSelector.deepThinking",
  });
  await waitFor(() => expect(thinking).toBeEnabled());
  fireEvent.click(thinking);
  await waitFor(() => expect(thinking).toHaveAttribute("aria-checked", "true"));
  expect(await openAdvanced()).toHaveValue(0.5);
  await changeSampling(temperatureName, "0.24");
  await waitFor(() =>
    expect(readModelDraft("fresh-thread", 42)).toEqual({
      enable_thinking: true,
      temperature: 0.24,
    })
  );
  fireEvent.keyDown(screen.getByRole("region", { name: advancedName }), {
    key: "Escape",
  });
  expect(await openAdvanced()).toHaveValue(0.24);
  expect(readModelDraft("another-thread", 42)).toEqual({});
  expect(readModelDraft("fresh-thread", 43)).toEqual({});
  expect(api.getConversationModelPreferences).not.toHaveBeenCalled();
  expect(api.patchConversationModelPreferences).not.toHaveBeenCalled();
});
it("UI-SESSION-15 keeps a failed quick save at the persisted state", async () => {
  api.patchConversationModelPreferences.mockRejectedValue(new Error("stale"));
  setup(11);
  const thinking = await screen.findByRole("switch", {
    name: "chat.modelSelector.deepThinking",
  });
  await waitFor(() => expect(thinking).toBeEnabled());
  fireEvent.click(thinking);
  await screen.findByText("modelProfile.preferencesFailed");
  expect(thinking).toHaveAttribute("aria-checked", "false");
  expect(api.patchConversationModelPreferences).toHaveBeenCalledTimes(1);
});

it("UI-SESSION-15 resets an effort by deletion and clears inactive reasoning when switched off", async () => {
  saved.defaults.enable_thinking = true;
  saved.defaults.reasoning_effort = "low";
  saved.parameter_values = { reasoning_effort: "high" };
  saved.field_specs.push({
    key: "reasoning_effort",
    visible: true,
    editable: true,
    required: false,
    ui_group: "thinking",
    allowed_scopes: ["conversation"],
    schema: { type: "string", enum: ["low", "high"] },
  });
  setup(11);
  const reset = await screen.findByRole("button", {
    name: "modelProfile.useInheritedDefault",
  });
  fireEvent.click(reset);
  await waitFor(() =>
    expect(api.patchConversationModelPreferences).toHaveBeenLastCalledWith(
      11,
      42,
      {
        expected_version: 3,
        parameter_values: {},
        delete_parameters: ["reasoning_effort"],
      }
    )
  );
  await waitFor(() =>
    expect(
      screen.getByRole("switch", { name: "chat.modelSelector.deepThinking" })
    ).toBeEnabled()
  );
  fireEvent.click(
    screen.getByRole("switch", { name: "chat.modelSelector.deepThinking" })
  );
  await waitFor(() =>
    expect(api.patchConversationModelPreferences).toHaveBeenLastCalledWith(
      11,
      42,
      {
        expected_version: 4,
        parameter_values: { enable_thinking: false },
        delete_parameters: ["reasoning_effort"],
      }
    )
  );
});

it("retains profile sampling bounds in the shared upstream control", async () => {
  saved.field_specs[0].schema = { type: "number", minimum: 0.1, maximum: 0.6 };
  setup(11);
  const field = await openAdvanced();
  expect(field).toHaveAttribute("min", "0.1");
  expect(field).toHaveAttribute("max", "0.6");
  fireEvent.change(field, { target: { value: "0.7" } });
  fireEvent.blur(field);
  expect(field).toHaveAttribute("aria-invalid", "true");
  expect(api.patchConversationModelPreferences).not.toHaveBeenCalled();
  fireEvent.change(field, { target: { value: "0.6" } });
  fireEvent.blur(field);
  await waitFor(() => expect(saved.parameter_values.temperature).toBe(0.6));
});
it("keeps a fixed sampling field read-only while other fields remain editable", async () => {
  saved.field_specs[0].editable = false;
  setup(11);
  expect(await openAdvanced()).toBeDisabled();
  expect(screen.getByRole("spinbutton", { name: "Top P" })).toBeEnabled();
  expect(api.patchConversationModelPreferences).not.toHaveBeenCalled();
});

it("SU-AC-03 keeps sampling inputs mounted while saved preferences refresh", async () => {
  setup(11);
  await openAdvanced();
  const topP = screen.getByRole("spinbutton", { name: "Top P" });
  let release: ((view: ConversationModelPreferenceView) => void) | undefined;
  api.getConversationModelPreferences.mockImplementationOnce(
    () =>
      new Promise<ConversationModelPreferenceView>((resolve) => {
        release = resolve;
      })
  );
  await changeSampling(temperatureName, "0.31");
  await waitFor(() => expect(release).toBeDefined());
  expect(screen.getByRole("spinbutton", { name: "Top P" })).toBe(topP);
  expect(topP).toBeDisabled();
  await act(async () => {
    release!(structuredClone(saved));
  });
  await changeSampling("Top P", "0.72");
  await waitFor(() =>
    expect(saved.parameter_values).toEqual({ temperature: 0.31, top_p: 0.72 })
  );
});
