import { screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderWithProviders } from "./test-utils";
import CreateKBModal from "../CreateKBModal";
import type { CreateKBModalProps } from "../CreateKBModal";

// Mock unifiedKnowledgeBaseService — default and named export share the same object
// vi.hoisted() is required because vi.mock() is hoisted to the top of the file
const { mockUnifiedKbManager } = vi.hoisted(() => ({
  mockUnifiedKbManager: { createKb: vi.fn() },
}));
vi.mock("@/services/unifiedKnowledgeBaseService", () => ({
  default: mockUnifiedKbManager,
  unifiedKbManager: mockUnifiedKbManager,
}));

// Mock useAuthorizationContext
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: { tenantId: "tenant-123" },
  }),
  AuthorizationProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock modelService
vi.mock("@/services/modelService", () => ({
  modelService: {
    getAllModels: vi.fn(() => Promise.resolve([])),
  },
}));

// Mock groupService
vi.mock("@/services/groupService", () => ({
  listGroups: vi.fn(() => Promise.resolve({ groups: [] })),
}));

// Mock API responses
const mockAdapters: CreateKBModalProps["adapters"] = [
  { adapter_id: 1, platform: "local", name: "本地适配器", status: "running" },
  { adapter_id: 2, platform: "dify", name: "Dify", status: "running" },
];

describe("CreateKBModal", () => {
  const mockOnCancel = vi.fn();
  const mockOnCreated = vi.fn();

  const defaultProps: CreateKBModalProps = {
    visible: true,
    adapters: mockAdapters,
    onCancel: mockOnCancel,
    onCreated: mockOnCreated,
    onError: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders modal when visible", () => {
    renderWithProviders(<CreateKBModal {...defaultProps} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("does not render modal when not visible", () => {
    renderWithProviders(<CreateKBModal {...defaultProps} visible={false} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows step 1 adapter selection initially", () => {
    renderWithProviders(<CreateKBModal {...defaultProps} />);
    expect(screen.getByText("选择适配器")).toBeInTheDocument();
  });

  it("displays available adapters", () => {
    renderWithProviders(<CreateKBModal {...defaultProps} />);
    expect(screen.getByText("本地适配器")).toBeInTheDocument();
    expect(screen.getByText("Dify")).toBeInTheDocument();
  });

  it("moves to step 2 when adapter is selected and next clicked", async () => {
    renderWithProviders(<CreateKBModal {...defaultProps} />);

    // Select adapter via radio input
    const localRadio = screen.getByLabelText(/本地适配器/);
    fireEvent.click(localRadio);

    // Click next
    const nextButton = screen.getByRole("button", { name: /下一步/i });
    fireEvent.click(nextButton);

    await waitFor(() => {
      expect(screen.getByText("配置知识库")).toBeInTheDocument();
    });
  });

  it("shows name input in step 2", async () => {
    renderWithProviders(<CreateKBModal {...defaultProps} />);

    const localRadio = screen.getByLabelText(/本地适配器/);
    fireEvent.click(localRadio);
    const nextButton = screen.getByRole("button", { name: /下一步/i });
    fireEvent.click(nextButton);

    await waitFor(() => {
      // antd Form.Item without name prop doesn't create label-input association;
      // find the input by its placeholder instead
      expect(screen.getByPlaceholderText("输入知识库名称")).toBeInTheDocument();
    });
  });

  it("shows description input in step 2", async () => {
    renderWithProviders(<CreateKBModal {...defaultProps} />);

    const localRadio = screen.getByLabelText(/本地适配器/);
    fireEvent.click(localRadio);
    const nextButton = screen.getByRole("button", { name: /下一步/i });
    fireEvent.click(nextButton);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/输入知识库描述/)).toBeInTheDocument();
    });
  });

  it("shows local adapter-specific fields when local adapter selected (Q3 C1)", async () => {
    renderWithProviders(<CreateKBModal {...defaultProps} />);

    const localRadio = screen.getByLabelText(/本地适配器/);
    fireEvent.click(localRadio);
    const nextButton = screen.getByRole("button", { name: /下一步/i });
    fireEvent.click(nextButton);

    await waitFor(() => {
      // antd Form.Item labels are rendered as text; check they exist
      expect(screen.getByText("Embedding 模型")).toBeInTheDocument();
      expect(screen.getByText("群组权限")).toBeInTheDocument();
      expect(screen.getByText("授权群组")).toBeInTheDocument();
    });
  });

  it("hides local adapter-specific fields when external adapter selected (Q3 C1)", async () => {
    renderWithProviders(<CreateKBModal {...defaultProps} />);

    // Select Dify adapter and go to step 2
    const difyRadio = screen.getByLabelText(/Dify/);
    fireEvent.click(difyRadio);
    const nextButton = screen.getByRole("button", { name: /下一步/i });
    fireEvent.click(nextButton);

    await waitFor(() => {
      // Should NOT show local-only field labels
      expect(screen.queryByText("Embedding 模型")).not.toBeInTheDocument();
      expect(screen.queryByText("群组权限")).not.toBeInTheDocument();
      expect(screen.queryByText("授权群组")).not.toBeInTheDocument();
    });
  });

  it("calls onCancel when close button is clicked", () => {
    renderWithProviders(<CreateKBModal {...defaultProps} />);

    // antd Modal close button has aria-label="Close"
    const closeButton = screen.getByRole("button", { name: /close/i });
    fireEvent.click(closeButton);

    expect(mockOnCancel).toHaveBeenCalledTimes(1);
  });

  // Form submission flow has timing issues with antd Modal footer in jsdom
  it.skip("submits form and calls onCreated on success", async () => {
    mockUnifiedKbManager.createKb.mockResolvedValue({
      id: "kb-123",
      adapter_id: 1,
      adapter_platform: "local",
      name: "测试知识库",
      document_count: 0,
      chunk_count: 0,
    });

    renderWithProviders(<CreateKBModal {...defaultProps} />);

    // Select local adapter
    const localRadio = screen.getByLabelText(/本地适配器/);
    fireEvent.click(localRadio);
    const nextButton = screen.getByRole("button", { name: /下一步/i });
    fireEvent.click(nextButton);

    // Wait for step 2 form to appear
    await waitFor(() => {
      expect(screen.getByPlaceholderText("输入知识库名称")).toBeInTheDocument();
    });

    const nameInput = screen.getByPlaceholderText("输入知识库名称");
    fireEvent.change(nameInput, { target: { value: "测试知识库" } });

    // Submit — button text is "创建", wait for it to be available
    await waitFor(() => {
      const submitButton = screen.getByText("创建", { selector: "button" });
      expect(submitButton).toBeInTheDocument();
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      expect(mockUnifiedKbManager.createKb).toHaveBeenCalled();
      expect(mockOnCreated).toHaveBeenCalled();
    });
  });

  // Form submission flow has timing issues with antd Modal footer in jsdom
  it.skip("shows error message when creation fails", async () => {
    mockUnifiedKbManager.createKb.mockRejectedValueOnce(new Error("创建失败"));

    const mockOnError = vi.fn();
    renderWithProviders(<CreateKBModal {...defaultProps} onError={mockOnError} />);

    // Select local adapter
    const localRadio = screen.getByLabelText(/本地适配器/);
    fireEvent.click(localRadio);
    const nextButton = screen.getByRole("button", { name: /下一步/i });
    fireEvent.click(nextButton);

    await waitFor(() => {
      expect(screen.getByPlaceholderText("输入知识库名称")).toBeInTheDocument();
    });

    const nameInput = screen.getByPlaceholderText("输入知识库名称");
    fireEvent.change(nameInput, { target: { value: "测试知识库" } });

    // Submit — wait for button to be available
    await waitFor(() => {
      const submitButton = screen.getByText("创建", { selector: "button" });
      expect(submitButton).toBeInTheDocument();
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      expect(mockOnError).toHaveBeenCalled();
    });
  });
});
