// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ModelOutletEditDialog } from "../../app/[locale]/models/components/model/ModelOutletEditDialog";
import { ConversationModelParameters } from "../../components/model/ConversationModelParameters";

const api = vi.hoisted(() => ({
  getModelOutlet: vi.fn(),
  updateModelOutlet: vi.fn(),
  getConversationModelPreferences: vi.fn(),
  patchConversationModelPreferences: vi.fn(),
}));
vi.mock("../../services/modelProfileService", () => api);
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
// The shared field's actual structured-value behavior is covered by modelOutletAddForm.
vi.mock("../../components/model/ModelParameterField", () => ({
  ModelParameterField: ({
    rule,
    onChange,
    onReset,
  }: {
    rule: { key: string };
    onChange: (key: string, value: unknown) => void;
    onReset: (key: string) => void;
  }) => (
    <>
      <span>{rule.key}</span>
      <button type="button" onClick={() => onChange(rule.key, 0)}>
        {rule.key}=zero
      </button>
      <button type="button" onClick={() => onReset(rule.key)}>
        {rule.key}=default
      </button>
    </>
  ),
}));
const rule = {
  key: "temperature",
  visible: true,
  editable: true,
  allowed_scopes: ["outlet", "conversation"],
  schema: { type: "number" },
};

function setup(child: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <App>{child}</App>
    </QueryClientProvider>
  );
}
async function openSessionSettings() {
  const entry = screen.getByRole("button", {
    name: "workbench.controls.advanced",
  });
  await waitFor(() => expect(entry).toBeEnabled());
  fireEvent.click(entry);
}
beforeEach(() => {
  Object.values(api).forEach((method) => method.mockReset());
  api.getModelOutlet.mockResolvedValue({
    model_id: 42,
    config_revision: 7,
    field_specs: [rule],
    has_credential: true,
    profile: {
      identity: { display_name: "display", request_model_id: "exact-model" },
      connection: {
        base_url: "https://models.invalid/v1",
        ssl_verify: true,
        timeout_seconds: 60,
        concurrency_limit: null,
        credential_ref: { kind: "model_record", model_id: 42 },
      },
      capabilities: {
        context: {
          combined_window: 200000,
          input_limit: null,
          output_limit: 16000,
        },
      },
      context_configuration: {
        output_reserve_tokens: 4096,
        tokenizer_family: null,
      },
      parameter_values: { temperature: 0.7 },
      extra_api_parameters: [],
      parameter_rules: [rule],
    },
  });
  api.updateModelOutlet.mockResolvedValue({ config_revision: 8 });
  api.getConversationModelPreferences.mockResolvedValue({
    version: 4,
    config_revision: 7,
    parameter_values: {},
    defaults: { temperature: 0.7 },
    field_specs: [rule],
    issues: [],
  });
  api.patchConversationModelPreferences.mockResolvedValue(undefined);
});

it("UI-LAYOUT-08 edits visible saved parameters and the displayed revision without echoing credential references or clearing an omitted key", async () => {
  const success = vi.fn();
  setup(
    <ModelOutletEditDialog modelId={42} onClose={vi.fn()} onSuccess={success} />
  );
  await screen.findByRole("heading", { name: "modelProfile.modelParameters" });
  await waitFor(() =>
    expect(
      screen.getByRole("region", { name: "modelProfile.samplingGroup" })
    ).toBeVisible()
  );
  expect(
    screen.queryByRole("button", { name: "modelProfile.layout.reset" })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("spinbutton", { name: "modelProfile.maximumOutput" })
  ).toHaveValue("16000");
  fireEvent.click(await screen.findByText("temperature=zero"));
  fireEvent.click(screen.getByRole("button", { name: "common.save" }));
  await waitFor(() => expect(success).toHaveBeenCalledOnce());
  const request = api.updateModelOutlet.mock.calls[0][1];
  expect(request.expected_revision).toBe(7);
  expect(request.parameter_values.temperature).toBe(0);
  expect(request.parameter_values).not.toHaveProperty("max_output_tokens");
  expect(request).not.toHaveProperty("api_key");
  expect(screen.queryByText("modelProfile.clearKey")).not.toBeInTheDocument();
  expect(request.connection).not.toHaveProperty("credential_ref");
}, 15000);

it("keeps a conflicted edit open without retrying another revision", async () => {
  api.updateModelOutlet.mockRejectedValue(new Error("stale"));
  const success = vi.fn();
  setup(
    <ModelOutletEditDialog modelId={42} onClose={vi.fn()} onSuccess={success} />
  );
  await screen.findByRole("heading", { name: "modelProfile.modelParameters" });
  fireEvent.click(screen.getByRole("button", { name: "common.save" }));
  await waitFor(() =>
    expect(
      screen.getAllByText("modelProfile.editFailed").length
    ).toBeGreaterThan(0)
  );
  expect(success).not.toHaveBeenCalled();
  expect(api.updateModelOutlet).toHaveBeenCalledOnce();
  expect(api.updateModelOutlet.mock.calls[0][1].expected_revision).toBe(7);
}, 15000);

it("saves only explicitly adjusted values for the current conversation and outlet", async () => {
  setup(<ConversationModelParameters conversationId={11} modelId={42} />);
  await openSessionSettings();
  const temperature = await screen.findByRole("spinbutton", {
    name: "workbench.controls.temperature",
  });
  fireEvent.change(temperature, { target: { value: "0" } });
  fireEvent.blur(temperature);
  await waitFor(() =>
    expect(
      api.patchConversationModelPreferences
    ).toHaveBeenCalledExactlyOnceWith(11, 42, {
      expected_version: 4,
      parameter_values: { temperature: 0 },
      delete_parameters: [],
    })
  );
  expect(api.updateModelOutlet).not.toHaveBeenCalled();
}, 15000);

it("explicitly removes a preference without copying the outlet default", async () => {
  api.getConversationModelPreferences.mockResolvedValue({
    version: 5,
    config_revision: 7,
    parameter_values: { temperature: 0 },
    defaults: { temperature: 0.7 },
    field_specs: [rule],
    issues: [],
  });
  setup(<ConversationModelParameters conversationId={11} modelId={42} />);
  await openSessionSettings();
  fireEvent.click(
    await screen.findByRole("button", { name: "workbench.controls.restore" })
  );
  await waitFor(() =>
    expect(
      api.patchConversationModelPreferences
    ).toHaveBeenCalledExactlyOnceWith(11, 42, {
      expected_version: 5,
      parameter_values: {},
      delete_parameters: ["temperature"],
    })
  );
  expect(api.updateModelOutlet).not.toHaveBeenCalled();
}, 15000);

it("keeps a failed preference save open without retrying or changing the model", async () => {
  api.patchConversationModelPreferences.mockRejectedValue(new Error("stale"));
  setup(<ConversationModelParameters conversationId={11} modelId={42} />);
  await openSessionSettings();
  const temperature = await screen.findByRole("spinbutton", {
    name: "workbench.controls.temperature",
  });
  fireEvent.change(temperature, { target: { value: "0" } });
  fireEvent.blur(temperature);
  await waitFor(() =>
    expect(
      screen.getAllByText("modelProfile.preferencesFailed").length
    ).toBeGreaterThan(0)
  );
  expect(api.patchConversationModelPreferences).toHaveBeenCalledOnce();
  await waitFor(() =>
    expect(
      screen.getByRole("spinbutton", { name: "workbench.controls.temperature" })
    ).toHaveValue(0)
  );
  expect(api.updateModelOutlet).not.toHaveBeenCalled();
}, 15000);

it("requires a persisted conversation or an unsent thread scope before editing preferences", () => {
  setup(<ConversationModelParameters modelId={42} />);
  expect(
    screen.getByRole("button", { name: "workbench.controls.advanced" })
  ).toBeDisabled();
  expect(api.getConversationModelPreferences).not.toHaveBeenCalled();
});

it("keeps incomplete custom request rows local and disables outlet saving", async () => {
  setup(
    <ModelOutletEditDialog modelId={42} onClose={vi.fn()} onSuccess={vi.fn()} />
  );
  await screen.findByRole("heading", { name: "modelProfile.modelParameters" });
  fireEvent.click(screen.getByText("modelProfile.advanced"));
  fireEvent.click(
    screen.getByRole("button", { name: "modelProfile.addParameter" })
  );
  expect(screen.getByRole("button", { name: "common.save" })).toBeDisabled();
  await waitFor(() =>
    expect(screen.getByText("modelProfile.parameterRowsInvalid")).toBeVisible()
  );
  expect(api.updateModelOutlet).not.toHaveBeenCalled();
}, 15000);

it.each(["unknown", "unsupported"])(
  "UI-SAMPLING-10 shows required Top P even when capability is %s",
  async (status) => {
    const saved = await api.getModelOutlet();
    saved.field_specs = [{ ...rule, key: "top_p", visible: false }];
    saved.profile.capabilities.sampling = { top_p: { status } };
    api.getModelOutlet.mockResolvedValue(saved);
    setup(
      <ModelOutletEditDialog
        modelId={42}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    );
    await screen.findByRole("heading", {
      name: "modelProfile.modelParameters",
    });
    fireEvent.click(screen.getByText("modelProfile.advanced"));
    await waitFor(() => expect(screen.getByText("top_p")).toBeVisible());
  }
);

it("keeps output capability separate from an existing request default", async () => {
  const saved = await api.getModelOutlet();
  saved.profile.parameter_values.max_output_tokens = 4096;
  api.getModelOutlet.mockResolvedValue(saved);
  setup(
    <ModelOutletEditDialog modelId={42} onClose={vi.fn()} onSuccess={vi.fn()} />
  );
  await screen.findByRole("heading", { name: "modelProfile.modelParameters" });
  fireEvent.click(screen.getByText("modelProfile.advanced"));
  const output = screen.getByRole("spinbutton", {
    name: "modelProfile.maximumOutput",
  });
  expect(output).toHaveValue("16000");
  fireEvent.change(output, { target: { value: "8000" } });
  fireEvent.click(screen.getByRole("button", { name: "common.save" }));
  await waitFor(() => expect(api.updateModelOutlet).toHaveBeenCalledOnce());
  const request = api.updateModelOutlet.mock.calls[0][1];
  expect(request.context_limits.output_limit).toBe(8000);
  expect(request.parameter_values.max_output_tokens).toBe(4096);
  expect(request.delete_parameters).not.toContain("max_output_tokens");
});

it("UI-LAYOUT-08 cancels an edited draft without saving", async () => {
  const close = vi.fn();
  setup(
    <ModelOutletEditDialog modelId={42} onClose={close} onSuccess={vi.fn()} />
  );
  await screen.findByRole("heading", { name: "modelProfile.modelParameters" });
  fireEvent.click(screen.getByText("temperature=zero"));
  fireEvent.click(screen.getByRole("button", { name: "common.cancel" }));
  expect(close).toHaveBeenCalledOnce();
  expect(api.updateModelOutlet).not.toHaveBeenCalled();
});

it("UI-LAYOUT-08 retries a failed load before exposing saved parameters", async () => {
  const saved = await api.getModelOutlet();
  api.getModelOutlet
    .mockReset()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue(saved);
  setup(
    <ModelOutletEditDialog modelId={42} onClose={vi.fn()} onSuccess={vi.fn()} />
  );
  await screen.findByText("modelProfile.loadFailed");
  expect(screen.queryByText("temperature=zero")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
  await screen.findByText("temperature=zero");
  expect(api.updateModelOutlet).not.toHaveBeenCalled();
});

it.each([true, false])(
  "UI-TLS-12 reflects saved TLS verification=%s and saves its inverse after toggling",
  async (verify) => {
    const saved = await api.getModelOutlet();
    saved.profile.connection.ssl_verify = verify;
    api.getModelOutlet.mockResolvedValue(saved);
    const success = vi.fn();
    setup(
      <ModelOutletEditDialog
        modelId={42}
        onClose={vi.fn()}
        onSuccess={success}
      />
    );
    await screen.findByRole("heading", {
      name: "modelProfile.modelParameters",
    });
    fireEvent.click(screen.getByText("modelProfile.advanced"));
    const toggle = screen.getByRole("switch", {
      name: "modelProfile.skipTlsVerify",
    });
    expect(toggle).toHaveAttribute("aria-checked", String(!verify));
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));
    await waitFor(() => expect(success).toHaveBeenCalledOnce());
    expect(api.updateModelOutlet.mock.calls[0][1].connection.ssl_verify).toBe(
      !verify
    );
  },
  15000
);

it.each([
  [true, undefined, undefined],
  [false, undefined, undefined],
  [true, "", null],
  [true, "***", undefined],
  [true, "replacement-key", "replacement-key"],
  [false, "replacement-key", "replacement-key"],
] as const)(
  "UI-AUTH-13 masks saved=%s and handles input=%s",
  async (hasKey, input, expected) => {
    const saved = await api.getModelOutlet();
    saved.has_credential = hasKey;
    api.getModelOutlet.mockResolvedValue(saved);
    const success = vi.fn();
    setup(
      <ModelOutletEditDialog
        modelId={42}
        onClose={vi.fn()}
        onSuccess={success}
      />
    );
    const field = await screen.findByLabelText("modelProfile.apiKey");
    expect(field).toHaveValue(hasKey ? "********" : "");
    if (input !== undefined)
      fireEvent.change(field, { target: { value: input } });
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));
    await waitFor(() => expect(success).toHaveBeenCalledOnce());
    const request = api.updateModelOutlet.mock.calls[0][1];
    if (expected === undefined) expect(request).not.toHaveProperty("api_key");
    else expect(request.api_key).toBe(expected);
    expect(JSON.stringify(request)).not.toContain("********");
  },
  15000
);

it("UI-AUTH-13 blocks mixed placeholder text from becoming a credential", async () => {
  setup(
    <ModelOutletEditDialog modelId={42} onClose={vi.fn()} onSuccess={vi.fn()} />
  );
  const field = await screen.findByLabelText("modelProfile.apiKey");
  fireEvent.change(field, { target: { value: "********new" } });
  expect(screen.getByRole("button", { name: "common.save" })).toBeDisabled();
  expect(api.updateModelOutlet).not.toHaveBeenCalled();
});

it.each([true, false])(
  "UI-AUTH-14 exposes visibility only for newly entered keys (saved=%s)",
  async (hasKey) => {
    const saved = await api.getModelOutlet();
    saved.has_credential = hasKey;
    api.getModelOutlet.mockResolvedValue(saved);
    setup(
      <ModelOutletEditDialog
        modelId={42}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    );
    const field = await screen.findByLabelText("modelProfile.apiKey");
    expect(field).toHaveAttribute("type", "password");
    expect(
      screen.queryByRole("button", { name: "Show" })
    ).not.toBeInTheDocument();
    fireEvent.change(field, { target: { value: "replacement-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(field).toHaveAttribute("type", "text");
    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(field).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    fireEvent.change(field, { target: { value: "" } });
    expect(
      screen.queryByRole("button", { name: /Show|Hide/ })
    ).not.toBeInTheDocument();
    expect(field).toHaveAttribute("type", "password");
    fireEvent.change(field, { target: { value: "another-key" } });
    expect(field).toHaveAttribute("type", "password");
    // jsdom does not complete Modal's CSS entrance animation. Assert the
    // credential control's own visibility, independently of modal opacity.
    expect(
      screen.getByRole("button", { name: "Show" }).parentElement
    ).toHaveStyle({
      display: "inline-flex",
    });
    if (hasKey) {
      fireEvent.change(field, { target: { value: "********" } });
      expect(
        screen.queryByRole("button", { name: /Show|Hide/ })
      ).not.toBeInTheDocument();
      expect(field).toHaveAttribute("type", "password");
    }
    expect(api.updateModelOutlet).not.toHaveBeenCalled();
  },
  15000
);
