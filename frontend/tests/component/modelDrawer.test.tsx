// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { render, changePageSize } from "./resourceDrawerTestUtils";
import { ModelDrawer } from "@/components/resource-picker/ModelDrawer";
import type { ModelOption } from "@/types/modelConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));
vi.mock("@/hooks/model/useModelList", () => ({
  useModelList: () => ({ llmModels: [], isLoading: false, refetch: vi.fn() }),
}));

it("uses the selected page size for models while preserving selection", async () => {
  const models = Array.from({ length: 21 }, (_, index): ModelOption => ({
    id: index + 1,
    name: `Model ${index + 1}`,
    displayName: `Model ${index + 1}`,
    source: "custom",
    type: "llm",
    maxTokens: 4096,
    apiKey: "",
    apiUrl: "https://example.invalid/v1",
  }));
  const confirm = vi.fn();
  render(
    <ModelDrawer open onClose={vi.fn()} onConfirm={confirm} models={models} />
  );
  const list = document.querySelector("[data-resource-list]") as HTMLElement;
  expect(within(list).getAllByRole("checkbox")).toHaveLength(10);
  fireEvent.click(screen.getByRole("button", { name: "3" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Model 21" }));
  await changePageSize(20);
  expect(within(list).getAllByRole("checkbox")).toHaveLength(20);
  expect(screen.getByRole("checkbox", { name: "Model 1" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "2" }));
  expect(screen.getByRole("checkbox", { name: "Model 21" })).toHaveAttribute(
    "aria-checked",
    "true"
  );
  fireEvent.click(screen.getByRole("button", { name: "确认" }));
  expect(confirm).toHaveBeenCalledWith([
    expect.objectContaining({ id: "21", name: "Model 21" }),
  ]);
});
