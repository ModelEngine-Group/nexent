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
  verifyModelConfigConnectivity: vi.fn(),
  addCustomModel: vi.fn(),
  addManageProviderModel: vi.fn(),
  createManageTenantModel: vi.fn(),
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
        !Object.hasOwn(body.parameter_values, "temperature") &&
        !Object.hasOwn(body.parameter_values, "top_p")
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
      connect_status: "unavailable",
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

it.each([false, true])(
  "drops row check results after rediscovery, pending=%s",
  async (pending) => {
    let finish!: (value: { ok: boolean }) => void;
    api.validateModelOutlet.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
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
    fireEvent.change(
      screen.getByPlaceholderText("https://api.example.com/v1"),
      {
        target: { value: "https://models.invalid/v1" },
      }
    );
    const fetchModels = screen.getByRole("button", {
      name: "modelConfig.addDialog.fetchModels",
    });
    fireEvent.click(fetchModels);
    await screen.findByText("model-a");
    fireEvent.click(
      screen.getByRole("button", { name: "modelProfile.checkModel model-a" })
    );
    await waitFor(() => expect(api.validateModelOutlet).toHaveBeenCalledOnce());
    if (!pending) {
      finish({ ok: true });
      await waitFor(() =>
        expect(
          screen.getByRole("button", {
            name: "modelProfile.checkModel model-a",
          })
        ).toBeEnabled()
      );
    }
    fireEvent.click(fetchModels);
    await waitFor(() =>
      expect(legacy.addProviderModel).toHaveBeenCalledTimes(2)
    );
    await screen.findByText("model-a");
    if (pending) finish({ ok: true });
    fireEvent.click(screen.getByText("modelConfig.addDialog.toggleAll"));
    fireEvent.click(
      screen.getByRole("button", { name: "modelConfig.addDialog.addSelected" })
    );
    await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledTimes(2));
    expect(
      api.createModelOutlet.mock.calls.every(
        ([body]) => body.connect_status === undefined
      )
    ).toBe(true);
  },
  30000
);

it.each(["headers", "tls", "timeout"])(
  "AC-BC1/BC2 blocks unsupported %s settings on legacy rows and recovers after clearing them",
  async (setting) => {
    legacy.addProviderModel.mockResolvedValue([
      { id: "embed-only", model_type: "embedding" },
    ]);
    legacy.verifyModelConfigConnectivity.mockResolvedValue({
      connectivity: true,
    });
    legacy.addCustomModel.mockResolvedValue({});
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
    if (setting === "headers") {
      fireEvent.click(
        screen.getByRole("button", { name: "modelProfile.addHeader" })
      );
      fireEvent.change(screen.getByLabelText("modelProfile.headerName"), {
        target: { value: "X-Gateway" },
      });
      fireEvent.change(screen.getByLabelText("modelProfile.headerValue"), {
        target: { value: "controlled-header" },
      });
    } else if (setting === "tls") {
      fireEvent.click(
        screen.getByRole("switch", { name: "modelProfile.skipTlsVerify" })
      );
    } else {
      fireEvent.change(
        screen.getByRole("spinbutton", { name: "modelProfile.timeout" }),
        { target: { value: "45" } }
      );
    }
    fireEvent.change(
      screen.getByPlaceholderText("https://api.example.com/v1"),
      { target: { value: "https://models.invalid/v1" } }
    );
    fireEvent.click(
      screen.getByRole("button", { name: "modelConfig.addDialog.fetchModels" })
    );
    await screen.findByText("embed-only");
    expect(legacy.addProviderModel).toHaveBeenCalledWith(
      expect.objectContaining(
        setting === "headers"
          ? { httpHeaders: { "x-gateway": "controlled-header" } }
          : setting === "tls"
            ? { sslVerify: false }
            : { timeoutSeconds: 45 }
      )
    );
    expect(
      screen.getByRole("button", { name: "modelProfile.checkModel embed-only" })
    ).toBeDisabled();
    fireEvent.click(screen.getByText("modelConfig.addDialog.toggleAll"));
    expect(
      screen.getByRole("button", { name: "modelConfig.addDialog.batchCheck" })
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "modelConfig.addDialog.addSelected" })
    ).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "modelProfile.legacyConnectionUnsupported"
    );
    expect(legacy.verifyModelConfigConnectivity).not.toHaveBeenCalled();
    expect(legacy.addCustomModel).not.toHaveBeenCalled();
    if (setting === "headers")
      fireEvent.click(screen.getByRole("button", { name: "common.delete" }));
    else if (setting === "tls")
      fireEvent.click(
        screen.getByRole("switch", { name: "modelProfile.skipTlsVerify" })
      );
    else
      fireEvent.change(
        screen.getByRole("spinbutton", { name: "modelProfile.timeout" }),
        { target: { value: "120" } }
      );
    const check = screen.getByRole("button", {
      name: "modelProfile.checkModel embed-only",
    });
    expect(check).toBeEnabled();
    fireEvent.click(check);
    await waitFor(() =>
      expect(legacy.verifyModelConfigConnectivity).toHaveBeenCalledOnce()
    );
    fireEvent.click(
      screen.getByRole("button", { name: "modelConfig.addDialog.addSelected" })
    );
    await waitFor(() => expect(legacy.addCustomModel).toHaveBeenCalledOnce());
  }
);

it("AC-BC3 keeps extended connection settings on LLM rows after deselecting unsupported rows", async () => {
  legacy.addProviderModel.mockResolvedValue([
    { id: "llm-only", model_type: "llm" },
    { id: "embed-only", model_type: "embedding" },
  ]);
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
  fireEvent.change(
    screen.getByRole("spinbutton", { name: "modelProfile.timeout" }),
    { target: { value: "45" } }
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
  await screen.findByText("embed-only");
  fireEvent.click(screen.getByText("modelConfig.addDialog.toggleAll"));
  expect(
    screen.getByRole("button", { name: "modelConfig.addDialog.addSelected" })
  ).toBeDisabled();
  fireEvent.click(screen.getByText("embed-only", { exact: true }));
  const submit = screen.getByRole("button", {
    name: "modelConfig.addDialog.addSelected",
  });
  expect(submit).toBeEnabled();
  fireEvent.click(
    screen.getByRole("button", { name: "modelProfile.checkModel llm-only" })
  );
  await waitFor(() => expect(api.validateModelOutlet).toHaveBeenCalledOnce());
  fireEvent.click(submit);
  await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledOnce());
  for (const draft of [
    api.validateModelOutlet.mock.calls[0][0].draft,
    api.createModelOutlet.mock.calls[0][0],
  ]) {
    expect(draft).toMatchObject({
      request_model_id: "llm-only",
      http_headers: { "x-gateway": "controlled-header" },
      provider_info: { ssl_verify: false, timeout_seconds: 45 },
    });
  }
  expect(legacy.addCustomModel).not.toHaveBeenCalled();
});

it("AC-BC4 prevents extended settings from silently entering the managed-tenant legacy LLM path", async () => {
  legacy.addManageProviderModel.mockResolvedValue([
    { id: "managed-llm", model_type: "llm" },
  ]);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <App>
        <ModelAddDialog
          isOpen
          tenantId="other-tenant"
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
  fireEvent.change(screen.getByPlaceholderText("https://api.example.com/v1"), {
    target: { value: "https://models.invalid/v1" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "modelConfig.addDialog.fetchModels" })
  );
  await screen.findByText("managed-llm");
  fireEvent.click(screen.getByText("modelConfig.addDialog.toggleAll"));
  expect(
    screen.getByRole("button", { name: "modelProfile.checkModel managed-llm" })
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "modelConfig.addDialog.addSelected" })
  ).toBeDisabled();
  expect(legacy.createManageTenantModel).not.toHaveBeenCalled();
});

it.each([
  "available",
  "unavailable",
  "inflight",
  "unchanged",
  "resolved-change",
])(
  "AC-PC1 binds batch checks to resolved drafts across catalog loading (%s)",
  async (mode) => {
    let finishCatalog!: (value: { items: object[] }) => void;
    let finishCheck!: (value: { ok: boolean }) => void;
    api.listModelProfiles.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishCatalog = resolve;
        })
    );
    legacy.addProviderModel.mockResolvedValue([
      { id: "route-kimi-k3", model_type: "llm" },
    ]);
    let resolvedTopP = 1;
    api.previewModelProfile.mockImplementation(async (draft) => ({
      catalog_revision: "r1",
      selected: { model: draft.model_profile, provider: null },
      field_specs: [],
      parameter_values: {
        temperature: 0.7,
        top_p: draft.model_profile ? 0.95 : resolvedTopP,
      },
      capabilities: {
        context: {
          combined_window: null,
          input_limit: null,
          output_limit: null,
        },
      },
    }));
    if (mode === "inflight") {
      api.validateModelOutlet.mockImplementation(
        () =>
          new Promise((resolve) => {
            finishCheck = resolve;
          })
      );
    } else {
      api.validateModelOutlet.mockResolvedValue({ ok: mode !== "unavailable" });
    }
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
    fireEvent.change(
      screen.getByPlaceholderText("https://api.example.com/v1"),
      { target: { value: "https://models.invalid/v1" } }
    );
    fireEvent.click(
      screen.getByRole("button", { name: "modelConfig.addDialog.fetchModels" })
    );
    await screen.findByText("route-kimi-k3");
    fireEvent.click(
      screen.getByRole("button", {
        name: "modelProfile.checkModel route-kimi-k3",
      })
    );
    await waitFor(() => expect(api.validateModelOutlet).toHaveBeenCalledOnce());
    expect(
      api.validateModelOutlet.mock.calls[0][0].draft.parameter_values.top_p
    ).toBe(1);
    if (mode !== "inflight") {
      await waitFor(() =>
        expect(
          screen.getByRole("button", {
            name: "modelProfile.checkModel route-kimi-k3",
          })
        ).toBeEnabled()
      );
    }
    const changesMatch = ["available", "unavailable", "inflight"].includes(
      mode
    );
    await act(async () =>
      finishCatalog({
        items: changesMatch
          ? [{ key: "moonshot/kimi-k3", revision: 1, name: "Kimi K3" }]
          : [],
      })
    );
    if (changesMatch) {
      await screen.findByText("modelProfile.profileMatched");
      expect(
        screen.queryByText("modelProfile.checkFailed")
      ).not.toBeInTheDocument();
      await waitFor(() =>
        expect(
          screen.getByRole("button", {
            name: "modelProfile.checkModel route-kimi-k3",
          })
        ).toBeEnabled()
      );
    }
    if (mode === "inflight") await act(async () => finishCheck({ ok: true }));
    if (mode === "resolved-change") resolvedTopP = 0.8;
    fireEvent.click(screen.getByText("modelConfig.addDialog.toggleAll"));
    fireEvent.click(
      screen.getByRole("button", { name: "modelConfig.addDialog.addSelected" })
    );
    await waitFor(() => expect(api.createModelOutlet).toHaveBeenCalledOnce());
    expect(api.createModelOutlet.mock.calls[0][0]).toMatchObject({
      parameter_values: { top_p: changesMatch ? 0.95 : resolvedTopP },
    });
    expect(api.createModelOutlet.mock.calls[0][0].connect_status).toBe(
      mode === "unchanged" ? "available" : undefined
    );
    expect(api.validateModelOutlet).toHaveBeenCalledOnce();
  },
  20000
);

it("AC-RF2 retries failed discovery through the connection summary and clears the error", async () => {
  legacy.addProviderModel.mockRejectedValueOnce(
    new Error("controlled-discovery-failure")
  );
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
  fireEvent.change(screen.getByPlaceholderText("https://api.example.com/v1"), {
    target: { value: "https://models.invalid/v1" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "modelConfig.addDialog.fetchModels" })
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "modelProfile.checkIssues" })
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "modelProfile.retryCheck" })
  );
  await screen.findByText("model-a");
  expect(legacy.addProviderModel).toHaveBeenCalledTimes(2);
  expect(legacy.addProviderModel.mock.calls[1]).toEqual(
    legacy.addProviderModel.mock.calls[0]
  );
  expect(
    screen.queryByRole("button", { name: "modelProfile.checkIssues" })
  ).not.toBeInTheDocument();
  expect(api.validateModelOutlet).not.toHaveBeenCalled();
});
