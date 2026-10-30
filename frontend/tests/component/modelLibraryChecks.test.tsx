// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { App } from "antd";
import { createRef } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  ModelConfigSection,
  type ModelConfigSectionRef,
} from "../../app/[locale]/models/components/modelConfig";

const mocks = vi.hoisted(() => ({
  validate: vi.fn(),
  legacy: vi.fn(),
  models: vi.fn(),
  invalidate: vi.fn(),
  updateConfig: vi.fn(),
  saveConfig: vi.fn(),
  selected: "Kimi",
  type: "llm",
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { count?: number }) =>
      opts?.count === undefined ? key : `${key}:${opts.count}`,
  }),
}));
vi.mock("@/hooks/useConfig", () => ({
  CONFIG_QUERY_KEY: ["config"],
  useConfig: () => ({
    modelConfig: Object.fromEntries(
      [
        "llm",
        "embedding",
        "multiEmbedding",
        "rerank",
        "vlm",
        "vlm2",
        "vlm3",
        "vlm4",
        "tts",
        "stt",
      ].map((key) => [
        key,
        {
          modelName: key === "llm" ? mocks.selected : "",
          displayName: key === "llm" ? mocks.selected : "",
        },
      ])
    ),
    appConfig: {},
    updateModelConfig: mocks.updateConfig,
    saveConfig: mocks.saveConfig,
  }),
}));
vi.mock("@/hooks/permission/usePermission", () => ({
  usePermission: () => ({ can: () => true }),
}));
vi.mock("@/hooks/useConfirmModal", () => ({
  useConfirmModal: () => ({ confirm: vi.fn() }),
}));
vi.mock("@/hooks/model/useModelList", () => ({
  useModelList: () => ({ invalidate: mocks.invalidate }),
}));
vi.mock("@/components/permission/Can", () => ({
  Can: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/services/modelProfileService", () => ({
  updateModelOutlet: vi.fn(),
  validateModelOutlet: mocks.validate,
}));
vi.mock("@/services/modelService", () => ({
  modelService: { getAllModels: mocks.models, verifyCustomModel: mocks.legacy },
  ModelError: class extends Error {},
}));
vi.mock("../../app/[locale]/models/components/model/ModelAddDialog", () => ({
  ModelAddDialog: ({ onSuccess }: { onSuccess: (model: unknown) => void }) => (
    <button onClick={() => onSuccess({ name: "Kimi", type: "llm" })}>
      saved model callback
    </button>
  ),
}));
vi.mock(
  "../../app/[locale]/models/components/model/ModelOutletEditDialog",
  () => ({ ModelOutletEditDialog: () => null })
);
vi.mock("../../app/[locale]/models/components/model/ModelEditDialog", () => ({
  ModelEditDialog: () => null,
}));
vi.mock(
  "../../app/[locale]/models/components/model/ModelManagerDialog",
  () => ({ ModelManagerDialog: () => null })
);
vi.mock("../../app/[locale]/models/components/model/ModelSlotSelect", () => ({
  ModelSlotSelect: () => null,
  buildModelSlots: () => [],
}));
// Exercise the real page handlers and summary; only unrelated table rendering is replaced.
vi.mock("../../app/[locale]/models/components/model/ModelLibraryList", () => ({
  ModelLibraryList: ({ models, onCheck }: any) =>
    models.map((m: any) => (
      <button key={m.id} onClick={() => onCheck(m.displayName, m.type)}>
        check {m.displayName}: {m.connect_status}
      </button>
    )),
}));

beforeEach(() => {
  vi.resetAllMocks();
  mocks.selected = "Kimi";
  mocks.type = "llm";
  mocks.models.mockImplementation(async () => [
    {
      id: 37,
      name: "kimi-k3",
      displayName: "Kimi",
      type: mocks.type,
      profileSchemaVersion: 1,
      configRevision: 2,
    },
  ]);
});
function setup(ref?: React.Ref<ModelConfigSectionRef>) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <App>
        <ModelConfigSection ref={ref} skipVerification />
      </App>
    </QueryClientProvider>
  );
}
const failure = {
  ok: false,
  error: {
    category: "MODEL_REQUEST_INVALID",
    scope: "model",
    http_status: 400,
    message_source: "provider",
      message: "(400) invalid top_p: only 0.95 is allowed",
  },
};

it("RC-04 retains row probe details, retries the saved outlet and clears corrected failures", async () => {
  mocks.validate
    .mockResolvedValueOnce(failure)
    .mockResolvedValueOnce({ ok: true, error: null });
  setup();
  fireEvent.click(await screen.findByRole("button", { name: /check Kimi:/ }));
  await screen.findByRole(
    "button",
    { name: "modelProfile.checkIssues:1" },
    { timeout: 4000 }
  );
  fireEvent.click(
    screen.getByRole("button", { name: "modelProfile.checkIssues:1" })
  );
  expect(await screen.findByText(/\(400\) invalid top_p/)).toBeVisible();
  expect(mocks.validate).toHaveBeenCalledWith(
    { outlet_id: 37, expected_revision: 2 },
    undefined
  );
  expect(mocks.legacy).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "modelProfile.retryCheck" })
  );
  await waitFor(
    () =>
      expect(
        screen.queryByRole("button", { name: "modelProfile.checkIssues:1" })
      ).toBeNull(),
    { timeout: 4000 }
  );
  expect(
    screen.getByRole("button", { name: "check Kimi: available" })
  ).toBeVisible();
});

it("RC-04 default-slot checks use the same diagnostics endpoint and retain AbortSignal", async () => {
  mocks.validate.mockResolvedValue(failure);
  setup();
  await screen.findByRole("button", { name: /check Kimi:/ });
  fireEvent.click(
    screen.getByRole("button", { name: "modelConfig.button.checkConnectivity" })
  );
  await screen.findByRole(
    "button",
    { name: "modelProfile.checkIssues:1" },
    { timeout: 4000 }
  );
  expect(mocks.validate).toHaveBeenCalledWith(
    { outlet_id: 37, expected_revision: 2 },
    expect.any(AbortSignal)
  );
  expect(mocks.legacy).not.toHaveBeenCalled();
});

it("RC-04 preserves the legacy check for non-LLM models", async () => {
  mocks.selected = "";
  mocks.type = "embedding";
  mocks.legacy.mockResolvedValue(true);
  setup();
  fireEvent.click(await screen.findByRole("button", { name: /check Kimi:/ }));
  await screen.findByRole(
    "button",
    { name: "check Kimi: available" },
    { timeout: 4000 }
  );
  expect(mocks.legacy).toHaveBeenCalledWith("Kimi", "embedding", undefined);
  expect(mocks.validate).not.toHaveBeenCalled();
});

it("S-01 page refresh after saving never starts a hidden connectivity check", async () => {
  setup();
  await screen.findByRole("button", { name: /check Kimi:/ });
  fireEvent.click(screen.getByRole("button", { name: "saved model callback" }));
  await waitFor(() => expect(mocks.models).toHaveBeenCalledTimes(2));
  await new Promise((resolve) => setTimeout(resolve, 1300));
  expect(mocks.validate).not.toHaveBeenCalled();
  expect(mocks.legacy).not.toHaveBeenCalled();
});

it("Q-03 rapid checks for different rows never replace earlier clicks", async () => {
  mocks.models.mockResolvedValue(
    ["one", "two", "three", "four"].map((name, index) => ({
      id: index + 1,
      name,
      displayName: name,
      type: "llm",
      profileSchemaVersion: 1,
      configRevision: 1,
    }))
  );
  mocks.validate.mockResolvedValue({ ok: true, error: null });
  setup();
  await screen.findByRole("button", { name: /check one:/ });
  for (const name of ["one", "two", "three", "four"])
    fireEvent.click(
      screen.getByRole("button", { name: new RegExp(`check ${name}:`) })
    );
  await waitFor(() => expect(mocks.validate).toHaveBeenCalledTimes(4));
  expect(
    mocks.validate.mock.calls.map(([request]) => request.outlet_id)
  ).toEqual([1, 2, 3, 4]);
});

it("CS-04 default selection autosaves without probing the model", async () => {
  const ref = createRef<ModelConfigSectionRef>();
  setup(ref);
  await screen.findByRole("button", { name: /check Kimi:/ });
  await act(async () => {
    await ref.current!.simulateDropdownChange("llm", "main", "Kimi");
  });
  await waitFor(() => expect(mocks.saveConfig).toHaveBeenCalledOnce(), { timeout: 2000 });
  expect(mocks.updateConfig).toHaveBeenCalledOnce();
  expect(mocks.validate).not.toHaveBeenCalled();
  expect(mocks.legacy).not.toHaveBeenCalled();
});


it("CS-03 management API errors keep the previous completed result", async () => {
  mocks.models.mockResolvedValue([{ id: 37, name: "kimi-k3", displayName: "Kimi", type: "llm",
    profileSchemaVersion: 1, configRevision: 2, connect_status: "available" }]);
  mocks.validate.mockRejectedValue({ code: 403 });
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "check Kimi: available" }));
  await waitFor(() => expect(mocks.validate).toHaveBeenCalledOnce());
  await screen.findByRole("button", { name: "check Kimi: available" });
});

it("CS-03 cancelled check restores previous result", async () => {
  mocks.models.mockResolvedValue([{ id: 37, name: "kimi-k3", displayName: "Kimi", type: "llm",
    profileSchemaVersion: 1, configRevision: 2, connect_status: "available" }]);
  mocks.validate.mockRejectedValue(new DOMException("Cancelled", "AbortError"));
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "check Kimi: available" }));
  await waitFor(() => expect(mocks.validate).toHaveBeenCalledOnce());
  await screen.findByRole("button", { name: "check Kimi: available" });
});
