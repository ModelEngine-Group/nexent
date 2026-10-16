// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { ApiError } from "../../services/api";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Dialog, DialogContent, DialogTitle } from "../../components/ui/dialog";
import { ModelOutletAddForm } from "../../app/[locale]/models/components/model/ModelOutletAddForm";

const api = vi.hoisted(() => ({
  listModelProfiles: vi.fn(),
  listProviderProfiles: vi.fn(),
  previewModelProfile: vi.fn(),
  createModelOutlet: vi.fn(),
  validateModelOutlet: vi.fn(),
}));
vi.mock("../../services/modelProfileService", () => api);
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const preview = {
  catalog_revision: "catalog-v1",
  selected: { model: null, provider: null },
  candidates: { models: [], providers: [] },
  parameter_values: {},
  field_specs: [],
  capabilities: {},
  instruction_mapping: {},
  conflicts: [],
};

function setup(inDialog = false) {
  const onDone = vi.fn();
  const onSuccess = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <App>
        {inDialog ? (
          <Dialog open>
            <DialogContent>
              <DialogTitle>Model onboarding</DialogTitle>
              <ModelOutletAddForm
                onDone={onDone}
                onSuccess={onSuccess}
                onPendingChange={vi.fn()}
              />
            </DialogContent>
          </Dialog>
        ) : (
          <ModelOutletAddForm
            onDone={onDone}
            onSuccess={onSuccess}
            onPendingChange={vi.fn()}
          />
        )}
      </App>
    </QueryClientProvider>
  );
  return { onDone, onSuccess };
}
function fillIdentity(name = "custom-model") {
  fireEvent.change(screen.getByLabelText("modelProfile.endpoint"), {
    target: { value: "https://models.invalid/v1" },
  });
  fireEvent.change(screen.getByLabelText("modelProfile.requestModel"), {
    target: { value: name },
  });
}
const saveButton = () =>
  screen.getByRole("button", { name: "modelProfile.saveAndCheck" });

beforeEach(() => {
  vi.clearAllMocks();
  Object.values(api).forEach((mock) => mock.mockReset());
  api.listModelProfiles.mockResolvedValue({
    items: [],
    total: 0,
    page: 1,
    page_size: 100,
    catalog_revision: "catalog-v1",
  });
  api.listProviderProfiles.mockResolvedValue({
    items: [],
    total: 0,
    page: 1,
    page_size: 100,
    catalog_revision: "catalog-v1",
  });
  api.previewModelProfile.mockResolvedValue(preview);
  api.createModelOutlet.mockResolvedValue({
    model_id: 42,
    config_revision: 1,
    profile: {},
    has_credential: true,
  });
  api.validateModelOutlet.mockResolvedValue({
    ok: true,
    error: null,
    check_scope: "connection_only",
    model_id: 42,
    config_revision: 1,
  });
});

describe("LLM outlet onboarding", () => {
  it("keeps credentials out of preview and checks the saved revision exactly once", async () => {
    const callbacks = setup();
    fillIdentity();
    fireEvent.change(screen.getByLabelText("modelProfile.apiKey"), {
      target: { value: "controlled-key" },
    });
    await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
    expect(JSON.stringify(api.previewModelProfile.mock.calls)).not.toContain(
      "controlled-key"
    );
    fireEvent.click(saveButton());
    await waitFor(() => expect(callbacks.onDone).toHaveBeenCalledOnce());
    expect(api.createModelOutlet).toHaveBeenCalledOnce();
    expect(api.createModelOutlet.mock.calls[0][0]).toMatchObject({
      request_model_id: "custom-model",
      catalog_revision: "catalog-v1",
      api_key: "controlled-key",
    });
    expect(api.validateModelOutlet).toHaveBeenCalledExactlyOnceWith({
      outlet_id: 42,
      expected_revision: 1,
    });
    expect(callbacks.onSuccess).toHaveBeenCalledWith({
      name: "custom-model",
      type: "llm",
      connectionChecked: true,
    });
  }, 15000);

  it("reports a failed check without creating a second saved outlet", async () => {
    api.validateModelOutlet.mockResolvedValue({
      ok: false,
      error: { category: "MODEL_AUTHENTICATION_ERROR" },
    });
    const callbacks = setup();
    fillIdentity();
    await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
    fireEvent.click(saveButton());
    await waitFor(() => expect(callbacks.onDone).toHaveBeenCalledOnce());
    expect(
      await screen.findByText("modelProfile.savedUnavailable")
    ).toBeVisible();
    expect(api.createModelOutlet).toHaveBeenCalledOnce();
  }, 15000);

  it("keeps incomplete custom parameter rows editable and prohibits saving them", async () => {
    setup();
    fillIdentity();
    await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
    fireEvent.click(screen.getByText("modelProfile.advanced"));
    fireEvent.click(
      screen.getByRole("button", { name: "modelProfile.addParameter" })
    );
    expect(saveButton()).toBeDisabled();
    expect(screen.getByText("modelProfile.extrasInvalid")).toBeVisible();
    expect(api.createModelOutlet).not.toHaveBeenCalled();
    fireEvent.change(
      screen.getByRole("textbox", { name: "modelProfile.parameterName 1" }),
      { target: { value: "custom_flag" } }
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: "modelProfile.parameterValue 1" }),
      { target: { value: "configured" } }
    );
    await waitFor(
      () =>
        expect(
          api.previewModelProfile.mock.calls.at(-1)?.[0].extra_api_parameters
        ).toEqual([{ path: "/custom_flag", value: "configured" }]),
      { timeout: 7000 }
    );
    await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
  }, 15000);

  it("does not save when composition or the version check fails", async () => {
    api.previewModelProfile.mockRejectedValue(
      new Error("MODEL_OUTLET_VERSION_CONFLICT")
    );
    const callbacks = setup();
    fillIdentity();
    await screen.findByText("modelProfile.previewFailed");
    expect(saveButton()).toBeDisabled();
    expect(api.createModelOutlet).not.toHaveBeenCalled();
    expect(callbacks.onDone).not.toHaveBeenCalled();
  }, 15000);

  it("ignores an obsolete preview while the latest model is still being checked", async () => {
    let resolveOld: (value: typeof preview) => void = () => {};
    let resolveNew: (value: typeof preview) => void = () => {};
    api.previewModelProfile.mockImplementation(
      (request) =>
        new Promise((resolve) => {
          if (request.request_model_id === "old-model") resolveOld = resolve;
          else resolveNew = resolve;
        })
    );
    const callbacks = setup();
    fillIdentity("old-model");
    await waitFor(
      () => expect(api.previewModelProfile).toHaveBeenCalledOnce(),
      { timeout: 7000 }
    );
    fillIdentity("new-model");
    await waitFor(
      () => expect(api.previewModelProfile).toHaveBeenCalledTimes(2),
      { timeout: 7000 }
    );
    expect(api.previewModelProfile.mock.calls[0][1].aborted).toBe(true);
    await act(async () => resolveOld(preview));
    expect(saveButton()).toBeDisabled();
    await act(async () => resolveNew(preview));
    await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
    fireEvent.click(saveButton());
    await waitFor(() => expect(callbacks.onDone).toHaveBeenCalledOnce());
    expect(api.createModelOutlet.mock.calls[0][0].request_model_id).toBe(
      "new-model"
    );
  }, 15000);

  it("preserves structured declared parameters including false and zero", async () => {
    api.previewModelProfile.mockResolvedValue({
      ...preview,
      parameter_values: { custom_options: { enabled: false } },
      field_specs: [
        {
          key: "custom_options",
          schema: { type: "object" },
          visible: true,
          editable: true,
          required: false,
          allowed_scopes: ["outlet"],
          ui_group: "advanced",
        },
      ],
    });
    const callbacks = setup();
    fillIdentity();
    await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
    fireEvent.click(screen.getByText("modelProfile.advanced"));
    fireEvent.change(screen.getByLabelText("custom_options"), {
      target: { value: '{"enabled":false,"retries":0}' },
    });
    await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
    fireEvent.click(saveButton());
    await waitFor(() => expect(callbacks.onDone).toHaveBeenCalledOnce());
    expect(api.createModelOutlet.mock.calls[0][0].parameter_values).toEqual({
      custom_options: { enabled: false, retries: 0 },
    });
  }, 15000);
});

it("keeps provider choices inside the modal and applies the selected endpoint", async () => {
  api.listProviderProfiles.mockResolvedValue({
    items: [
      {
        key: "alibaba-cn",
        name: "Alibaba (China)",
        revision: "r1",
        suggested_base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
      },
    ],
    total: 1,
    page: 1,
    page_size: 100,
    catalog_revision: "catalog-v1",
  });
  setup(true);
  await waitFor(() => expect(api.listProviderProfiles).toHaveBeenCalledOnce());
  fireEvent.mouseDown(screen.getByLabelText("modelProfile.provider"));
  const choice = await screen.findByText("Alibaba (China)");
  expect(screen.getByRole("dialog")).toContainElement(choice);
  fireEvent.click(choice);
  await waitFor(() =>
    expect(screen.getByLabelText("modelProfile.endpoint")).toHaveValue(
      "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
  );
}, 15000);

it("opens advanced settings for Other without rewriting the requested model ID", async () => {
  setup();
  fillIdentity("deployment-custom-id");
  await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
  fireEvent.mouseDown(screen.getByLabelText("modelProfile.modelProfile"));
  fireEvent.click(
    (await screen.findAllByText("modelProfile.otherProfile")).at(-1)!
  );
  expect(
    await screen.findByLabelText("modelProfile.extraParameters")
  ).toBeVisible();
  expect(screen.getByLabelText("modelProfile.requestModel")).toHaveValue(
    "deployment-custom-id"
  );
  await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
  fireEvent.click(saveButton());
  await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledOnce());
  expect(api.createModelOutlet.mock.calls[0][0]).toMatchObject({
    selection_mode: "manual",
    model_profile: null,
    request_model_id: "deployment-custom-id",
  });
}, 15000);

it("keeps a manually selected profile when the requested ID changes", async () => {
  api.listModelProfiles.mockResolvedValue({
    items: [{ key: "qwen/reference", name: "Qwen Reference", revision: "m1" }],
  });
  setup();
  fillIdentity("qwen-reference");
  await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
  fireEvent.mouseDown(screen.getByLabelText("modelProfile.modelProfile"));
  fireEvent.click((await screen.findAllByText("Qwen Reference")).at(-1)!);
  fillIdentity("deployment-2");
  await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
  fireEvent.click(saveButton());
  await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledOnce());
  expect(api.createModelOutlet.mock.calls[0][0]).toMatchObject({
    model_profile: { key: "qwen/reference", revision: "m1" },
    request_model_id: "deployment-2",
  });
}, 15000);

it("keeps an unchanged batch draft ready when its parent recreates equivalent connection values", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const onApply = vi.fn();
  const form = () => (
    <QueryClientProvider client={client}>
      <App>
        <ModelOutletAddForm
          configuration={{
            draft: {
              request_model_id: "custom-model",
              provider_info: { base_url: "https://models.invalid/v1" },
            },
            onApply,
          }}
          onDone={vi.fn()}
          onSuccess={vi.fn()}
          onPendingChange={vi.fn()}
        />
      </App>
    </QueryClientProvider>
  );
  const view = render(form());
  await waitFor(
    () =>
      expect(screen.getByRole("button", { name: "common.save" })).toBeEnabled(),
    { timeout: 7000 }
  );
  view.rerender(form());
  expect(screen.getByRole("button", { name: "common.save" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "common.save" }));
  await waitFor(() => expect(onApply).toHaveBeenCalledOnce());
  expect(api.createModelOutlet).not.toHaveBeenCalled();
}, 15000);

it("suggests qwen3.8, exposes thinking controls and keeps capacity settings to two inputs", async () => {
  api.listModelProfiles.mockResolvedValue({
    items: [
      {
        key: "alibaba/qwen3.8-27b",
        name: "Qwen3.8 27B",
        revision: "r1",
        catalog_kind: "model",
        qualification: "reference_only",
      },
    ],
    total: 1,
  });
  api.previewModelProfile.mockImplementation(async (draft) => ({
    ...preview,
    selected: { model: "alibaba/qwen3.8-27b", provider: null },
    parameter_values: draft.parameter_values,
    field_specs:
      draft.thinking_control !== "profile_default"
        ? [
            {
              key: "enable_thinking",
              schema: { type: "boolean" },
              visible: true,
              editable: true,
              required: false,
              allowed_scopes: ["outlet", "conversation"],
              ui_group: "reasoning",
            },
          ]
        : [],
  }));
  setup();
  fillIdentity("qwen3.8");
  await waitFor(() =>
    expect(
      api.previewModelProfile.mock.calls.at(-1)?.[0].model_profile
    ).toEqual({ key: "alibaba/qwen3.8-27b", revision: "r1" })
  );
  expect(screen.getByText("modelProfile.approximateMatch")).toBeVisible();
  fireEvent.click(screen.getByText("modelProfile.advanced"));
  expect(
    screen.queryByText("modelProfile.input_limit")
  ).not.toBeInTheDocument();
  expect(
    screen.queryByText("modelProfile.outputReserve")
  ).not.toBeInTheDocument();
  expect(screen.queryByText("modelProfile.tokenizer")).not.toBeInTheDocument();
  expect(
    screen.getByRole("spinbutton", { name: "modelProfile.maximumOutput" })
  ).toBeVisible();
  expect(
    screen.queryByRole("combobox", { name: "modelProfile.thinkingMode" })
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("switch", { name: "modelProfile.thinkingToggle" })
  );
  await screen.findByRole("combobox", { name: "modelProfile.thinkingMode" });
  fireEvent.mouseDown(
    screen.getByRole("combobox", { name: "modelProfile.thinkingMode" })
  );
  fireEvent.click(
    await screen.findByText("modelProfile.thinkingModeOption.effort")
  );
  fireEvent.mouseDown(
    screen.getByRole("combobox", { name: "modelProfile.thinkingDegree" })
  );
  fireEvent.click(await screen.findByText("medium"));
  await waitFor(
    () =>
      expect(api.previewModelProfile.mock.calls.at(-1)?.[0]).toMatchObject({
        thinking_mode: "effort",
        parameter_values: { enable_thinking: true, reasoning_effort: "medium" },
      }),
    { timeout: 7000 }
  );
  fireEvent.click(
    screen.getByRole("switch", { name: "modelProfile.thinkingToggle" })
  );
  expect(
    screen.queryByRole("combobox", { name: "modelProfile.thinkingMode" })
  ).not.toBeInTheDocument();
  await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
  fireEvent.click(saveButton());
  await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledOnce());
  expect(api.createModelOutlet.mock.calls[0][0]).toMatchObject({
    thinking_control: "enable_thinking",
    thinking_mode: "effort",
    parameter_values: { enable_thinking: false },
  });
}, 15000);

it("offers Top P as an explicit numeric value without creating a default", async () => {
  api.previewModelProfile.mockResolvedValue({
    ...preview,
    field_specs: [
      {
        key: "top_p",
        visible: true,
        editable: true,
        allowed_scopes: ["outlet", "conversation"],
        ui_group: "advanced",
        schema: { type: ["number", "null"], minimum: 0, maximum: 1 },
      },
    ],
  });
  const callbacks = setup();
  fillIdentity();
  fireEvent.click(screen.getByText("modelProfile.advanced"));
  const field = await screen.findByRole(
    "spinbutton",
    { name: "top_p" },
    { timeout: 7000 }
  );
  expect(field).toHaveValue("");
  expect(field).toHaveAttribute("aria-valuemin", "0");
  expect(field).toHaveAttribute("aria-valuemax", "1");
  fireEvent.change(field, { target: { value: "0.85" } });
  await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
  fireEvent.click(saveButton());
  await waitFor(() => expect(callbacks.onDone).toHaveBeenCalledOnce());
  expect(api.createModelOutlet.mock.calls[0][0].parameter_values.top_p).toBe(
    0.85
  );
}, 15000);

it("refreshes stale profile revisions without discarding a batch draft's configuration", async () => {
  const atom = {
    key: "deepseek/deepseek-v4-pro",
    name: "DeepSeek V4 Pro",
    revision: "old",
  };
  api.listModelProfiles
    .mockResolvedValueOnce({ items: [atom] })
    .mockResolvedValue({ items: [{ ...atom, revision: "new" }] });
  api.previewModelProfile.mockImplementation(async (draft) => {
    if (draft.model_profile?.revision === "old")
      throw new ApiError(409, "MODEL_OUTLET_VERSION_CONFLICT");
    return { ...preview, parameter_values: draft.parameter_values };
  });
  const onApply = vi.fn();
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <App>
        <ModelOutletAddForm
          configuration={{
            draft: {
              selection_mode: "manual",
              request_model_id: "route/deepseek-v4-pro",
              display_name: "My model",
              provider_info: { base_url: "https://models.invalid/v1" },
              model_profile: { key: atom.key, revision: "old" },
              parameter_values: { temperature: 0.4, enable_thinking: false },
              thinking_control: "enable_thinking",
              context_limits: { combined_window: 200000 },
            },
            onApply,
          }}
          onDone={vi.fn()}
          onSuccess={vi.fn()}
          onPendingChange={vi.fn()}
        />
      </App>
    </QueryClientProvider>
  );
  await screen.findByText("modelProfile.catalogChanged");
  expect(screen.getByRole("alert")).not.toHaveClass("ant-alert");
  expect(
    screen.queryByText("modelProfile.catalogChangedDetail")
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "modelProfile.refreshCatalog" })
  );
  const apply = screen.getByRole("button", { name: "common.save" });
  await waitFor(() => expect(apply).toBeEnabled(), { timeout: 7000 });
  fireEvent.click(apply);
  await waitFor(() => expect(onApply).toHaveBeenCalledOnce());
  expect(onApply.mock.calls[0][0]).toMatchObject({
    model_profile: { key: atom.key, revision: "new" },
    request_model_id: "route/deepseek-v4-pro",
    display_name: "My model",
    parameter_values: { temperature: 0.4, enable_thinking: false },
    thinking_control: "enable_thinking",
    context_limits: { combined_window: 200000 },
  });
}, 15000);

it("edits output capability without adding a request output parameter", async () => {
  api.previewModelProfile.mockImplementation(async (draft) => ({
    ...preview,
    capabilities: {
      context: { combined_window: 1000000, output_limit: 384000 },
    },
    parameter_values: draft.parameter_values,
  }));
  setup();
  fillIdentity();
  await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
  fireEvent.click(screen.getByText("modelProfile.advanced"));
  const output = screen.getByRole("spinbutton", {
    name: "modelProfile.maximumOutput",
  });
  expect(output).toHaveValue("384000");
  expect(
    api.previewModelProfile.mock.calls.at(-1)?.[0].parameter_values
  ).not.toHaveProperty("max_output_tokens");
  fireEvent.change(output, { target: { value: "8192" } });
  await waitFor(
    () =>
      expect(
        api.previewModelProfile.mock.calls.at(-1)?.[0].context_limits
      ).toHaveProperty("output_limit", 8192),
    { timeout: 7000 }
  );
  expect(
    api.previewModelProfile.mock.calls.at(-1)?.[0].parameter_values
  ).not.toHaveProperty("max_output_tokens");
}, 15000);

it("retries a failed preview without clearing the requested model", async () => {
  api.previewModelProfile
    .mockRejectedValueOnce(new ApiError("request_failed", "Connection error"))
    .mockResolvedValue(preview);
  setup();
  fillIdentity("deepseek-v4-pro");
  await screen.findByText("modelProfile.previewFailed");
  expect(saveButton()).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "modelProfile.retryPreview" })
  );
  await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
  expect(screen.getByLabelText("modelProfile.requestModel")).toHaveValue(
    "deepseek-v4-pro"
  );
}, 15000);

it("shows experience defaults in the draft before the user makes an explicit change", async () => {
  api.previewModelProfile.mockImplementation(async (draft) => ({
    ...preview,
    parameter_values: { temperature: 0.6, ...draft.parameter_values },
    field_specs: [
      {
        key: "temperature",
        schema: { type: "number", minimum: 0, maximum: 2 },
        visible: true,
        editable: true,
        required: false,
        allowed_scopes: ["outlet"],
        ui_group: "sampling",
        default_value: 0.6,
      },
    ],
  }));
  setup();
  fillIdentity();
  await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
  fireEvent.click(screen.getByText("modelProfile.advanced"));
  const temperature = screen.getByRole("spinbutton", { name: "temperature" });
  expect(temperature).toHaveValue("0.6");
  expect(
    api.previewModelProfile.mock.calls.at(-1)?.[0].parameter_values
  ).not.toHaveProperty("temperature");
  fireEvent.change(temperature, { target: { value: "0.9" } });
  await waitFor(
    () =>
      expect(
        api.previewModelProfile.mock.calls.at(-1)?.[0].parameter_values
          .temperature
      ).toBe(0.9),
    { timeout: 7000 }
  );
  await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
  fireEvent.click(saveButton());
  await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledOnce());
  expect(
    api.createModelOutlet.mock.calls[0][0].parameter_values.temperature
  ).toBe(0.9);
  expect(api.createModelOutlet.mock.invocationCallOrder[0]).toBeLessThan(
    api.validateModelOutlet.mock.invocationCallOrder[0]
  );
}, 15000);

it("shows model-only defaults immediately and composes provider values after the endpoint is supplied", async () => {
  const configuration = {
    capabilities: {
      context: { combined_window: 200000, output_limit: 16000 },
      reasoning: { status: "supported" },
    },
    parameter_values: { temperature: 0.2, enable_thinking: true },
    field_specs: [
      {
        key: "temperature",
        schema: { type: "number" },
        visible: true,
        editable: true,
        required: false,
        allowed_scopes: ["outlet"],
        ui_group: "sampling",
      },
      {
        key: "enable_thinking",
        schema: { type: "boolean" },
        visible: true,
        editable: true,
        required: false,
        allowed_scopes: ["outlet"],
        ui_group: "reasoning",
      },
    ],
  };
  api.listModelProfiles.mockResolvedValue({
    items: [
      {
        key: "alibaba/qwen3.7-max",
        name: "Qwen3.7 Max",
        revision: "r1",
        configuration,
      },
    ],
  });
  api.previewModelProfile.mockResolvedValue({
    ...preview,
    ...configuration,
    parameter_values: { temperature: 0.6, enable_thinking: true },
  });
  setup();
  fireEvent.change(screen.getByLabelText("modelProfile.requestModel"), {
    target: { value: "qwen3.7" },
  });
  fireEvent.click(screen.getByText("modelProfile.advanced"));
  await waitFor(() =>
    expect(
      screen.getByRole("spinbutton", { name: "modelProfile.combined_window" })
    ).toHaveValue("200000")
  );
  expect(
    screen.getByRole("spinbutton", { name: "modelProfile.maximumOutput" })
  ).toHaveValue("16000");
  expect(screen.getByRole("spinbutton", { name: "temperature" })).toHaveValue(
    "0.2"
  );
  expect(
    screen.getByRole("switch", { name: "modelProfile.thinkingToggle" })
  ).toHaveAttribute("aria-checked", "true");
  expect(api.previewModelProfile).not.toHaveBeenCalled();
  expect(saveButton()).toBeDisabled();
  fireEvent.change(screen.getByLabelText("modelProfile.endpoint"), {
    target: { value: "https://models.invalid/v1" },
  });
  await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
  expect(screen.getByRole("spinbutton", { name: "temperature" })).toHaveValue(
    "0.6"
  );
}, 15000);

it("does not retain another model's composed capabilities after clearing the endpoint", async () => {
  const configuration = (output: number) => ({
    capabilities: { context: { output_limit: output } },
    field_specs: [],
    parameter_values: {},
  });
  api.listModelProfiles.mockResolvedValue({
    items: [
      {
        key: "fixture/model-a",
        name: "Model A",
        revision: "a",
        configuration: configuration(16000),
      },
      {
        key: "fixture/model-b",
        name: "Model B",
        revision: "b",
        configuration: configuration(8000),
      },
    ],
  });
  api.previewModelProfile.mockResolvedValue({
    ...preview,
    ...configuration(32000),
  });
  setup();
  fillIdentity("model-a");
  await waitFor(() => expect(saveButton()).toBeEnabled(), { timeout: 7000 });
  fireEvent.click(screen.getByText("modelProfile.advanced"));
  expect(
    screen.getByRole("spinbutton", { name: "modelProfile.maximumOutput" })
  ).toHaveValue("32000");
  fireEvent.change(screen.getByLabelText("modelProfile.endpoint"), {
    target: { value: "" },
  });
  fireEvent.change(screen.getByLabelText("modelProfile.requestModel"), {
    target: { value: "model-b" },
  });
  expect(
    screen.getByRole("spinbutton", { name: "modelProfile.maximumOutput" })
  ).toHaveValue("8000");
  expect(saveButton()).toBeDisabled();
}, 15000);
