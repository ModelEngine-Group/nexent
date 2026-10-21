// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ResourceDrawer } from "@/components/resource-picker/ResourceDrawer";
import {
  ResourceCollection,
  ResourceItem,
} from "@/components/resource-picker/ResourceItem";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

describe("ResourceDrawer", () => {
  it("disables refresh and exposes its busy state while discovery is running", () => {
    const refresh = vi.fn();
    render(
      <ResourceDrawer
        open
        title="Tools"
        listTitle="Results"
        onClose={vi.fn()}
        onRefresh={refresh}
        refreshLoading
      >
        <p>Results</p>
      </ResourceDrawer>
    );
    const button = screen.getByRole("button", { name: "刷新" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    fireEvent.click(button);
    expect(refresh).not.toHaveBeenCalled();
  });
  it("does not expose tag management and retains the list refresh action", () => {
    const refresh = vi.fn();
    render(
      <ResourceDrawer
        open
        title="Resources"
        listTitle="Results"
        onClose={vi.fn()}
        onRefresh={refresh}
      >
        <p>Results</p>
      </ResourceDrawer>
    );
    expect(
      screen.queryByRole("button", { name: /管理标签|标签管理/ })
    ).toBeNull();
    const heading = document.querySelector(
      '[data-picker-part="list-heading"]'
    ) as HTMLElement;
    fireEvent.click(within(heading).getByRole("button", { name: "刷新" }));
    expect(refresh).toHaveBeenCalledOnce();
  });
  it("forwards page navigation using the supplied page size", () => {
    const page = vi.fn();
    render(
      <ResourceDrawer
        open
        title="Resources"
        onClose={vi.fn()}
        total={30}
        page={2}
        pageSize={6}
        onPageChange={page}
      >
        <p>Results</p>
      </ResourceDrawer>
    );
    fireEvent.click(screen.getByRole("button", { name: "3" }));
    expect(page).toHaveBeenCalledWith(3);
    expect(
      document.querySelectorAll("[data-resource-pagination]")
    ).toHaveLength(1);
    expect(document.querySelector("[data-resource-list]")).toHaveClass(
      "overflow-y-auto",
      "flex-1"
    );
  });
  it("renders only supplied regions and keeps controls outside the scrolling list", () => {
    render(
      <ResourceDrawer
        open
        title="Resources"
        onClose={vi.fn()}
        controlsContent={<input aria-label="Custom filter" />}
      >
        <p>Results</p>
      </ResourceDrawer>
    );
    expect(document.querySelector('[data-picker-part="search"]')).toBeNull();
    expect(document.querySelector('[data-picker-part="selection"]')).toBeNull();
    expect(
      document.querySelector('[data-picker-part="pagination"]')
    ).toBeNull();
    expect(
      document.querySelector('[data-picker-part="list-content"]')
    ).not.toContainElement(screen.getByLabelText("Custom filter"));
    expect(screen.getByText("Results")).toBeInTheDocument();
    expect(
      screen.getByRole("dialog", { name: "Resources" })
    ).toBeInTheDocument();
  });

  it("accepts external categories/data and resets controlled search on reopen", () => {
    function Fixture() {
      const [category, setCategory] = useState("mine");
      const [keyword, setKeyword] = useState("");
      return (
        <ResourceDrawer
          open
          title="Agents"
          onClose={() => setKeyword("")}
          searchPlaceholder="Search resources"
          keyword={keyword}
          onSearch={setKeyword}
          tabs={[
            { key: "mine", label: "Mine" },
            { key: "repository", label: "Repository" },
          ]}
          activeTab={category}
          onTabChange={setCategory}
        >
          {category === "mine" ? "My agents" : "Repository agents"}
        </ResourceDrawer>
      );
    }
    render(<Fixture />);
    fireEvent.click(screen.getByRole("button", { name: "Repository" }));
    expect(screen.getByText("Repository agents")).toBeInTheDocument();
    const input = screen.getByPlaceholderText("Search resources");
    fireEvent.change(input, { target: { value: "query" } });
    expect(input).toHaveValue("query");
    fireEvent.click(screen.getAllByRole("button", { name: "关闭" })[0]);
    expect(input).toHaveValue("");
  });

  it("disables resource interactions and submit while allowing cancel when read-only", () => {
    const toggle = vi.fn();
    const cancel = vi.fn();
    render(
      <ResourceDrawer
        open
        disabled
        title="Resources"
        onClose={cancel}
        onConfirm={vi.fn()}
      >
        <button onClick={toggle}>Select resource</button>
      </ResourceDrawer>
    );
    expect(
      screen.getByRole("button", { name: "Select resource" })
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "确认" })).toBeDisabled();
    fireEvent.click(screen.getAllByRole("button", { name: "关闭" })[0]);
    expect(cancel).toHaveBeenCalledOnce();
    expect(toggle).not.toHaveBeenCalled();
  });
});

describe("ResourceItem", () => {
  const item = {
    key: "knowledge:1",
    name: "Handbook",
    description: "Policies",
    tags: ["HR"],
    badges: ["Local"],
    metadata: [{ key: "documents", value: 128, label: "documents" }],
    raw: { id: 1 },
  };

  it("retains selection and metadata across list/card layout and keeps actions independent", () => {
    const toggle = vi.fn();
    const configure = vi.fn();
    const props = {
      item,
      selected: true,
      onToggle: toggle,
      slots: {
        renderActions: () => <button onClick={configure}>Configure</button>,
      },
    };
    const view = render(
      <ResourceCollection>
        <ResourceItem {...props} />
      </ResourceCollection>
    );
    expect(screen.getByText("128 documents")).toBeInTheDocument();
    const option = screen.getByRole("option", { name: "Handbook" });
    expect(option.firstElementChild).toHaveAttribute("data-resource-checkbox");
    expect(within(option).getByText("HR").parentElement).toBe(
      within(option).getByText("Handbook").parentElement
    );
    expect(screen.getByRole("listbox")).toHaveAttribute(
      "aria-multiselectable",
      "true"
    );
    fireEvent.click(screen.getByRole("button", { name: "Configure" }));
    expect(configure).toHaveBeenCalledOnce();
    expect(toggle).not.toHaveBeenCalled();
    const row = option.closest("[data-resource-view]")!;
    expect(row).toContainElement(
      screen.getByRole("button", { name: "Configure" })
    );
    expect(row).toContainElement(screen.getByText("128 documents"));
    expect(row).toHaveClass("hover:bg-primary/10");
    expect(option).not.toHaveClass("hover:bg-muted/50");
    view.rerender(
      <ResourceCollection viewMode="card">
        <ResourceItem {...props} viewMode="card" />
      </ResourceCollection>
    );
    expect(screen.getByRole("option", { name: "Handbook" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(
      document.querySelector('[data-resource-view="card"]')
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: "Handbook" }));
    expect(toggle).toHaveBeenCalledOnce();
  });

  it("replaces only the metadata slot and blocks disabled selection", () => {
    const toggle = vi.fn();
    const details = vi.fn();
    render(
      <ResourceItem
        item={item}
        onToggle={toggle}
        disabled
        disabledReason="Unavailable"
        slots={{
          renderMetadata: (resource, context) => (
            <button onClick={details}>
              {resource.raw.id}: {context.viewMode}
            </button>
          ),
        }}
      />
    );
    expect(screen.queryByText("128 documents")).toBeNull();
    expect(screen.getByText("Policies")).toBeInTheDocument();
    const option = screen.getByRole("option", { name: "Handbook" });
    expect(within(option).getByText("Unavailable")).toBeInTheDocument();
    expect(option).toBeDisabled();
    fireEvent.click(option);
    fireEvent.click(screen.getByRole("button", { name: "1: list" }));
    expect(details).toHaveBeenCalledOnce();
    expect(toggle).not.toHaveBeenCalled();
  });
});
