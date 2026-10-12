import { describe, it, expect, vi, beforeAll, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import ResourceCardGrid from "@/components/resource/ResourceCardGrid";
import ResourceCard from "@/components/resource/ResourceCard";

beforeAll(() => {
  if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }),
    });
  }
});

afterEach(() => {
  cleanup();
});

type ResourceItem = { title: string; description: string };

describe("CreateResourceCard/ResourceCard/ResourceCardGrid", () => {
  it("UT-FE-AUTO-4124855DB982BD12 normalizes columns and renders the --resource-card-columns variable", () => {
    const { container, rerender } = render(
      <ResourceCardGrid items={[]} columns={0} rows={3} renderItem={() => null} />
    );
    let grid = container.querySelector('[style*="--resource-card-columns"]') as HTMLElement;
    expect(grid.style.getPropertyValue("--resource-card-columns")).toBe("4");

    rerender(<ResourceCardGrid items={[]} rows={3} renderItem={() => null} />);
    grid = container.querySelector('[style*="--resource-card-columns"]') as HTMLElement;
    expect(grid.style.getPropertyValue("--resource-card-columns")).toBe("4");

    rerender(<ResourceCardGrid items={[]} columns={3.9} rows={3} renderItem={() => null} />);
    grid = container.querySelector('[style*="--resource-card-columns"]') as HTMLElement;
    expect(grid.style.getPropertyValue("--resource-card-columns")).toBe("3");
  });

  it("renders the first visible slice within columns*rows slots", () => {
    const items: ResourceItem[] = Array.from({ length: 6 }, (_, i) => ({
      title: `Resource ${i + 1}`,
      description: `description ${i + 1}`,
    }));
    const { container } = render(
      <ResourceCardGrid
        items={items}
        columns={4}
        rows={3}
        renderItem={(item) => (
          <ResourceCard key={item.title} title={item.title} description={item.description} />
        )}
      />
    );

    const grid = container.querySelector('[style*="--resource-card-columns"]') as HTMLElement;
    expect(grid.style.getPropertyValue("--resource-card-columns")).toBe("4");
    expect(container.querySelectorAll("h2")).toHaveLength(6);
  });

  it("renders pagination with ceil(itemCount/itemsPerPage) and calls onPageChange", () => {
    const onPageChange = vi.fn();
    const items = Array.from({ length: 20 }, (_, i) => `item-${i + 1}`);
    const { container } = render(
      <ResourceCardGrid
        items={items}
        columns={2}
        rows={2}
        onPageChange={onPageChange}
        renderItem={(item, index) => (
          <div key={index} data-testid="grid-item">{item}</div>
        )}
      />
    );

    expect(container.querySelector(".ant-pagination")).not.toBeNull();

    const pageItems = container.querySelectorAll(".ant-pagination-item");
    expect(pageItems).toHaveLength(5);

    const active = container.querySelector(".ant-pagination-item-active");
    expect(active).not.toBeNull();
    expect(active?.textContent?.trim()).toBe("1");

    fireEvent.click(pageItems[1] as HTMLElement);
    expect(onPageChange).toHaveBeenCalledWith(2, 4);
  });

  it("renders the create placeholder with aria-label and occupies one slot", () => {
    const onCreate = vi.fn();
    const items = Array.from({ length: 4 }, (_, i) => `item-${i + 1}`);
    const { container } = render(
      <ResourceCardGrid
        items={items}
        columns={2}
        rows={2}
        createCardTitle="Create resource"
        onCreate={onCreate}
        renderItem={(item, index) => (
          <div key={index} data-testid="grid-item">{item}</div>
        )}
      />
    );

    const createButton = screen.getByRole("button", { name: "Create resource" });
    expect(createButton.getAttribute("aria-label")).toBe("Create resource");

    fireEvent.click(createButton);
    expect(onCreate).toHaveBeenCalledTimes(1);

    expect(container.querySelectorAll('[data-testid="grid-item"]')).toHaveLength(3);
  });

  it("links the interactive card button to the title and mirrors selected via aria-pressed", () => {
    const onClick = vi.fn();
    const { container } = render(
      <ResourceCard title="My Resource" description="desc" onClick={onClick} selected />
    );

    const heading = container.querySelector("h2");
    const button = container.querySelector("button") as HTMLButtonElement;

    expect(button.getAttribute("aria-labelledby")).toBe(heading?.getAttribute("id"));
    expect(button.getAttribute("aria-pressed")).toBe("true");

    const cardContainer = button.parentElement as HTMLElement;
    expect(cardContainer.className).toContain("border-blue-400");
    expect(cardContainer.className).toContain("ring-1");

    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("reflects selected=false and keeps the non-selected border", () => {
    const { container } = render(<ResourceCard title="T" selected={false} onClick={() => {}} />);
    const button = container.querySelector("button") as HTMLButtonElement;
    expect(button.getAttribute("aria-pressed")).toBe("false");

    const cardContainer = button.parentElement as HTMLElement;
    expect(cardContainer.className).not.toContain("border-blue-400");
    expect(cardContainer.className).toContain("border-slate-200");
  });

  it("exposes focus-visible ring styling and receives keyboard focus", () => {
    const { container } = render(<ResourceCard title="Focusable" onClick={() => {}} />);
    const button = container.querySelector("button") as HTMLButtonElement;

    expect(button.className).toContain("focus-visible:ring-2");

    button.focus();
    expect(document.activeElement).toBe(button);
  });

  it("renders filter buttons with aria-pressed and calls onFilterChange with the key", () => {
    const onFilterChange = vi.fn();
    const { container } = render(
      <ResourceCardGrid
        items={[]}
        filters={[
          { key: "all", label: "All" },
          { key: "mine", label: "Mine", count: 3 },
        ]}
        activeFilter="mine"
        onFilterChange={onFilterChange}
        renderItem={() => null}
      />
    );

    const buttons = container.querySelectorAll("button");
    expect(buttons).toHaveLength(2);
    expect(buttons[0].getAttribute("aria-pressed")).toBe("false");
    expect(buttons[1].getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(buttons[0]);
    expect(onFilterChange).toHaveBeenCalledWith("all");
  });

  it("controls search input, marks it readOnly without onSearchChange, and hides the toolbar without controls", async () => {
    function ControlledSearch({ onChange }: { onChange: (value: string) => void }) {
      const [value, setValue] = useState("");
      return (
        <ResourceCardGrid
          items={[]}
          search={value}
          onSearchChange={(next) => {
            setValue(next);
            onChange(next);
          }}
          renderItem={() => null}
        />
      );
    }

    const onSearchChange = vi.fn();
    const user = userEvent.setup();
    render(<ControlledSearch onChange={onSearchChange} />);

    const input = screen.getByRole("textbox") as HTMLInputElement;
    await user.type(input, "gpu");
    expect(onSearchChange).toHaveBeenLastCalledWith("gpu");
    expect(input.value).toBe("gpu");

    cleanup();

    render(<ResourceCardGrid items={[]} search="fixed" renderItem={() => null} />);
    const readOnlyInput = screen.getByRole("textbox") as HTMLInputElement;
    expect(readOnlyInput.readOnly).toBe(true);

    cleanup();

    const { container } = render(<ResourceCardGrid items={[]} renderItem={() => null} />);
    expect(container.querySelector("input")).toBeNull();
    expect(container.querySelector("button")).toBeNull();
  });

  it("renders the empty state and hides pagination when itemCount is 0", () => {
    const { container } = render(
      <ResourceCardGrid items={[]} total={0} renderItem={() => null} />
    );

    expect(container.querySelector(".ant-empty")).not.toBeNull();
    expect(container.querySelector(".ant-pagination")).toBeNull();
  });

  it("clamps an overflowing page back to totalPages via onPageChange", () => {
    const onPageChange = vi.fn();
    const items = Array.from({ length: 13 }, (_, i) => `item-${i + 1}`);

    render(
      <ResourceCardGrid
        items={items}
        page={5}
        columns={4}
        rows={3}
        onPageChange={onPageChange}
        renderItem={(item, index) => <div key={index}>{item}</div>}
      />
    );

    expect(onPageChange).toHaveBeenCalledWith(2);
  });
});
