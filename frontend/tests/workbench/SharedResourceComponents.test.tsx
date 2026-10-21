// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WorkbenchResourceDrawer } from "@/features/workbench/components/WorkbenchResourceDrawer";
import { ResourceSelectionRow } from "@/features/workbench/components/ResourceSelectionRow";
import ResourceCard from "@/components/resource/ResourceCard";
import { ResourceSelectionGrid } from "@/features/workbench/components/ResourceSelectionGrid";
import {
  RESOURCE_PAGE_SIZE,
  resourcePage,
} from "@/features/workbench/components/ResourcePagination";

it("preserves the shared card's default button semantics and independent actions", async () => {
  const select = vi.fn();
  const action = vi.fn();
  render(
    <ResourceCard
      title="Resource"
      selected
      onClick={select}
      actions={<button onClick={action}>Edit</button>}
    />
  );
  expect(screen.getByRole("button", { name: "Resource" })).toHaveAttribute(
    "aria-pressed",
    "true"
  );
  await userEvent.click(screen.getByRole("button", { name: "Edit" }));
  expect(action).toHaveBeenCalledOnce();
  expect(select).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Resource" }));
  expect(select).toHaveBeenCalledOnce();
});

it("renders all picker results without default grid pagination, filters or create cards", () => {
  render(
    <ResourceSelectionGrid>
      {Array.from({ length: 21 }, (_, i) => (
        <ResourceCard key={i} title={`Resource ${i}`} onClick={vi.fn()} />
      ))}
    </ResourceSelectionGrid>
  );
  expect(screen.getAllByRole("button")).toHaveLength(21);
  expect(
    screen.getByRole("button", { name: "Resource 20" })
  ).toBeInTheDocument();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  expect(RESOURCE_PAGE_SIZE).toBe(10);
  expect(
    resourcePage(
      Array.from({ length: 12 }, (_, i) => i),
      2
    )
  ).toEqual([10, 11]);
});

it("text rows keep repository actions independent of selection and retain descriptive tags", async () => {
  const select = vi.fn(),
    action = vi.fn();
  render(
    <ResourceSelectionGrid layout="list">
      <ResourceSelectionRow
        title="Resource"
        description="Details"
        tags={["Finance"]}
        onClick={select}
        actions={<button onClick={action}>Import</button>}
      />
    </ResourceSelectionGrid>
  );
  const row = screen.getByRole("option", { name: "Resource" });
  expect(row).toHaveTextContent("Details");
  expect(row).toHaveTextContent("Finance");
  expect(row.querySelector("svg")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Import" }));
  expect(action).toHaveBeenCalledOnce();
  expect(select).not.toHaveBeenCalled();
  await userEvent.click(row);
  expect(select).toHaveBeenCalledOnce();
});

it("never caps the fixed header title column so title, subtitle and badge stay unclipped", () => {
  render(
    <ResourceCard
      fixedHeaderLayout
      title="Agent"
      subtitle="Current version v1.0.0"
      badge={<span>Main agent</span>}
      description="Description"
    />
  );
  const column = screen.getByRole("heading", { name: "Agent" }).parentElement;
  expect(column).toHaveClass("min-h-11");
  expect(column).not.toHaveClass("h-11");
  expect(column).toHaveClass("flex-col");
  expect(screen.getByText("Current version v1.0.0")).toBeInTheDocument();
  expect(screen.getByText("Main agent")).toBeInTheDocument();
});

it("Workbench picker reuses only Close/Confirm and offers exactly 10/20/50", async () => {
  const confirm = vi.fn(),
    cancel = vi.fn(),
    sizeChange = vi.fn();
  render(
    <WorkbenchResourceDrawer
      open
      title="Resources"
      onCancel={cancel}
      onConfirm={confirm}
      footerLeading={<button>Extra footer</button>}
      listContent={<p>Items</p>}
      picker={{
        listTitle: "Items",
        total: 21,
        page: 1,
        pageSize: 10,
        onPageChange: vi.fn(),
        onPageSizeChange: sizeChange,
      }}
    />
  );
  const footer = document.querySelector(
    '[data-picker-part="footer"]'
  ) as HTMLElement;
  expect(
    within(footer)
      .getAllByRole("button")
      .map((button) => button.textContent)
  ).toEqual(["关闭", "确认"]);
  expect(screen.queryByText("Extra footer")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("combobox"));
  expect(
    Array.from(
      document.querySelectorAll(".ant-select-item-option-content")
    ).map((el) => el.textContent)
  ).toEqual(["10 条/页", "20 条/页", "50 条/页"]);
  await userEvent.click(screen.getByText("20 条/页", { exact: true }));
  expect(sizeChange).toHaveBeenCalledOnce();
  expect(sizeChange.mock.calls[0][0]).toBe(20);
  expect(confirm).not.toHaveBeenCalled();
  await userEvent.click(within(footer).getByRole("button", { name: "关闭" }));
  expect(cancel).toHaveBeenCalledOnce();
});
