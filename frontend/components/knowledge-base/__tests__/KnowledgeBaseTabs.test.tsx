import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import KnowledgeBaseTabs from "../KnowledgeBaseTabs";
import type { AdapterSummary } from "../KnowledgeBaseTabs";

describe("KnowledgeBaseTabs", () => {
  const mockOnSelectAdapter = vi.fn();
  const mockOnTabChange = vi.fn();

  const mockAdapters: AdapterSummary[] = [
    {
      adapter_id: 1,
      platform: "local",
      name: "本地 Adapter",
      status: "running",
    },
    {
      adapter_id: 2,
      platform: "dify",
      name: "Dify Adapter",
      status: "running",
    },
    {
      adapter_id: 3,
      platform: "aidp",
      name: "AIDP Adapter",
      status: "error",
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders all three tabs", () => {
    render(
      <KnowledgeBaseTabs
        adapters={mockAdapters}
        activeTab="all"
        activeAdapterId={null}
        onSelectAdapter={mockOnSelectAdapter}
        onTabChange={mockOnTabChange}
      />
    );

    // Tab labels: "所有知识库", "本地知识库", "外部知识库"
    expect(screen.getByRole("tab", { name: /所有知识库/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /本地知识库/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /外部知识库/ })).toBeInTheDocument();
  });

  it("shows badge counts for each tab", () => {
    render(
      <KnowledgeBaseTabs
        adapters={mockAdapters}
        activeTab="all"
        activeAdapterId={null}
        onSelectAdapter={mockOnSelectAdapter}
        onTabChange={mockOnTabChange}
      />
    );

    // "所有知识库" tab has Badge count={3} (total adapters)
    // antd Badge renders the count as text inside a span
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("calls onTabChange when tab is clicked", () => {
    render(
      <KnowledgeBaseTabs
        adapters={mockAdapters}
        activeTab="all"
        activeAdapterId={null}
        onSelectAdapter={mockOnSelectAdapter}
        onTabChange={mockOnTabChange}
      />
    );

    const localTab = screen.getByRole("tab", { name: /本地知识库/ });
    fireEvent.click(localTab);

    expect(mockOnTabChange).toHaveBeenCalledWith("local");
  });

  it("shows adapter options when local tab is active", () => {
    render(
      <KnowledgeBaseTabs
        adapters={mockAdapters}
        activeTab="local"
        activeAdapterId={1}
        onSelectAdapter={mockOnSelectAdapter}
        onTabChange={mockOnTabChange}
      />
    );

    // Segmented option label: "${adapter.name} (${adapter.platform})"
    expect(screen.getByText(/本地 Adapter \(local\)/)).toBeInTheDocument();
  });

  it("shows adapter options when external tab is active", () => {
    render(
      <KnowledgeBaseTabs
        adapters={mockAdapters}
        activeTab="external"
        activeAdapterId={2}
        onSelectAdapter={mockOnSelectAdapter}
        onTabChange={mockOnTabChange}
      />
    );

    expect(screen.getByText(/Dify Adapter \(dify\)/)).toBeInTheDocument();
    expect(screen.getByText(/AIDP Adapter \(aidp\)/)).toBeInTheDocument();
  });

  it("disables non-running adapters", () => {
    render(
      <KnowledgeBaseTabs
        adapters={mockAdapters}
        activeTab="external"
        activeAdapterId={2}
        onSelectAdapter={mockOnSelectAdapter}
        onTabChange={mockOnTabChange}
      />
    );

    const aidpItem = screen.getByText(/AIDP Adapter \(aidp\)/);
    // Segmented control disables non-running adapters via CSS class
    const segmentedItem = aidpItem.closest(".ant-segmented-item");
    expect(segmentedItem).toBeTruthy();
    expect(segmentedItem).toHaveClass("ant-segmented-item-disabled");
  });

  it("calls onSelectAdapter when adapter is clicked", () => {
    const { container } = render(
      <KnowledgeBaseTabs
        adapters={mockAdapters}
        activeTab="local"
        activeAdapterId={null}
        onSelectAdapter={mockOnSelectAdapter}
        onTabChange={mockOnTabChange}
      />
    );

    // Click the Segmented item wrapper to trigger onChange
    // activeAdapterId is null so clicking any item triggers the callback
    const segmentedItems = container.querySelectorAll(".ant-segmented-item");
    let targetItem: Element | null = null;
    segmentedItems.forEach((item) => {
      if (item.textContent?.includes("本地 Adapter")) {
        targetItem = item;
      }
    });
    expect(targetItem).toBeTruthy();
    fireEvent.click(targetItem!);

    expect(mockOnSelectAdapter).toHaveBeenCalledWith(1);
  });

  it("highlights active adapter", () => {
    render(
      <KnowledgeBaseTabs
        adapters={mockAdapters}
        activeTab="local"
        activeAdapterId={1}
        onSelectAdapter={mockOnSelectAdapter}
        onTabChange={mockOnTabChange}
      />
    );

    const localAdapterItem = screen.getByText(/本地 Adapter \(local\)/);
    const segmentedItem = localAdapterItem.closest(".ant-segmented-item");
    expect(segmentedItem).toBeTruthy();
    expect(segmentedItem).toHaveClass("ant-segmented-item-selected");
  });

  it("hides adapter options when all tab is active", () => {
    render(
      <KnowledgeBaseTabs
        adapters={mockAdapters}
        activeTab="all"
        activeAdapterId={null}
        onSelectAdapter={mockOnSelectAdapter}
        onTabChange={mockOnTabChange}
      />
    );

    // Segmented renders as a radiogroup — should not be present when "all" tab is active
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
  });
});
