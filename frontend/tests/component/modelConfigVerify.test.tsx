// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ModelConfigSection } from "../../app/[locale]/models/components/modelConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue ?? key,
  }),
}));

vi.mock("@/hooks/useConfig", () => ({
  CONFIG_QUERY_KEY: ["config"],
  useConfig: () => ({
    modelConfig: {
      llm: { displayName: "" },
      embedding: { displayName: "" },
      multiEmbedding: { displayName: "" },
      rerank: { displayName: "" },
      vlm: { displayName: "" },
      stt: { displayName: "" },
      tts: { displayName: "" },
    },
    updateModelConfig: vi.fn(),
    appConfig: {},
    saveConfig: vi.fn(async () => true),
  }),
}));

vi.mock("@/hooks/permission/usePermission", () => ({
  usePermission: () => ({ can: () => true }),
}));

vi.mock("@/hooks/model/useModelList", () => ({
  useModelList: () => ({ invalidate: vi.fn(async () => {}) }),
}));

const verifyCustomModel = vi.fn();
let resolveProbe: () => void;
beforeEach(() => {
  verifyCustomModel.mockReset();
  const result = new Promise((resolve) => {
    resolveProbe = () => resolve({ connectivity: true });
  });
  verifyCustomModel.mockReturnValue(result);
});

vi.mock("@/services/modelService", () => ({
  modelService: {
    getAllModels: vi.fn().mockResolvedValue([
      {
        id: 1,
        name: "vendor/model-a",
        displayName: "Model A",
        type: "llm",
        source: "silicon",
        apiKey: "",
        apiUrl: "https://a.example.com/v1",
        maxTokens: 4096,
        connect_status: "available",
      },
      {
        id: 2,
        name: "vendor/model-b",
        displayName: "Model B",
        type: "embedding",
        source: "silicon",
        apiKey: "",
        apiUrl: "https://b.example.com/v1",
        maxTokens: 1024,
        connect_status: "not_detected",
      },
    ]),
    verifyCustomModelDetail: (...args: unknown[]) => verifyCustomModel(...args),
    deleteCustomModel: vi.fn(),
    updateSingleModel: vi.fn(),
  },
  ModelError: class ModelError extends Error {},
}));

vi.mock("@/services/memoryService", () => ({
  loadMemoryConfig: vi.fn().mockResolvedValue({ memoryEnabled: false }),
}));

function renderSection() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <App>
        <ModelConfigSection />
      </App>
    </QueryClientProvider>
  );
}

function rowOf(displayName: string): HTMLElement {
  const nameEl = screen.getByText(displayName);
  return nameEl.closest("div.flex.flex-col.gap-3") as HTMLElement;
}

it("lights up every clicked row and probes them all", async () => {
  const user = userEvent.setup();
  renderSection();

  const actions = await screen.findAllByRole("button", {
    name: "检测连通性",
  });
  expect(actions).toHaveLength(2);

  // Keep both probes pending while checking the row feedback.
  await user.click(actions[0]);
  expect(within(rowOf("Model A")).getByText("检测中")).toBeInTheDocument();
  await user.click(actions[1]);
  expect(within(rowOf("Model B")).getByText("检测中")).toBeInTheDocument();

  await act(async () => resolveProbe());
  await waitFor(
    () => {
      expect(within(rowOf("Model A")).getByText("已连通")).toBeInTheDocument();
      expect(within(rowOf("Model B")).getByText("已连通")).toBeInTheDocument();
    },
    { timeout: 3000 }
  );
  expect(verifyCustomModel).toHaveBeenCalledTimes(2);
  expect(verifyCustomModel).toHaveBeenCalledWith("Model A", "llm", undefined);
  expect(verifyCustomModel).toHaveBeenCalledWith("Model B", "embedding", undefined);
});

it("collapses rapid re-clicks of the same row into a single probe", async () => {
  const user = userEvent.setup();
  renderSection();

  const actions = await screen.findAllByRole("button", {
    name: "检测连通性",
  });
  await user.click(actions[0]);
  // The pending row does not queue a second probe.
  expect(within(rowOf("Model A")).getByText("检测中")).toBeInTheDocument();
  await user.click(actions[0]);
  await act(async () => resolveProbe());

  await waitFor(
    () => {
      expect(verifyCustomModel).toHaveBeenCalledTimes(1);
    },
    { timeout: 3000 }
  );
  await waitFor(
    () => {
      expect(within(rowOf("Model A")).getByText("已连通")).toBeInTheDocument();
    },
    { timeout: 3000 }
  );
});
