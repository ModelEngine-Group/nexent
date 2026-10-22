// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
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

const verifyCustomModel = vi.fn().mockResolvedValue(true);

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
    verifyCustomModel: (...args: unknown[]) => verifyCustomModel(...args),
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

it("keeps a superseded row probe from sticking in the detecting state", async () => {
  const user = userEvent.setup();
  renderSection();

  const actions = await screen.findAllByRole("button", {
    name: "检测连通性",
  });
  expect(actions).toHaveLength(2);

  // Two different rows within the 1s shared-debounce window: only the last
  // click actually probes. Row A must keep its stored status instead of
  // flashing into a never-resolving 检测中.
  await user.click(actions[0]);
  await user.click(actions[1]);

  await waitFor(
    () => {
      expect(within(rowOf("Model B")).getByText("可用")).toBeInTheDocument();
    },
    { timeout: 3000 }
  );
  expect(
    within(rowOf("Model A")).queryByText("检测中")
  ).not.toBeInTheDocument();
  expect(within(rowOf("Model A")).getByText("可用")).toBeInTheDocument();
  expect(verifyCustomModel).toHaveBeenCalledTimes(1);
  expect(verifyCustomModel).toHaveBeenCalledWith("Model B", "embedding");
});

it("collapses rapid re-clicks of the same row into a single probe", async () => {
  const user = userEvent.setup();
  renderSection();

  const actions = await screen.findAllByRole("button", {
    name: "检测连通性",
  });
  await user.click(actions[0]);
  await user.click(actions[0]);

  await waitFor(
    () => {
      expect(verifyCustomModel).toHaveBeenCalledTimes(1);
    },
    { timeout: 3000 }
  );
  await waitFor(
    () => {
      expect(within(rowOf("Model A")).getByText("可用")).toBeInTheDocument();
    },
    { timeout: 3000 }
  );
});
