// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ModelOutletAddForm } from "../../app/[locale]/models/components/model/ModelOutletAddForm";
import type { ModelOutletResponse } from "../../types/modelProfile";

const api = vi.hoisted(() => ({
  listModelProfiles: vi.fn(),
  listProviderProfiles: vi.fn(),
  previewModelOutletPatch: vi.fn(),
  updateModelOutlet: vi.fn(),
  validateModelOutlet: vi.fn(),
}));
vi.mock("../../services/modelProfileService", () => api);
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function saved(values: Record<string, unknown>): ModelOutletResponse {
  const rules = ["temperature", "top_p"].map((key) => ({
    key,
    schema: {
      type: "number",
      minimum: 0,
      maximum: key === "temperature" ? 2 : 1,
    },
    visible: true,
    editable: true,
    required: false,
    allowed_scopes: ["outlet"],
    ui_group: "sampling",
  }));
  return {
    model_id: 42,
    config_revision: 7,
    field_specs: rules,
    has_credential: true,
    profile: {
      identity: { display_name: "Old model", request_model_id: "old-model" },
      connection: {
        base_url: "https://example.invalid/v1",
        ssl_verify: true,
        timeout_seconds: 120,
      },
      capabilities: { context: {} },
      context_configuration: {},
      parameter_values: values,
      parameter_rules: rules,
      extra_api_parameters: [],
    },
  } as unknown as ModelOutletResponse;
}

function setup(model: ModelOutletResponse) {
  api.previewModelOutletPatch.mockImplementation(async (_id, patch) => {
    const values = {
      ...model.profile.parameter_values,
      ...patch.parameter_values,
    };
    for (const key of patch.delete_parameters ?? []) delete values[key];
    for (const key of ["temperature", "top_p"])
      if (values[key] === null) delete values[key];
    return {
      catalog_revision: "saved",
      selected: { model: null, provider: null },
      candidates: { models: [], providers: [] },
      field_specs: model.field_specs,
      parameter_values: values,
      capabilities: model.profile.capabilities,
      conflicts: [],
    };
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <ModelOutletAddForm
          editing={model}
          onDone={vi.fn()}
          onPendingChange={vi.fn()}
          onSuccess={vi.fn()}
        />
      </App>
    </QueryClientProvider>
  );
}

async function ready() {
  const save = await screen.findByRole("button", { name: "common.save" });
  await waitFor(() => expect(save).toBeEnabled(), { timeout: 7000 });
  return save;
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.listModelProfiles.mockResolvedValue({ items: [] });
  api.listProviderProfiles.mockResolvedValue({ items: [] });
  api.updateModelOutlet.mockResolvedValue({ config_revision: 8 });
  api.validateModelOutlet.mockResolvedValue({
    ok: true,
    check_scope: "connection_only",
  });
});

it("AC-002 edits an upgraded outlet with missing sampling without inventing defaults", async () => {
  setup(saved({}));
  await ready();
  expect(screen.getByRole("spinbutton", { name: "temperature" })).toHaveValue(
    ""
  );
  expect(screen.getByRole("spinbutton", { name: "top_p" })).toHaveValue("");
  fireEvent.click(
    screen.getByRole("button", {
      name: "modelConfig.editDialog.checkConnectivity",
    })
  );
  await waitFor(() => expect(api.validateModelOutlet).toHaveBeenCalledOnce());
  expect(
    api.validateModelOutlet.mock.calls[0][0].patch.parameter_values
  ).toEqual({});
  fireEvent.click(await ready());
  await waitFor(() => expect(api.updateModelOutlet).toHaveBeenCalledOnce());
  expect(api.updateModelOutlet.mock.calls[0][1].parameter_values).toEqual({});
});

it.each([["temperature"], ["top_p"], ["temperature", "top_p"]])(
  "AC-003 checks and saves explicit empty sampling %j",
  async (...keys: string[]) => {
    setup(saved({ temperature: 0.6, top_p: 0.9 }));
    await ready();
    for (const key of keys)
      fireEvent.change(screen.getByRole("spinbutton", { name: key }), {
        target: { value: "" },
      });
    await ready();
    for (const key of keys)
      expect(screen.getByRole("spinbutton", { name: key })).toHaveValue("");
    fireEvent.click(
      screen.getByRole("button", {
        name: "modelConfig.editDialog.checkConnectivity",
      })
    );
    await waitFor(() => expect(api.validateModelOutlet).toHaveBeenCalledOnce());
    for (const key of keys)
      expect(
        api.validateModelOutlet.mock.calls[0][0].patch.parameter_values[key]
      ).toBeNull();
    fireEvent.click(await ready());
    await waitFor(() => expect(api.updateModelOutlet).toHaveBeenCalledOnce());
    const patch = api.updateModelOutlet.mock.calls[0][1];
    for (const key of keys) expect(patch.parameter_values[key]).toBeNull();
    const unchanged = ["temperature", "top_p"].filter(
      (key) => !keys.includes(key)
    );
    for (const key of unchanged)
      expect(patch.parameter_values[key]).toBe(
        key === "temperature" ? 0.6 : 0.9
      );
  },
  15000
);
