// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ResourceDrawer } from "@/components/resource-picker/ResourceDrawer";
import { ModelDrawer } from "@/components/resource-picker/ModelDrawer";
import type { ModelOption } from "@/types/modelConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/hooks/model/useModelList", () => ({
  useModelList: () => ({ llmModels: [], isLoading: false, refetch: vi.fn() }),
}));

const models = [1, 2, 3].map((id) => ({
  id,
  name: `Model ${id}`,
  source: "provider",
  displayName: `Model ${id}`,
})) as ModelOption[];

describe("AGENT-CONFIG-D1-005 resource drawer compatibility", () => {
  it("keeps the shared right drawer and its independent close/confirm callbacks", () => {
    const close = vi.fn();
    const confirm = vi.fn();
    render(
      <ResourceDrawer
        open
        title="Knowledge"
        searchPlaceholder="Search"
        listTitle="Resources"
        selected={[]}
        total={0}
        onClose={close}
        onConfirm={confirm}
      >
        <div>Existing controller</div>
      </ResourceDrawer>,
    );
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(document.querySelector(".ant-drawer-right")).not.toBeNull();
    expect(document.querySelector(".ant-drawer-mask")).not.toBeNull();
    expect(document.querySelector(".ant-drawer-content-wrapper")).toHaveStyle({
      width: "min(760px, 100vw)",
    });
    expect(screen.getByText("Existing controller").parentElement).toHaveClass(
      "overflow-y-auto",
    );
    expect(confirm).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "resourcePicker.confirm" }),
    );
    expect(confirm).toHaveBeenCalledOnce();
    expect(close).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getAllByRole("button", { name: "resourcePicker.close" })[0],
    );
    expect(close).toHaveBeenCalledOnce();
  });

  it("preserves ordered model drafts and commits only on confirmation", () => {
    const change = vi.fn();
    const props = {
      open: true,
      onClose: vi.fn(),
      models,
      selectedModelIds: [2, 1],
      onSelectionChange: change,
      selectedTrailing: <button type="button">Model priority</button>,
    };
    const { rerender } = render(<ModelDrawer {...props} />);
    expect(
      screen.getByRole("button", { name: "Model priority" }),
    ).toBeVisible();
    expect(change).not.toHaveBeenCalled();
    expect(
      screen.getAllByRole("button", { name: "resourcePicker.remove" })[0].parentElement,
    ).toHaveTextContent("Model 2");
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Model 3", exact: true }),
    );
    expect(change).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "resourcePicker.confirm" }));
    expect(change).toHaveBeenLastCalledWith([2, 1, 3]);
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Model 2", exact: true }),
    );
    fireEvent.click(screen.getByRole("button", { name: "resourcePicker.confirm" }));
    expect(change).toHaveBeenLastCalledWith([1, 3]);
    change.mockClear();
    rerender(<ModelDrawer {...props} disabled />);
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Model 3", exact: true }),
    );
    expect(change).not.toHaveBeenCalled();
  });

  it("keeps standalone model drawer selection local when uncontrolled", () => {
    render(<ModelDrawer open onClose={vi.fn()} models={models} />);
    const toggle = screen.getByRole("checkbox", { name: "Model 1", exact: true });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });
});
