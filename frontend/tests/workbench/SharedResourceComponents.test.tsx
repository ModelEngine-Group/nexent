import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ResourceCard from "@/components/resource/ResourceCard";
import { ResourceSelectionGrid } from "@/features/workbench/components/ResourceSelectionGrid";

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
});
