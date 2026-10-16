import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  expect(RESOURCE_PAGE_SIZE).toBe(6);
  expect(
    resourcePage(
      Array.from({ length: 12 }, (_, i) => i),
      2
    )
  ).toEqual([6, 7, 8, 9, 10, 11]);
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
