// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ModelOutletEditDialog } from "../../app/[locale]/models/components/model/ModelOutletEditDialog";
import { ConversationModelParameters } from "../../components/model/ConversationModelParameters";

const api = vi.hoisted(() => ({
  getModelOutlet: vi.fn(),
  confirmModelOutletMigration: vi.fn(),
  listModelProfiles: vi.fn(),
  listProviderProfiles: vi.fn(),
  previewModelOutletPatch: vi.fn(),
  updateModelOutlet: vi.fn(),
  validateModelOutlet: vi.fn(),
  getConversationModelPreferences: vi.fn(),
  patchConversationModelPreferences: vi.fn(),
}));
vi.mock("../../services/modelProfileService", () => api);
const auth = vi.hoisted(() => ({ role: "ADMIN" }));
vi.mock("../../components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { role: auth.role } }),
}));
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
async function waitForEditSaveReady() {
  const button = screen.getByRole("button", { name: "common.save" });
  await waitFor(() => expect(button).toBeEnabled(), { timeout: 5000 });
}
async function openSessionSettings() {
  const entry = screen.getByRole("button", {
    name: "workbench.controls.advanced",
  });
  await waitFor(() => expect(entry).toBeEnabled());
  fireEvent.click(entry);
}
beforeEach(() => {
  auth.role = "ADMIN";
  Object.values(api).forEach((method) => method.mockReset());
  api.getModelOutlet.mockResolvedValue({
    model_id: 42,
    config_revision: 7,
    field_specs: [rule],
    has_credential: true,
    profile: {
      provenance: {
        provider_metadata: {
          migration: { version: "fixture", reviewed_revision: null },
        },
      },
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
  api.listModelProfiles.mockResolvedValue({
    catalog_revision: "catalog",
    items: [],
  });
  api.listProviderProfiles.mockResolvedValue({
    catalog_revision: "catalog",
    items: [],
  });
  api.previewModelOutletPatch.mockImplementation(async (_id, patch) => {
    const saved = await api.getModelOutlet.mock.results[0].value;
    return {
      catalog_revision: "saved",
      selected: { model: null, provider: null },
      candidates: { models: [], providers: [] },
      field_specs: saved.profile.parameter_rules,
      parameter_values: {
        ...saved.profile.parameter_values,
        ...patch.parameter_values,
      },
      capabilities: saved.profile.capabilities,
      conflicts: [],
    };
  });
  api.updateModelOutlet.mockResolvedValue({ model_id: 42, config_revision: 8 });
  api.confirmModelOutletMigration.mockResolvedValue(undefined);
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

function edit() {
  const close = vi.fn(),
    success = vi.fn();
  setup(
    <ModelOutletEditDialog modelId={42} onClose={close} onSuccess={success} />
  );
  return { close, success };
}
async function save(label = "modelMigration.saveAndConfirm") {
  const button = await screen.findByRole("button", { name: label });
  await waitFor(() => expect(button).toBeEnabled(), { timeout: 5000 });
  fireEvent.click(button);
}
it("ME-02 saves edits then confirms exactly the returned revision without revealing credentials", async () => {
  const { success } = edit();
  await screen.findByText("modelMigration.pendingHint");
  expect(
    screen.queryByText("modelMigration.reviewTitle")
  ).not.toBeInTheDocument();
  fireEvent.click(await screen.findByText("temperature=zero"));
  await save();
  await waitFor(() => expect(success).toHaveBeenCalledOnce());
  expect(
    api.updateModelOutlet.mock.calls[0][1].parameter_values.temperature
  ).toBe(0);
  expect(api.confirmModelOutletMigration).toHaveBeenCalledExactlyOnceWith(
    42,
    8
  );
  expect(api.updateModelOutlet.mock.invocationCallOrder[0]).toBeLessThan(
    api.confirmModelOutletMigration.mock.invocationCallOrder[0]
  );
  expect(api.updateModelOutlet.mock.calls[0][1]).not.toHaveProperty("api_key");
});
it("ME-03 never confirms or closes when saving conflicts", async () => {
  api.updateModelOutlet.mockRejectedValue(
    new Error("MODEL_OUTLET_VERSION_CONFLICT")
  );
  const { close, success } = edit();
  fireEvent.click(await screen.findByText("temperature=zero"));
  await save();
  await screen.findByText("modelProfile.editFailed");
  expect(api.confirmModelOutletMigration).not.toHaveBeenCalled();
  expect(close).not.toHaveBeenCalled();
  expect(success).not.toHaveBeenCalled();
});
it("ME-03 reports a saved but unreviewed version without retrying the successful save", async () => {
  api.confirmModelOutletMigration.mockRejectedValue(
    new Error("MODEL_OUTLET_VERSION_CONFLICT")
  );
  const { close, success } = edit();
  fireEvent.click(await screen.findByText("temperature=zero"));
  await save();
  await screen.findByText("modelMigration.savedReviewFailed");
  await waitFor(() => expect(success).toHaveBeenCalledOnce());
  expect(close).toHaveBeenCalledOnce();
  expect(api.updateModelOutlet).toHaveBeenCalledOnce();
  expect(api.confirmModelOutletMigration).toHaveBeenCalledExactlyOnceWith(
    42,
    8
  );
  expect(screen.queryByText("modelProfile.saved")).not.toBeInTheDocument();
});
it("ME-02 cancellation never saves or confirms", async () => {
  const { close } = edit();
  fireEvent.click(await screen.findByRole("button", { name: "common.cancel" }));
  expect(close).toHaveBeenCalledOnce();
  expect(api.updateModelOutlet).not.toHaveBeenCalled();
  expect(api.confirmModelOutletMigration).not.toHaveBeenCalled();
});
it("ME-02 non-administrators retain ordinary save without confirmation", async () => {
  auth.role = "DEV";
  const { success } = edit();
  await save("common.save");
  await waitFor(() => expect(success).toHaveBeenCalledOnce());
  expect(api.confirmModelOutletMigration).not.toHaveBeenCalled();
});
it.each(["reviewed", "ordinary"])(
  "ME-04 %s outlets retain ordinary editing",
  async (kind) => {
    const snapshot = await api.getModelOutlet.getMockImplementation()!();
    if (kind === "reviewed")
      snapshot.profile.provenance.provider_metadata.migration.reviewed_revision = 7;
    else delete snapshot.profile.provenance.provider_metadata.migration;
    const { success } = edit();
    await save("common.save");
    await waitFor(() => expect(success).toHaveBeenCalledOnce());
    expect(api.confirmModelOutletMigration).not.toHaveBeenCalled();
    expect(
      screen.queryByText("modelMigration.pendingHint")
    ).not.toBeInTheDocument();
  }
);
it("ME-02 a missing reviewed revision still requires review", async () => {
  const snapshot = await api.getModelOutlet.getMockImplementation()!();
  delete snapshot.profile.provenance.provider_metadata.migration
    .reviewed_revision;
  edit();
  await screen.findByRole("button", { name: "modelMigration.confirm" });
});
it("ME-03 read failure never offers an editor or confirms a stale snapshot", async () => {
  api.getModelOutlet.mockRejectedValue(new Error("failed"));
  edit();
  await screen.findByText("modelProfile.loadFailed");
  expect(
    screen.queryByRole("button", { name: "modelMigration.saveAndConfirm" })
  ).not.toBeInTheDocument();
  expect(api.confirmModelOutletMigration).not.toHaveBeenCalled();
});

it.each([null, undefined])(
  "ME-05 confirms untouched legacy Top P %s without saving or filling defaults",
  async (value) => {
    const snapshot = await api.getModelOutlet.getMockImplementation()!();
    if (value === undefined) delete snapshot.profile.parameter_values.top_p;
    else snapshot.profile.parameter_values.top_p = value;
    const { success } = edit();
    await save("modelMigration.confirm");
    await waitFor(() => expect(success).toHaveBeenCalledOnce());
    expect(api.updateModelOutlet).not.toHaveBeenCalled();
    expect(api.confirmModelOutletMigration).toHaveBeenCalledExactlyOnceWith(
      42,
      7
    );
    expect(snapshot.profile.parameter_values.top_p).toBe(value);
  }
);
it("ME-05 an unavailable parameter preview does not block review of the displayed saved snapshot", async () => {
  api.previewModelOutletPatch.mockRejectedValue(
    new Error("preview unavailable")
  );
  const { success } = edit();
  await save("modelMigration.confirm");
  await waitFor(() => expect(success).toHaveBeenCalledOnce());
  expect(api.updateModelOutlet).not.toHaveBeenCalled();
  expect(api.confirmModelOutletMigration).toHaveBeenCalledExactlyOnceWith(
    42,
    7
  );
});
it("ME-05 an edited legacy snapshot still requires valid sampling before save and review", async () => {
  const snapshot = await api.getModelOutlet.getMockImplementation()!();
  snapshot.profile.parameter_values.top_p = null;
  edit();
  fireEvent.click(await screen.findByText("temperature=zero"));
  const button = await screen.findByRole("button", {
    name: "modelMigration.saveAndConfirm",
  });
  await waitFor(() => expect(button).toBeDisabled());
  fireEvent.click(button);
  expect(api.updateModelOutlet).not.toHaveBeenCalled();
  expect(api.confirmModelOutletMigration).not.toHaveBeenCalled();
});
it("ME-05 a failed unchanged review remains open without patching or retrying a different revision", async () => {
  api.confirmModelOutletMigration.mockRejectedValue(
    new Error("MODEL_OUTLET_VERSION_CONFLICT")
  );
  const { close, success } = edit();
  await save("modelMigration.confirm");
  await screen.findByText("modelMigration.confirmFailed");
  expect(close).not.toHaveBeenCalled();
  expect(success).not.toHaveBeenCalled();
  expect(api.updateModelOutlet).not.toHaveBeenCalled();
  expect(api.confirmModelOutletMigration).toHaveBeenCalledExactlyOnceWith(
    42,
    7
  );
});
it("ME-05 opening advanced settings does not count as modifying the saved configuration", async () => {
  edit();
  const advanced = await screen.findByText("modelProfile.advanced");
  fireEvent.click(advanced);
  expect(
    await screen.findByRole("button", { name: "modelMigration.confirm" })
  ).toBeEnabled();
});
it("ME-05 reverting a field to its original value restores review-only behavior", async () => {
  const snapshot = await api.getModelOutlet.getMockImplementation()!();
  snapshot.profile.parameter_values.top_p = null;
  const { success } = edit();
  const field = await screen.findByRole("textbox", {
    name: "modelProfile.displayName",
  });
  fireEvent.change(field, { target: { value: "temporary edit" } });
  expect(
    await screen.findByRole("button", { name: "modelMigration.saveAndConfirm" })
  ).toBeDisabled();
  fireEvent.change(field, { target: { value: "display" } });
  await save("modelMigration.confirm");
  await waitFor(() => expect(success).toHaveBeenCalledOnce());
  expect(api.updateModelOutlet).not.toHaveBeenCalled();
  expect(api.confirmModelOutletMigration).toHaveBeenCalledExactlyOnceWith(
    42,
    7
  );
});
