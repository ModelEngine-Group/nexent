// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ResourceCardGrid from "@/components/resource/ResourceCardGrid";
import ResourceCard from "@/components/resource/ResourceCard";
import { REPOSITORY_PAGE_SIZE } from "@/const/resource";

const items = Array.from({ length: 25 }, (_, index) => index + 1);
const renderItem = (id: number) => (
  <ResourceCard key={id} title={`Item ${id}`} />
);

describe("repository pagination", () => {
  it("keeps twelve results when visual rows and columns change", () => {
    const props = {
      items,
      pageSize: REPOSITORY_PAGE_SIZE,
      renderItem,
      onPageChange: vi.fn(),
    };
    const { rerender, container } = render(
      <ResourceCardGrid {...props} columns={4} rows={3} />
    );
    expect(screen.getAllByRole("heading")).toHaveLength(12);
    rerender(<ResourceCardGrid {...props} columns={2} rows={1} />);
    expect(screen.getAllByRole("heading")).toHaveLength(12);
    expect(screen.getByRole("heading", { name: "Item 12" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Item 13" })).toBeNull();
    expect(container.querySelector<HTMLElement>(".grid")?.style.height).toBe(
      ""
    );
    fireEvent.click(screen.getByTitle("2"));
    expect(props.onPageChange).toHaveBeenCalledWith(2, 12);
    rerender(<ResourceCardGrid {...props} page={3} columns={2} rows={1} />);
    expect(screen.getAllByRole("heading")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Item 25" })).toBeVisible();
  });

  it("preserves later server pages without slicing the results again", () => {
    render(
      <ResourceCardGrid
        items={items.slice(12, 24)}
        page={2}
        total={25}
        pageSize={12}
        paginateItems={false}
        renderItem={renderItem}
      />
    );
    expect(screen.getAllByRole("heading")).toHaveLength(12);
    expect(screen.getByRole("heading", { name: "Item 13" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Item 24" })).toBeVisible();
  });

  it("retains explicit sizing and create-card slots for existing callers", () => {
    const { container } = render(
      <ResourceCardGrid
        items={items}
        columns={2}
        rows={2}
        gridHeight={500}
        createCard={<button>Create</button>}
        renderItem={renderItem}
      />
    );
    expect(screen.getAllByRole("heading")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Create" })).toBeVisible();
    expect(container.querySelector<HTMLElement>(".grid")).toHaveStyle({
      height: "500px",
    });
  });

  it("keeps twelve mine card slots including the create entry across viewport layouts", () => {
    const props = {
      items,
      pageSize: REPOSITORY_PAGE_SIZE,
      createCard: <button>Create</button>,
      renderItem,
    };
    const { rerender, container } = render(
      <ResourceCardGrid {...props} columns={4} rows={3} />
    );
    expect(screen.getAllByRole("heading")).toHaveLength(11);
    rerender(<ResourceCardGrid {...props} columns={1} rows={1} />);
    expect(screen.getAllByRole("heading")).toHaveLength(11);
    expect(screen.getByRole("button", { name: "Create" })).toBeVisible();
    expect(container.querySelector<HTMLElement>(".grid")?.style.height).toBe(
      ""
    );
  });

  it("uses responsive flow layout and preserves the empty state", () => {
    const onPageChange = vi.fn();
    const { container } = render(
      <ResourceCardGrid
        items={[]}
        page={5}
        onPageChange={onPageChange}
        renderItem={renderItem}
        emptyState={<span>No matches</span>}
      />
    );
    expect(screen.getByText("No matches")).toBeVisible();
    expect(container.querySelector<HTMLElement>(".grid")).toHaveClass(
      "md:grid-cols-2",
      "lg:grid-cols-3",
      "xl:grid-cols-4"
    );
    expect(container.querySelector<HTMLElement>(".grid")?.style.height).toBe(
      ""
    );
    expect(onPageChange).toHaveBeenCalledWith(1);
    expect(container.querySelector(".ant-pagination")).toBeNull();
  });
});
