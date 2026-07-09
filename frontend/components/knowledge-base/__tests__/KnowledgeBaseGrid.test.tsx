import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import KnowledgeBaseGrid from "../KnowledgeBaseGrid";
import type { KnowledgeBaseItem } from "../KnowledgeBaseGrid";

describe("KnowledgeBaseGrid", () => {
  const mockOnCreateClick = vi.fn();
  const mockOnKbClick = vi.fn();
  const mockOnKbDelete = vi.fn();

  const mockKbs: KnowledgeBaseItem[] = [
    {
      kb_id: "1",
      adapter_id: 1,
      adapter_platform: "local",
      name: "知识库 1",
      description: "描述 1",
      document_count: 10,
      chunk_count: 50,
      embedding_model: "model-a",
    },
    {
      kb_id: "2",
      adapter_id: 1,
      adapter_platform: "local",
      name: "知识库 2",
      description: "描述 2",
      document_count: 20,
      chunk_count: 100,
      embedding_model: "model-b",
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders KB cards when kbs are provided", () => {
    render(
      <KnowledgeBaseGrid
        kbs={mockKbs}
        loading={false}
        showCreateButton={true}
        onCreateClick={mockOnCreateClick}
        onKbClick={mockOnKbClick}
        onKbDelete={mockOnKbDelete}
      />
    );

    expect(screen.getByText("知识库 1")).toBeInTheDocument();
    expect(screen.getByText("知识库 2")).toBeInTheDocument();
  });

  it("renders create button when showCreateButton is true", () => {
    render(
      <KnowledgeBaseGrid
        kbs={mockKbs}
        loading={false}
        showCreateButton={true}
        onCreateClick={mockOnCreateClick}
        onKbClick={mockOnKbClick}
        onKbDelete={mockOnKbDelete}
      />
    );

    // Component renders "创建新知识库" text
    expect(screen.getByText("创建新知识库")).toBeInTheDocument();
  });

  it("does not render create button when showCreateButton is false", () => {
    render(
      <KnowledgeBaseGrid
        kbs={mockKbs}
        loading={false}
        showCreateButton={false}
        onCreateClick={mockOnCreateClick}
        onKbClick={mockOnKbClick}
        onKbDelete={mockOnKbDelete}
      />
    );

    expect(screen.queryByText("创建新知识库")).not.toBeInTheDocument();
  });

  it("calls onCreateClick when create button is clicked", () => {
    render(
      <KnowledgeBaseGrid
        kbs={mockKbs}
        loading={false}
        showCreateButton={true}
        onCreateClick={mockOnCreateClick}
        onKbClick={mockOnKbClick}
        onKbDelete={mockOnKbDelete}
      />
    );

    const createButton = screen.getByText("创建新知识库");
    // Click the parent Card element (the text is inside a Card)
    fireEvent.click(createButton);

    expect(mockOnCreateClick).toHaveBeenCalledTimes(1);
  });

  it("calls onKbClick when KB card is clicked", () => {
    render(
      <KnowledgeBaseGrid
        kbs={mockKbs}
        loading={false}
        showCreateButton={true}
        onCreateClick={mockOnCreateClick}
        onKbClick={mockOnKbClick}
        onKbDelete={mockOnKbDelete}
      />
    );

    const kbName = screen.getByText("知识库 1");
    fireEvent.click(kbName);

    expect(mockOnKbClick).toHaveBeenCalledWith("1", 1);
  });

  it("shows delete button on each card", () => {
    render(
      <KnowledgeBaseGrid
        kbs={mockKbs}
        loading={false}
        showCreateButton={true}
        onCreateClick={mockOnCreateClick}
        onKbClick={mockOnKbClick}
        onKbDelete={mockOnKbDelete}
      />
    );

    // DeleteOutlined icon renders with aria-label="delete"
    const deleteIcons = screen.getAllByLabelText("delete");
    expect(deleteIcons.length).toBeGreaterThanOrEqual(2);
  });

  it("calls onKbDelete when delete is confirmed", async () => {
    const { container } = render(
      <KnowledgeBaseGrid
        kbs={mockKbs}
        loading={false}
        showCreateButton={true}
        onCreateClick={mockOnCreateClick}
        onKbClick={mockOnKbClick}
        onKbDelete={mockOnKbDelete}
      />
    );

    // Find the delete icon and click its parent button to trigger Popconfirm
    const deleteIcons = screen.getAllByLabelText("delete");
    const deleteButton = deleteIcons[0].closest("button");
    expect(deleteButton).toBeTruthy();
    fireEvent.click(deleteButton!);

    // Popconfirm renders its popup in a portal; wait for the confirm button
    await waitFor(() => {
      // The Popconfirm okText is "删除"
      const popconfirm = container.querySelector(".ant-popconfirm") ??
        document.querySelector(".ant-popconfirm");
      expect(popconfirm).toBeTruthy();
    });

    // Click the Popconfirm OK button
    const okButton = document.querySelector(".ant-popconfirm-buttons .ant-btn-primary") as HTMLButtonElement
      ?? document.querySelector(".ant-popover-buttons .ant-btn-primary") as HTMLButtonElement;
    if (okButton) {
      fireEvent.click(okButton);
    }

    await waitFor(() => {
      expect(mockOnKbDelete).toHaveBeenCalledWith("1", 1);
    });
  });

  it("shows loading spinner when loading is true", () => {
    const { container } = render(
      <KnowledgeBaseGrid
        kbs={[]}
        loading={true}
        showCreateButton={true}
        onCreateClick={mockOnCreateClick}
        onKbClick={mockOnKbClick}
        onKbDelete={mockOnKbDelete}
      />
    );

    // antd v6 Spin uses aria-busy="true" and class ant-spin-spinning (no role="status")
    const spinner = container.querySelector(".ant-spin-spinning");
    expect(spinner).toBeInTheDocument();
  });

  it("shows empty state when loading is false and kbs is empty", () => {
    render(
      <KnowledgeBaseGrid
        kbs={[]}
        loading={false}
        showCreateButton={false}
        onCreateClick={mockOnCreateClick}
        onKbClick={mockOnKbClick}
        onKbDelete={mockOnKbDelete}
      />
    );

    // Component renders "暂无知识库" for empty state
    expect(screen.getByText("暂无知识库")).toBeInTheDocument();
  });

  it("displays KB metadata correctly", () => {
    render(
      <KnowledgeBaseGrid
        kbs={mockKbs}
        loading={false}
        showCreateButton={true}
        onCreateClick={mockOnCreateClick}
        onKbClick={mockOnKbClick}
        onKbDelete={mockOnKbDelete}
      />
    );

    // Description is rendered directly
    expect(screen.getByText("描述 1")).toBeInTheDocument();
    // Metadata is rendered as "文档数：10", "块数：50", "Embedding 模型：model-a"
    expect(screen.getByText(/文档数.*10/)).toBeInTheDocument();
    expect(screen.getByText(/块数.*50/)).toBeInTheDocument();
    expect(screen.getByText(/Embedding 模型.*model-a/)).toBeInTheDocument();
  });
});
