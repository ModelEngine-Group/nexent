// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ModelAddDialog } from "../../app/[locale]/models/components/model/ModelAddDialog";

const api = vi.hoisted(() => ({
  listModelProfiles: vi.fn(),
  listProviderProfiles: vi.fn(),
  previewModelProfile: vi.fn(),
  createModelOutlet: vi.fn(),
  validateModelOutlet: vi.fn(),
}));
const legacy = vi.hoisted(() => ({
  getFullCatalog: vi.fn(),
  addProviderModel: vi.fn(),
  suggestCapacity: vi.fn(),
  backfillDefaults: vi.fn(),
}));
vi.mock("../../services/modelProfileService", () => api);
vi.mock("../../services/modelService", () => ({
  modelService: legacy,
  ModelError: class extends Error {},
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

async function waitForConfigurationReady() {
  const button = screen.getByRole("button", { name: "common.save" });
  await waitFor(() => expect(button).toBeEnabled(), { timeout: 7000 });
}

beforeEach(() => {
  Object.values(api).forEach((mock) => mock.mockReset());
  Object.values(legacy).forEach((mock) => mock.mockReset());
  api.listModelProfiles.mockResolvedValue({ items: [] });
  api.listProviderProfiles.mockResolvedValue({ items: [] });
  api.previewModelProfile.mockResolvedValue({
    catalog_revision: "r1",
    selected: { model: null, provider: null },
    field_specs: [],
    parameter_values: {},
    capabilities: {
      context: { combined_window: null, input_limit: null, output_limit: null },
    },
  });
  api.validateModelOutlet.mockResolvedValue({ ok: true });
  api.createModelOutlet.mockResolvedValue({ model_id: 10 });
  legacy.getFullCatalog.mockResolvedValue({ catalog: { providers: [] } });
  legacy.addProviderModel.mockResolvedValue([
    { id: "model-a", model_type: "llm" },
    { id: "model-b", model_type: "llm" },
  ]);
  legacy.suggestCapacity.mockResolvedValue(null);
  legacy.backfillDefaults.mockResolvedValue({});
});

it.each([false, true])(
  "keeps independent batch drafts and handles partial failure=%s",
  async (partialFailure) => {
    if (partialFailure)
      api.createModelOutlet.mockImplementation(async (request) => {
        if (request.request_model_id === "model-b")
          throw new Error("controlled-save-failure");
        return { model_id: 10, config_revision: 1 };
      });
    const onClose = vi.fn();
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <App>
          <ModelAddDialog
            isOpen
            initialTab="batch"
            onClose={onClose}
            onSuccess={vi.fn()}
          />
        </App>
      </QueryClientProvider>
    );
    fireEvent.change(screen.getByPlaceholderText("sk-..."), {
      target: { value: "controlled-key" },
    });
    fireEvent.change(
      screen.getByPlaceholderText("https://api.example.com/v1"),
      {
        target: { value: "https://models.invalid/v1" },
      }
    );
    fireEvent.click(
      screen.getByRole("button", { name: "modelConfig.addDialog.fetchModels" })
    );
    await screen.findByText("model-a");
    fireEvent.click(
      screen.getByRole("button", {
        name: "modelProfile.configureModel model-a",
      })
    );
    await waitForConfigurationReady();
    expect(screen.getByLabelText("modelProfile.endpoint")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("modelProfile.displayName"), {
      target: { value: "Configured A" },
    });
    await waitForConfigurationReady();
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));
    await waitFor(() =>
      expect(
        screen.queryByLabelText("modelProfile.requestModel")
      ).not.toBeInTheDocument()
    );
    expect(api.createModelOutlet).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", {
        name: "modelProfile.configureModel model-b",
      })
    );
    expect(screen.getByLabelText("modelProfile.displayName")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("modelProfile.displayName"), {
      target: { value: "Discarded B" },
    });
    fireEvent.click(
      screen.getAllByRole("button", { name: "common.cancel" }).at(-1)!
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "modelProfile.configureModel model-a",
      })
    );
    expect(screen.getByLabelText("modelProfile.displayName")).toHaveValue(
      "Configured A"
    );
    fireEvent.click(
      screen.getAllByRole("button", { name: "common.cancel" }).at(-1)!
    );
    fireEvent.click(screen.getByText("modelConfig.addDialog.toggleAll"));
    fireEvent.click(
      screen.getByRole("button", { name: "modelConfig.addDialog.batchCheck" })
    );
    await waitFor(() =>
      expect(api.validateModelOutlet).toHaveBeenCalledTimes(2)
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "modelConfig.addDialog.batchCheck" })
      ).toBeEnabled()
    );
    fireEvent.click(
      screen.getByRole("button", { name: "modelConfig.addDialog.addSelected" })
    );
    await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledTimes(2));
    expect(api.createModelOutlet.mock.calls[0][0]).toMatchObject({
      request_model_id: "model-a",
      display_name: "Configured A",
      api_key: "controlled-key",
      catalog_revision: "r1",
    });
    expect(api.createModelOutlet.mock.calls[1][0].display_name).not.toBe(
      "Discarded B"
    );
    const checked = api.validateModelOutlet.mock.calls.find(
      ([request]) => request.draft.request_model_id === "model-a"
    )![0].draft;
    expect(api.createModelOutlet.mock.calls[0][0]).toMatchObject(checked);
    if (partialFailure) {
      await waitFor(() =>
        expect(screen.queryByText("model-a")).not.toBeInTheDocument()
      );
      expect(screen.getByText("model-b")).toBeVisible();
      expect(onClose).not.toHaveBeenCalled();
    } else {
      await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    }
  },
  60000
);
