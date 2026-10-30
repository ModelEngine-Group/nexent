// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { ApiError } from "../../services/api";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ModelAddDialog } from "../../app/[locale]/models/components/model/ModelAddDialog";

const api = vi.hoisted(() => ({
  listModelProfiles: vi.fn(),
  listProviderProfiles: vi.fn(),
  previewModelProfile: vi.fn(),
  createModelOutlet: vi.fn(),
  updateModelOutlet: vi.fn(),
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
const translate = vi.hoisted(() =>
  vi.fn((key: string, _options?: unknown) => key)
);
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: translate }) }));

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
  api.updateModelOutlet.mockResolvedValue({ model_id: 10, config_revision: 2 });
  legacy.getFullCatalog.mockResolvedValue({ catalog: { providers: [] } });
  legacy.addProviderModel.mockResolvedValue([
    { id: "model-a", model_type: "llm" },
    { id: "model-b", model_type: "llm" },
  ]);
  legacy.suggestCapacity.mockResolvedValue(null);
  legacy.backfillDefaults.mockResolvedValue({});
});

it("S-01 saves unchecked batch models without waiting for the probe and closes", async () => {
  let finishFirstSave!: (value: {
    model_id: number;
    config_revision: number;
  }) => void;
  api.createModelOutlet.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finishFirstSave = resolve;
      })
  );
  api.validateModelOutlet.mockImplementation(() => new Promise(() => {}));
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
  fireEvent.change(screen.getByPlaceholderText("https://api.example.com/v1"), {
    target: { value: "https://models.invalid/v1" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "modelConfig.addDialog.fetchModels" })
  );
  await screen.findByText("model-a");
  fireEvent.click(
    screen.getByRole("button", { name: "modelProfile.configureModel model-a" })
  );
  await waitForConfigurationReady();
  fireEvent.change(screen.getByLabelText("modelProfile.displayName"), {
    target: { value: "Configured A" },
  });
  await waitForConfigurationReady();
  fireEvent.click(screen.getByRole("button", { name: "common.save" }));
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "common.save" })
    ).not.toBeInTheDocument()
  );
  fireEvent.click(screen.getByText("modelConfig.addDialog.toggleAll"));
  expect(api.validateModelOutlet).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "modelConfig.addDialog.addSelected" })
  );
  await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledOnce());
  expect(screen.getByPlaceholderText("sk-...")).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "modelConfig.addDialog.fetchModels" })
  ).toBeDisabled();
  finishFirstSave({ model_id: 11, config_revision: 1 });
  await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  expect(translate).toHaveBeenCalledWith(
    "modelConfig.addDialog.batchSuccess",
    expect.objectContaining({ created: 2 })
  );
  expect(api.validateModelOutlet).not.toHaveBeenCalled();
  expect(legacy.backfillDefaults).not.toHaveBeenCalled();
  expect(
    api.createModelOutlet.mock.calls.every(
      ([body]) =>
        body.parameter_values.temperature === 0.7 &&
        body.parameter_values.top_p === 1
    )
  ).toBe(true);
}, 30000);

it("places shared HTTP settings outside each model's body configuration", async () => {
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
          onClose={vi.fn()}
          onSuccess={vi.fn()}
        />
      </App>
    </QueryClientProvider>
  );
  fireEvent.click(screen.getByText("modelProfile.connectionSettings"));
  fireEvent.click(
    screen.getByRole("switch", { name: "modelProfile.skipTlsVerify" })
  );
  fireEvent.click(
    screen.getByRole("button", { name: "modelProfile.addHeader" })
  );
  fireEvent.change(screen.getByLabelText("modelProfile.headerName"), {
    target: { value: "X-Gateway" },
  });
  fireEvent.change(screen.getByLabelText("modelProfile.headerValue"), {
    target: { value: "controlled-header" },
  });
  fireEvent.change(screen.getByPlaceholderText("https://api.example.com/v1"), {
    target: { value: "https://models.invalid/v1" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "modelConfig.addDialog.fetchModels" })
  );
  await screen.findByText("model-a");
  expect(legacy.addProviderModel).toHaveBeenCalledWith(
    expect.objectContaining({
      sslVerify: false,
      httpHeaders: { "x-gateway": "controlled-header" },
    })
  );
  fireEvent.click(
    screen.getByRole("button", { name: "modelProfile.configureModel model-a" })
  );
  await waitForConfigurationReady();
  // The child dialog contains the body editor, but not another connection section.
  const { within } = await import("@testing-library/react");
  const dialog = screen.getAllByRole("dialog").at(-1)!;
  expect(
    within(dialog).queryByRole("switch", { name: "modelProfile.skipTlsVerify" })
  ).not.toBeInTheDocument();
  expect(
    within(dialog).getAllByText("modelProfile.extraParameters")[0]
  ).toBeVisible();
}, 30000);

it.each([false, true])(
  "keeps independent batch drafts and handles partial failure=%s",
  async (partialFailure) => {
    api.validateModelOutlet.mockResolvedValue({
      ok: false,
      check_receipt: "batch-failed-proof",
      error: {
        category: "MODEL_NOT_FOUND",
        scope: "connection",
        http_status: 404,
      },
    });
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
      check_receipt: "batch-failed-proof",
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
      api.createModelOutlet.mockResolvedValue({
        model_id: 12,
        config_revision: 1,
      });
      fireEvent.click(
        screen.getByRole("button", {
          name: "modelConfig.addDialog.addSelected",
        })
      );
      await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
      expect(
        api.createModelOutlet.mock.calls.map(([body]) => body.request_model_id)
      ).toEqual(["model-a", "model-b", "model-b"]);
    } else {
      await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    }
    expect(api.validateModelOutlet).toHaveBeenCalledTimes(2);
  },
  60000
);

it.each(["all", "partial", "stale"])(
  "D-02 reports profile duplicate names accurately (%s)",
  async (mode) => {
    translate.mockClear();
    api.createModelOutlet.mockImplementation(async (request) => {
      if (mode === "stale")
        throw new ApiError(409, "MODEL_OUTLET_VERSION_CONFLICT");
      if (mode === "all" || request.request_model_id === "model-b")
        throw new ApiError(
          "MODEL_DISPLAY_NAME_CONFLICT",
          "The display name is already in use."
        );
      return { model_id: 20, config_revision: 1 };
    });
    const onClose = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient()}>
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
    fireEvent.change(
      screen.getByPlaceholderText("https://api.example.com/v1"),
      { target: { value: "https://models.invalid/v1" } }
    );
    fireEvent.click(
      screen.getByRole("button", { name: "modelConfig.addDialog.fetchModels" })
    );
    await screen.findByText("model-a");
    fireEvent.click(screen.getByText("modelConfig.addDialog.toggleAll"));
    fireEvent.click(
      screen.getByRole("button", { name: "modelConfig.addDialog.addSelected" })
    );
    const key =
      mode === "all"
        ? "batchAllDuplicates"
        : mode === "partial"
          ? "batchPartialDuplicates"
          : "batchAllFailed";
    await screen.findByText(`modelConfig.addDialog.${key}`);
    if (mode === "all") {
      expect(translate).toHaveBeenCalledWith(
        `modelConfig.addDialog.${key}`,
        expect.objectContaining({ names: "model-a、model-b", total: 2 })
      );
    } else if (mode === "partial") {
      expect(translate).toHaveBeenCalledWith(
        `modelConfig.addDialog.${key}`,
        expect.objectContaining({ names: "model-b", duplicates: 1, count: 1 })
      );
    }
    expect(api.createModelOutlet).toHaveBeenCalledTimes(2);
    expect(api.validateModelOutlet).not.toHaveBeenCalled();
  },
  15000
);
