import { screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderWithProviders, createTestQueryClient } from "./test-utils";
import UnifiedKnowledgeBaseView from "../UnifiedKnowledgeBaseView";
import type { AdapterInfo, KbSummary } from "@/types/unifiedKnowledgeBase";

// Mock unifiedKnowledgeBaseService
// vi.hoisted() is required because vi.mock() is hoisted to the top of the file
const { mockUnifiedKbManager } = vi.hoisted(() => ({
  mockUnifiedKbManager: {
    listAllAdapters: vi.fn(),
    listKbsInAdapter: vi.fn(),
    listAllKbs: vi.fn(),
    deleteKb: vi.fn(),
    createKb: vi.fn(),
    listDocuments: vi.fn(),
    uploadDocuments: vi.fn(),
    deleteDocument: vi.fn(),
    getDocumentStatus: vi.fn(),
  },
}));
vi.mock("@/services/unifiedKnowledgeBaseService", () => ({
  default: mockUnifiedKbManager,
  unifiedKbManager: mockUnifiedKbManager,
}));

// Mock useAuthorizationContext (needed by CreateKBModal rendered as child)
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: { tenantId: "tenant-123" },
  }),
  AuthorizationProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock modelService (needed by CreateKBModal)
vi.mock("@/services/modelService", () => ({
  modelService: {
    getAllModels: vi.fn(() => Promise.resolve([])),
  },
}));

// Mock groupService (needed by CreateKBModal)
vi.mock("@/services/groupService", () => ({
  listGroups: vi.fn(() => Promise.resolve({ groups: [] })),
}));

// Mock window.open
vi.stubGlobal("open", vi.fn());

const mockAdapters: AdapterInfo[] = [
  { adapter_id: 1, platform: "local", name: "本地适配器", status: "running", enabled: true },
  { adapter_id: 2, platform: "dify", name: "Dify", status: "running", enabled: true },
];

const mockKbSummaries: KbSummary[] = [
  {
    id: "kb-1",
    adapter_id: 1,
    adapter_platform: "local",
    name: "知识库 1",
    description: "描述 1",
    document_count: 10,
    chunk_count: 50,
    embedding_model: "text-embedding-v2",
  },
  {
    id: "kb-2",
    adapter_id: 2,
    adapter_platform: "dify",
    name: "知识库 2",
    description: "描述 2",
    document_count: 20,
    chunk_count: 100,
    embedding_model: "text-embedding-v2",
  },
];

describe("UnifiedKnowledgeBaseView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default mock implementations
    mockUnifiedKbManager.listAllAdapters.mockResolvedValue(mockAdapters);
    mockUnifiedKbManager.listAllKbs.mockResolvedValue([]);
    mockUnifiedKbManager.listKbsInAdapter.mockResolvedValue({ kbs: [], total: 0, page: 1, pageSize: 20 });
  });

  it("renders without crashing", async () => {
    renderWithProviders(<UnifiedKnowledgeBaseView />);

    // Header title "知识库管理" should be present immediately
    await waitFor(() => {
      expect(screen.getByText("知识库管理")).toBeInTheDocument();
    });
  });

  it("shows adapter tabs", async () => {
    renderWithProviders(<UnifiedKnowledgeBaseView />);

    // Wait for adapters to load and tabs to render with adapter names
    await waitFor(() => {
      // Tabs: "所有知识库", "本地知识库", "外部知识库"
      expect(screen.getByRole("tab", { name: /所有知识库/ })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /本地知识库/ })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /外部知识库/ })).toBeInTheDocument();
    });
  });

  it("shows knowledge base grid", async () => {
    mockUnifiedKbManager.listAllKbs.mockResolvedValue(mockKbSummaries);

    renderWithProviders(<UnifiedKnowledgeBaseView />);

    await waitFor(() => {
      expect(screen.getByText("知识库 1")).toBeInTheDocument();
      expect(screen.getByText("知识库 2")).toBeInTheDocument();
    });
  });

  it("opens create KB modal when create button clicked", async () => {
    mockUnifiedKbManager.listAllKbs.mockResolvedValue(mockKbSummaries);

    renderWithProviders(<UnifiedKnowledgeBaseView />);

    // Wait for grid to render
    await waitFor(() => {
      expect(screen.getByText("知识库 1")).toBeInTheDocument();
    });

    // The "创建新知识库" card is shown when activeTab !== "all"
    // Default tab is "all" which doesn't show create button
    // Switch to local tab first
    const localTab = screen.getByRole("tab", { name: /本地知识库/ });
    fireEvent.click(localTab);

    await waitFor(() => {
      expect(screen.getByText("创建新知识库")).toBeInTheDocument();
    });

    const createButton = screen.getByText("创建新知识库");
    fireEvent.click(createButton);

    await waitFor(() => {
      // CreateKBModal opens with title "创建知识库"
      expect(screen.getByText("创建知识库")).toBeInTheDocument();
    });
  });

  it("opens detail drawer when KB card clicked", async () => {
    mockUnifiedKbManager.listAllKbs.mockResolvedValue(mockKbSummaries);

    renderWithProviders(<UnifiedKnowledgeBaseView />);

    // Wait for grid data and click the KB card in one waitFor to avoid race conditions
    await waitFor(() => {
      const kbCard = screen.getByText("知识库 1");
      expect(kbCard).toBeInTheDocument();
      fireEvent.click(kbCard);
    });

    // KBDetailDrawer opens — it renders a Drawer with role="dialog"
    await waitFor(() => {
      const dialogs = screen.getAllByRole("dialog");
      expect(dialogs.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("opens adapter registration modal when register button clicked", async () => {
    renderWithProviders(<UnifiedKnowledgeBaseView showRegisterButton={true} />);

    // Click the register button
    await waitFor(() => {
      const registerButton = screen.getByRole("button", { name: /注册外部适配器/i });
      expect(registerButton).toBeInTheDocument();
      fireEvent.click(registerButton);
    });

    // AdapterRegistrationModal opens — check for the dialog role
    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });
  });

  it("shows search input", async () => {
    renderWithProviders(<UnifiedKnowledgeBaseView />);

    await waitFor(() => {
      // Input.Search has placeholder "搜索知识库名称..."
      expect(screen.getByPlaceholderText("搜索知识库名称...")).toBeInTheDocument();
    });
  });

  it("shows empty state when no knowledge bases", async () => {
    // listAllKbs returns empty array (default mock)
    renderWithProviders(<UnifiedKnowledgeBaseView />);

    // Wait for data to load — with empty kbs and activeTab="all", no create button
    await waitFor(() => {
      // KnowledgeBaseGrid shows "暂无知识库" when empty and no create button
      expect(screen.getByText("暂无知识库")).toBeInTheDocument();
    });
  });

  it("applies onKbSelect callback when KB card clicked", async () => {
    mockUnifiedKbManager.listAllKbs.mockResolvedValue(mockKbSummaries);

    const mockOnKbSelect = vi.fn();
    renderWithProviders(<UnifiedKnowledgeBaseView onKbSelect={mockOnKbSelect} />);

    // Wait for grid data and click in one waitFor to avoid race conditions
    await waitFor(() => {
      const kbCard = screen.getByText("知识库 1");
      expect(kbCard).toBeInTheDocument();
      fireEvent.click(kbCard);
    });

    await waitFor(() => {
      expect(mockOnKbSelect).toHaveBeenCalled();
    });
  });
});
