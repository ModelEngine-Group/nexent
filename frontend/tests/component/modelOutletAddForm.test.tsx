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
const translate = vi.hoisted(() =>
  vi.fn((key: string, _options?: unknown) => key)
);
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: translate }) }));

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
  const view = render(
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
  return { onDone, onSuccess, unmount: view.unmount };
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
  screen.getByRole("button", { name: "modelConfig.addDialog.submit" });

async function waitForSaveReady() {
  // Resolve once: repeated role queries recalculate every AntD node's style
  // and can starve the debounce timer in jsdom. Keep the state assertion real.
  const button = saveButton();
  await waitFor(() => expect(button).toBeEnabled(), { timeout: 7000 });
}

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
  it("S-01 keeps credentials out of preview and completes without an automatic probe", async () => {
    const callbacks = setup();
    fillIdentity();
    fireEvent.change(screen.getByLabelText("modelProfile.apiKey"), {
      target: { value: "controlled-key" },
    });
    await waitForSaveReady();
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
      authentication_scheme: "bearer_token_v1",
    });
    expect(api.validateModelOutlet).not.toHaveBeenCalled();
    expect(translate).toHaveBeenCalledWith(
      "modelConfig.addDialog.batchSuccess",
      { count: 1, created: 1 }
    );
    expect(callbacks.onSuccess).toHaveBeenCalledWith({
      name: "custom-model",
      type: "llm",
    });
  }, 15000);

  it("UI-AUTH-11 saves an empty optional key without Bearer authentication", async () => {
    setup();
    fillIdentity();
    expect(screen.queryByText("modelProfile.noAuth")).not.toBeInTheDocument();
    await waitForSaveReady();
    fireEvent.click(saveButton());
    await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledOnce());
    expect(api.createModelOutlet.mock.calls[0][0]).toMatchObject({
      api_key: null,
      authentication_scheme: "no_auth_v1",
    });
  }, 15000);

  it("UI-TLS-12 verifies TLS by default and skips it only when enabled", async () => {
    setup();
    fillIdentity();
    fireEvent.click(screen.getByText("modelProfile.advanced"));
    const toggle = screen.getByRole("switch", {
      name: "modelProfile.skipTlsVerify",
    });
    expect(toggle).not.toBeChecked();
    await waitForSaveReady();
    expect(
      api.previewModelProfile.mock.lastCall?.[0].provider_info.ssl_verify
    ).toBe(true);
    fireEvent.click(toggle);
    await waitForSaveReady();
    fireEvent.click(saveButton());
    await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledOnce());
    expect(
      api.createModelOutlet.mock.calls[0][0].provider_info.ssl_verify
    ).toBe(false);
  }, 15000);

  it("S-01 closes after save even when the unused probe would never finish", async () => {
    api.validateModelOutlet.mockImplementation(() => new Promise(() => {}));
    const callbacks = setup();
    fillIdentity();
    await waitForSaveReady();
    fireEvent.click(saveButton());
    await waitFor(() => expect(callbacks.onDone).toHaveBeenCalledOnce());
    expect(api.createModelOutlet).toHaveBeenCalledOnce();
    expect(api.validateModelOutlet).not.toHaveBeenCalled();
    expect(screen.queryByText("modelProfile.layout.checkAfterSave")).toBeNull();
  }, 15000);

  it("S-04 retains the form and retries a failed save without probing", async () => {
    api.createModelOutlet.mockRejectedValueOnce(
      new Error("controlled save failure")
    );
    const callbacks = setup();
    fillIdentity();
    await waitForSaveReady();
    fireEvent.click(saveButton());
    await screen.findByText("modelProfile.saveFailed");
    expect(callbacks.onDone).not.toHaveBeenCalled();
    expect(screen.getByLabelText("modelProfile.requestModel")).toHaveValue(
      "custom-model"
    );
    fireEvent.click(saveButton());
    await waitFor(() => expect(callbacks.onDone).toHaveBeenCalledOnce());
    expect(api.createModelOutlet).toHaveBeenCalledTimes(2);
    expect(api.validateModelOutlet).not.toHaveBeenCalled();
  }, 15000);

  it("keeps incomplete custom parameter rows editable and prohibits saving them", async () => {
    setup();
    fillIdentity();
    await waitForSaveReady();
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
    await waitForSaveReady();
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
    await waitForSaveReady();
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
    await waitForSaveReady();
    fireEvent.click(screen.getByText("modelProfile.advanced"));
    fireEvent.change(screen.getByLabelText("custom_options"), {
      target: { value: '{"enabled":false,"retries":0}' },
    });
    await waitForSaveReady();
    fireEvent.click(saveButton());
    await waitFor(() => expect(callbacks.onDone).toHaveBeenCalledOnce());
    expect(api.createModelOutlet.mock.calls[0][0].parameter_values).toEqual({
      custom_options: { enabled: false, retries: 0 },
      temperature: 0.7,
      top_p: 1,
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
  await waitForSaveReady();
  fireEvent.mouseDown(screen.getByLabelText("modelProfile.modelProfile"));
  fireEvent.click(
    await screen.findByText("modelProfile.otherProfile", {
      selector: ".ant-select-item-option-content",
    })
  );
  expect(
    await screen.findByLabelText("modelProfile.extraParameters")
  ).toBeVisible();
  expect(screen.getByLabelText("modelProfile.requestModel")).toHaveValue(
    "deployment-custom-id"
  );
  await waitForSaveReady();
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
  await waitForSaveReady();
  fireEvent.mouseDown(screen.getByLabelText("modelProfile.modelProfile"));
  fireEvent.click(
    await screen.findByText("Qwen Reference", {
      selector: ".ant-select-item-option-content",
    })
  );
  fillIdentity("deployment-2");
  await waitForSaveReady();
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
  expect(
    screen.queryByRole("button", {
      name: "modelConfig.editDialog.checkConnectivity",
    })
  ).not.toBeInTheDocument();
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
  await waitFor(
    () =>
      expect(api.previewModelProfile.mock.calls.at(-1)?.[0]).toMatchObject({
        thinking_mode: "effort",
        parameter_values: { enable_thinking: true, reasoning_effort: "low" },
      }),
    { timeout: 7000 }
  );
  fireEvent.mouseDown(
    screen.getByRole("combobox", { name: "modelProfile.thinkingDegree" })
  );
  fireEvent.click(await screen.findByText("modelProfile.thinkingLevel.medium"));
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
  await waitForSaveReady();
  fireEvent.click(saveButton());
  await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledOnce());
  expect(api.createModelOutlet.mock.calls[0][0]).toMatchObject({
    thinking_control: "enable_thinking",
    thinking_mode: "effort",
    parameter_values: { enable_thinking: false },
  });
}, 30000);

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
  expect(field).toHaveValue("1");
  expect(field).toHaveAttribute("aria-valuemin", "0");
  expect(field).toHaveAttribute("aria-valuemax", "1");
  fireEvent.change(field, { target: { value: "0.85" } });
  await waitForSaveReady();
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
  await waitForSaveReady();
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
  await waitForSaveReady();
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
  await waitForSaveReady();
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
  await waitForSaveReady();
  fireEvent.click(saveButton());
  await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledOnce());
  expect(
    api.createModelOutlet.mock.calls[0][0].parameter_values.temperature
  ).toBe(0.9);
  expect(api.validateModelOutlet).not.toHaveBeenCalled();
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
  api.previewModelProfile.mockImplementation(async (request) => ({
    ...preview,
    ...configuration,
    parameter_values: {
      temperature: request.provider_info.base_url ? 0.6 : 0.2,
      enable_thinking: true,
    },
  }));
  setup();
  fireEvent.change(screen.getByLabelText("modelProfile.requestModel"), {
    target: { value: "qwen3.7" },
  });
  fireEvent.click(screen.getByText("modelProfile.advanced"));
  await waitFor(
    () =>
      expect(
        screen.getByRole("spinbutton", { name: "modelProfile.combined_window" })
      ).toHaveValue("200000"),
    { timeout: 7000 }
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
  expect(api.previewModelProfile).toHaveBeenCalled();
  expect(saveButton()).toBeDisabled();
  fireEvent.change(screen.getByLabelText("modelProfile.endpoint"), {
    target: { value: "https://models.invalid/v1" },
  });
  await waitForSaveReady();
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
  api.previewModelProfile.mockImplementation(async (request) => ({
    ...preview,
    ...configuration(
      request.request_model_id === "model-b" && !request.provider_info.base_url
        ? 8000
        : 32000
    ),
  }));
  setup();
  fillIdentity("model-a");
  await waitForSaveReady();
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
  await waitFor(
    () =>
      expect(
        screen.getByRole("spinbutton", { name: "modelProfile.maximumOutput" })
      ).toHaveValue("8000"),
    { timeout: 5000 }
  );
  expect(saveButton()).toBeDisabled();
}, 15000);

it("UI-LAYOUT-03 keeps the parameter panel visible and restores only model overrides", async () => {
  const config = {
    ...preview,
    capabilities: { context: { combined_window: 200000, output_limit: 16000 } },
    parameter_values: { temperature: 0.4 },
    field_specs: [
      {
        key: "temperature",
        schema: { type: "number" },
        visible: true,
        editable: true,
        allowed_scopes: ["outlet"],
        ui_group: "sampling",
      },
    ],
  };
  api.previewModelProfile.mockImplementation(async (draft) => ({
    ...config,
    parameter_values: { ...config.parameter_values, ...draft.parameter_values },
  }));
  setup();
  expect(screen.getByText("modelProfile.layout.emptyTitle")).toBeVisible();
  expect(
    screen.queryByRole("spinbutton", { name: "temperature" })
  ).not.toBeInTheDocument();
  fillIdentity();
  await waitForSaveReady();
  expect(screen.getByRole("spinbutton", { name: "temperature" })).toBeVisible();
  // Model parameters are available without opening connection settings.
  expect(
    screen.queryByLabelText("modelProfile.extraParameters")
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("spinbutton", { name: "temperature" }), {
    target: { value: "0.9" },
  });
  fireEvent.change(
    screen.getByRole("spinbutton", { name: "modelProfile.combined_window" }),
    { target: { value: "100000" } }
  );
  await waitFor(() =>
    expect(
      api.previewModelProfile.mock.calls.at(-1)?.[0].parameter_values
        .temperature
    ).toBe(0.9)
  );
  fireEvent.click(
    screen.getByRole("button", { name: "modelProfile.layout.reset" })
  );
  await waitFor(() =>
    expect(api.previewModelProfile.mock.calls.at(-1)?.[0]).toMatchObject({
      parameter_values: {},
      context_limits: {},
      provider_info: { base_url: "https://models.invalid/v1" },
    })
  );
  await waitFor(
    () =>
      expect(
        screen.getByRole("spinbutton", { name: "temperature" })
      ).toHaveValue("0.4"),
    { timeout: 7000 }
  );
  expect(
    screen.getByRole("spinbutton", { name: "modelProfile.combined_window" })
  ).toHaveValue("200000");
}, 15000);

it("S-04 freezes connection identity only while saving", async () => {
  let finishCheck!: (value: {
    model_id: number;
    config_revision: number;
  }) => void;
  api.createModelOutlet.mockImplementation(
    () =>
      new Promise((resolve) => {
        finishCheck = resolve;
      })
  );
  const callbacks = setup();
  fillIdentity();
  await waitForSaveReady();
  fireEvent.click(saveButton());
  await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledOnce());
  for (const label of [
    "modelProfile.provider",
    "modelProfile.endpoint",
    "modelProfile.requestModel",
    "modelProfile.apiKey",
  ])
    expect(screen.getByLabelText(label)).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "modelProfile.layout.reset" })
  ).toBeDisabled();
  await act(async () => finishCheck({ model_id: 42, config_revision: 1 }));
  await waitFor(() => expect(callbacks.onDone).toHaveBeenCalledOnce());
}, 20000);

it.each([false, true])(
  "AC-FIX-09 prefills fallback sampling while asking for an unmatched/ambiguous profile (%s)",
  async (ambiguous) => {
    const candidates = ambiguous
      ? ["vendor-one/model-one", "vendor-two/model-two"]
      : [];
    api.listModelProfiles.mockResolvedValue({
      items: candidates.map((key) => ({ key, name: key, revision: "r1" })),
      total: candidates.length,
      catalog_revision: "catalog-v1",
    });
    api.previewModelProfile.mockResolvedValue({
      ...preview,
      matched_profile: false,
      candidates: { models: candidates, providers: [] },
    });
    setup();
    fillIdentity("custom-shared-model");
    await waitForSaveReady();
    expect(screen.getByText("modelProfile.chooseProfile")).toBeVisible();
    fireEvent.click(screen.getByText("modelProfile.advanced"));
    expect(screen.getByRole("spinbutton", { name: "temperature" })).toHaveValue(
      "0.7"
    );
    expect(screen.getByRole("spinbutton", { name: "top_p" })).toHaveValue("1");
    fireEvent.click(saveButton());
    await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledOnce());
    expect(
      api.createModelOutlet.mock.calls[0][0].parameter_values
    ).toMatchObject({ temperature: 0.7, top_p: 1 });
    expect(api.createModelOutlet.mock.calls[0][0].model_profile).toBeNull();
  },
  15000
);

it("D-03 preserves single duplicate input and distinguishes stale revisions", async () => {
  api.createModelOutlet.mockRejectedValueOnce(
    new ApiError("MODEL_DISPLAY_NAME_CONFLICT", "duplicate")
  );
  const callbacks = setup();
  fillIdentity();
  await waitForSaveReady();
  fireEvent.click(saveButton());
  await screen.findByText("modelProfile.displayNameConflict");
  expect(callbacks.onDone).not.toHaveBeenCalled();
  expect(screen.getByLabelText("modelProfile.requestModel")).toHaveValue(
    "custom-model"
  );
  api.createModelOutlet.mockRejectedValueOnce(
    new ApiError(409, "MODEL_OUTLET_VERSION_CONFLICT")
  );
  fireEvent.click(saveButton());
  await screen.findByText("modelProfile.saveFailed");
  expect(callbacks.onDone).not.toHaveBeenCalled();
  expect(api.validateModelOutlet).not.toHaveBeenCalled();
}, 15000);

function manualPreviewConfiguration() {
  const rule = (
    key: string,
    schema: Record<string, unknown>,
    ui_group: string
  ) => ({
    key,
    schema,
    ui_group,
    visible: true,
    editable: true,
    required: false,
    allowed_scopes: ["outlet"],
  });
  const configuration = {
    capabilities: { context: { combined_window: 200000, output_limit: 16000 } },
    parameter_values: { temperature: 0.2, top_p: 0.9, enable_thinking: false },
    field_specs: [
      rule("temperature", { type: "number" }, "sampling"),
      rule("top_p", { type: "number", minimum: 0, maximum: 1 }, "sampling"),
      rule("enable_thinking", { type: "boolean" }, "reasoning"),
      rule(
        "reasoning_budget_tokens",
        { type: "integer", minimum: 1, maximum: 16000 },
        "reasoning"
      ),
    ],
  };
  api.listModelProfiles.mockResolvedValue({
    items: [
      {
        key: "alibaba/qwen-reference",
        name: "Manual Qwen",
        revision: "m1",
        configuration,
      },
      {
        key: "deepseek/deepseek-v4-flash",
        name: "DeepSeek V4 Flash",
        revision: "m2",
        configuration,
      },
    ],
  });
  api.previewModelProfile.mockImplementation(async (request) => ({
    ...preview,
    ...configuration,
    parameter_values: request.request_model_id
      ? { temperature: 0.6, top_p: 1, enable_thinking: false }
      : configuration.parameter_values,
  }));
}
async function selectManualPreviewProfile() {
  fireEvent.mouseDown(screen.getByLabelText("modelProfile.modelProfile"));
  fireEvent.click(
    await screen.findByText("Manual Qwen", {
      selector: ".ant-select-item-option-content",
    })
  );
}

it.each([false, true])(
  "MP-01/02 profile-first display and edits survive name changes (endpoint first: %s)",
  async (endpointFirst) => {
    manualPreviewConfiguration();
    setup();
    expect(
      screen.getByText("modelProfile.layout.emptyTitle")
    ).toBeInTheDocument();
    if (endpointFirst)
      fireEvent.change(screen.getByLabelText("modelProfile.endpoint"), {
        target: { value: "https://models.invalid/v1" },
      });
    await selectManualPreviewProfile();
    const temperature = await screen.findByRole("spinbutton", {
      name: "temperature",
    });
    await waitFor(() => expect(temperature).toHaveValue("0.2"), {
      timeout: 5000,
    });
    expect(
      screen.queryByText("modelProfile.layout.emptyTitle")
    ).not.toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
    expect(api.previewModelProfile).toHaveBeenCalled();
    fireEvent.change(temperature, { target: { value: "0.35" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: "top_p" }), {
      target: { value: "0.83" },
    });
    fireEvent.change(
      screen.getByRole("spinbutton", { name: "modelProfile.maximumOutput" }),
      { target: { value: "8000" } }
    );
    fireEvent.click(
      screen.getByRole("switch", { name: "modelProfile.thinkingToggle" })
    );
    fireEvent.change(
      await screen.findByRole("spinbutton", {
        name: "modelProfile.thinkingDegree",
      }),
      { target: { value: "1300" } }
    );
    fillIdentity("first-deployment");
    await waitForSaveReady();
    fireEvent.change(screen.getByLabelText("modelProfile.requestModel"), {
      target: { value: "" },
    });
    await waitFor(() => expect(saveButton()).toBeDisabled());
    expect(screen.getByRole("spinbutton", { name: "temperature" })).toHaveValue(
      "0.35"
    );
    fillIdentity("deepseek-v4-flash");
    await waitForSaveReady();
    expect(screen.getByRole("spinbutton", { name: "temperature" })).toHaveValue(
      "0.35"
    );
    expect(
      screen.getByRole("spinbutton", { name: "modelProfile.maximumOutput" })
    ).toHaveValue("8000");
    fireEvent.click(saveButton());
    await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledOnce());
    expect(api.createModelOutlet.mock.calls[0][0]).toMatchObject({
      model_profile: { key: "alibaba/qwen-reference", revision: "m1" },
      request_model_id: "deepseek-v4-flash",
      parameter_values: {
        temperature: 0.35,
        top_p: 0.83,
        enable_thinking: true,
        reasoning_budget_tokens: 1300,
      },
      context_limits: { output_limit: 8000 },
    });
    expect(api.validateModelOutlet).not.toHaveBeenCalled();
  },
  15000
);

it("MP-03 prefills thinking before model identity is available even with an endpoint", async () => {
  manualPreviewConfiguration();
  setup();
  fireEvent.change(screen.getByLabelText("modelProfile.endpoint"), {
    target: { value: "https://models.invalid/v1" },
  });
  await selectManualPreviewProfile();
  await waitFor(
    () =>
      expect(
        screen.getByRole("spinbutton", { name: "temperature" })
      ).toHaveValue("0.2"),
    { timeout: 5000 }
  );
  fireEvent.click(
    await screen.findByRole("switch", { name: "modelProfile.thinkingToggle" })
  );
  await waitFor(
    () =>
      expect(
        screen.getByRole("spinbutton", {
          name: "modelProfile.thinkingDegree",
        })
      ).toHaveValue("8000"),
    { timeout: 5000 }
  );
  fireEvent.change(screen.getByLabelText("modelProfile.requestModel"), {
    target: { value: "deployment" },
  });
  await waitForSaveReady();
  expect(
    api.previewModelProfile.mock.calls.at(-1)?.[0].parameter_values
  ).toMatchObject({ enable_thinking: true, reasoning_budget_tokens: 8000 });
});

const checkButton = () =>
  screen.getByRole("button", {
    name: "modelConfig.editDialog.checkConnectivity",
  });

describe("single draft connectivity", () => {
  it("SDC-01 uses the current draft without saving and follows the requested field order", async () => {
    setup();
    expect(checkButton()).toBeDisabled();
    const endpoint = screen.getByLabelText("modelProfile.endpoint");
    const key = screen.getByLabelText("modelProfile.apiKey");
    const id = screen.getByLabelText("modelProfile.requestModel");
    const profile = screen.getByLabelText("modelProfile.modelProfile");
    for (const [first, second] of [
      [endpoint, key],
      [key, id],
      [id, profile],
    ])
      expect(
        first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
    fillIdentity();
    fireEvent.change(key, { target: { value: "draft-only-key" } });
    await waitForSaveReady();
    fireEvent.click(checkButton());
    await screen.findByText("model.status.available");
    expect(api.validateModelOutlet).toHaveBeenCalledOnce();
    expect(api.validateModelOutlet.mock.calls[0][0]).toMatchObject({
      draft: {
        request_model_id: "custom-model",
        api_key: "draft-only-key",
        catalog_revision: "catalog-v1",
        parameter_values: {
          temperature: expect.any(Number),
          top_p: expect.any(Number),
        },
      },
    });
    expect(api.createModelOutlet).not.toHaveBeenCalled();
    expect(JSON.stringify(api.previewModelProfile.mock.calls)).not.toContain(
      "draft-only-key"
    );
    fireEvent.change(key, { target: { value: "changed-key" } });
    expect(
      screen.queryByText("model.status.available")
    ).not.toBeInTheDocument();
    expect(api.validateModelOutlet).toHaveBeenCalledOnce();
  });

  it("SDC-02 shows provider errors and permits saving after a failed explicit check", async () => {
    api.validateModelOutlet.mockResolvedValue({
      ok: false,
      check_receipt: "failed-backend-proof",
      error: {
        category: "MODEL_REQUEST_INVALID",
        scope: "model",
        message_source: "provider",
        message: "(400) top_p must be less than 1",
      },
    });
    const callbacks = setup();
    fillIdentity();
    await waitForSaveReady();
    fireEvent.click(checkButton());
    const issues = await screen.findByRole("button", {
      name: "modelProfile.checkIssues",
    });
    fireEvent.click(issues);
    await screen.findByText(/\(400\) top_p must be less than 1/);
    expect(saveButton()).toBeEnabled();
    fireEvent.click(saveButton());
    await waitFor(() => expect(callbacks.onDone).toHaveBeenCalledOnce());
    expect(api.createModelOutlet).toHaveBeenCalledOnce();
    expect(api.createModelOutlet.mock.calls[0][0].check_receipt).toBe(
      "failed-backend-proof"
    );
    expect(api.validateModelOutlet).toHaveBeenCalledOnce();
  });

  it("SDC-03 cancels an edited draft and ignores its late response", async () => {
    let finish!: (result: unknown) => void;
    api.validateModelOutlet.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    setup();
    fillIdentity();
    await waitForSaveReady();
    fireEvent.click(checkButton());
    const signal = api.validateModelOutlet.mock.calls[0][1] as AbortSignal;
    fireEvent.change(screen.getByLabelText("modelProfile.apiKey"), {
      target: { value: "replacement" },
    });
    expect(signal.aborted).toBe(true);
    await waitForSaveReady();
    fireEvent.click(checkButton());
    await screen.findByText("model.status.available");
    await act(async () =>
      finish({ ok: false, error: { category: "MODEL_NETWORK_ERROR" } })
    );
    expect(screen.getByText("model.status.available")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "modelProfile.checkIssues" })
    ).not.toBeInTheDocument();
  });

  it("SDC-04 allows saving while an explicit check is pending", async () => {
    api.validateModelOutlet.mockImplementation(() => new Promise(() => {}));
    const callbacks = setup();
    fillIdentity();
    await waitForSaveReady();
    fireEvent.click(checkButton());
    expect(saveButton()).toBeEnabled();
    fireEvent.click(saveButton());
    await waitFor(() => expect(callbacks.onDone).toHaveBeenCalledOnce());
    expect(api.createModelOutlet).toHaveBeenCalledOnce();
  });
});

it("SDC-05 reports management network failures and aborts checks on close", async () => {
  api.validateModelOutlet.mockRejectedValueOnce(
    new TypeError("Failed to fetch")
  );
  const { unmount } = setup();
  fillIdentity();
  await waitForSaveReady();
  fireEvent.click(checkButton());
  await screen.findByRole("button", { name: "modelProfile.checkIssues" });
  expect(saveButton()).toBeEnabled();
  api.validateModelOutlet.mockImplementationOnce(() => new Promise(() => {}));
  fireEvent.click(checkButton());
  const signal = api.validateModelOutlet.mock.calls[1][1] as AbortSignal;
  unmount();
  expect(signal.aborted).toBe(true);
  expect(api.createModelOutlet).not.toHaveBeenCalled();
});

it("ECS-02 saves a successful explicit check receipt without a second probe", async () => {
  api.validateModelOutlet.mockResolvedValue({
    ok: true,
    check_receipt: "successful-proof",
  });
  const callbacks = setup();
  fillIdentity();
  await waitForSaveReady();
  fireEvent.click(checkButton());
  await screen.findByText("model.status.available");
  fireEvent.click(saveButton());
  await waitFor(() => expect(callbacks.onDone).toHaveBeenCalledOnce());
  expect(api.createModelOutlet.mock.calls[0][0].check_receipt).toBe(
    "successful-proof"
  );
  expect(api.validateModelOutlet).toHaveBeenCalledTimes(1);
});

it.each([
  ["PARAMETER_UNKNOWN", "unknown"],
  ["PARAMETER_VALUE_INVALID", "value"],
  ["FIXED_PARAMETER", "fixed"],
  ["PARAMETER_DEPENDENCY", "dependency"],
  ["UNRECOGNIZED_RULE", "source"],
])(
  "AEU-04 explains configuration conflict %s with localized labels or a source marker",
  async (category, message) => {
    api.previewModelProfile.mockRejectedValue(
      new ApiError("MODEL_OUTLET_INVALID", "invalid", {
        category,
        field: "/reasoning_effort",
      })
    );
    setup();
    fillIdentity();
    await screen.findByText(`modelProfile.validation.${message}`);
    if (message === "source") {
      expect(translate).toHaveBeenCalledWith("modelProfile.validation.source", {
        detail: `${category} · /reasoning_effort`,
      });
    } else {
      expect(translate).toHaveBeenCalledWith(
        `modelProfile.validation.${message}`,
        {
          field: "modelProfile.parameterLabel.reasoning_effort",
        }
      );
    }
    expect(api.createModelOutlet).not.toHaveBeenCalled();
  }
);
