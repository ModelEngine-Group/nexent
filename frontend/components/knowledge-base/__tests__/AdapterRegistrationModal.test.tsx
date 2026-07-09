import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderWithProviders, screen, waitFor } from "./test-utils";
import AdapterRegistrationModal from "../AdapterRegistrationModal";
import type { AdapterInfo } from "@/types/unifiedKnowledgeBase";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const { mockUnifiedKbManager } = vi.hoisted(() => {
  const mgr = {
    listAllAdaptersForManagement: vi.fn(),
    checkAdapterHealth: vi.fn(),
    updateAdapter: vi.fn(),
    deleteAdapter: vi.fn(),
    getAdapterCapabilities: vi.fn(),
  };
  return { mockUnifiedKbManager: mgr };
});

vi.mock("@/services/unifiedKnowledgeBaseService", () => ({
  default: mockUnifiedKbManager,
  unifiedKbManager: mockUnifiedKbManager,
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const LOCAL_ADAPTER: AdapterInfo = {
  adapter_id: 1,
  platform: "local",
  name: "本地知识库",
  status: "running",
  enabled: true,
  health_status: "healthy",
  capabilities: {
    create_knowledge_base: true,
    delete_knowledge_base: true,
    update_knowledge_base: true,
    upload_document: true,
    delete_document: true,
    list_documents: true,
    query_document_status: true,
    download_document: true,
    list_models: false,
    search_modes: ["hybrid", "semantic", "accurate"],
    supports_rerank: true,
    supports_multimodal: true,
    supports_batch_search: false,
    max_kb_ids_per_search: 100,
    requires_embedding_model: false,
    supports_custom_embedding_model: false,
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function setupMocks() {
  mockUnifiedKbManager.listAllAdaptersForManagement.mockResolvedValue([
    LOCAL_ADAPTER,
  ]);
  mockUnifiedKbManager.checkAdapterHealth.mockResolvedValue({ status: "ok" });
  mockUnifiedKbManager.getAdapterCapabilities.mockResolvedValue(
    LOCAL_ADAPTER.capabilities,
  );
  mockUnifiedKbManager.updateAdapter.mockResolvedValue(LOCAL_ADAPTER);
  mockUnifiedKbManager.deleteAdapter.mockResolvedValue(undefined);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AdapterRegistrationModal", () => {
  const mockOnCancel = vi.fn();
  const mockOnRegistered = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    setupMocks();
  });

  it("renders modal with title '适配器管理' when visible", () => {
    renderWithProviders(
      <AdapterRegistrationModal
        visible={true}
        onCancel={mockOnCancel}
        onRegistered={mockOnRegistered}
      />,
    );
    expect(screen.getByText("适配器管理")).toBeInTheDocument();
  });

  it("renders registered adapters section with the local adapter", async () => {
    renderWithProviders(
      <AdapterRegistrationModal
        visible={true}
        onCancel={mockOnCancel}
        onRegistered={mockOnRegistered}
      />,
    );
    expect(await screen.findByText("本地知识库")).toBeInTheDocument();
    expect(screen.getByText("local")).toBeInTheDocument();
  });

  it("renders placeholder platforms that are not yet registered", async () => {
    renderWithProviders(
      <AdapterRegistrationModal
        visible={true}
        onCancel={mockOnCancel}
        onRegistered={mockOnRegistered}
      />,
    );
    // "local" is registered; the other 4 platforms remain as placeholders.
    expect(await screen.findByText(/Dify 知识库/)).toBeInTheDocument();
    expect(await screen.findByText(/AIDP 知识库/)).toBeInTheDocument();
    expect(await screen.findByText(/DataMate 知识库/)).toBeInTheDocument();
    expect(await screen.findByText(/Haotian 知识库/)).toBeInTheDocument();
  });

  it("hides a placeholder platform when that platform is already registered", async () => {
    mockUnifiedKbManager.listAllAdaptersForManagement.mockResolvedValue([
      LOCAL_ADAPTER,
      {
        adapter_id: 2,
        platform: "dify",
        name: "Dify 已注册",
        status: "running",
        enabled: true,
      },
    ]);

    renderWithProviders(
      <AdapterRegistrationModal
        visible={true}
        onCancel={mockOnCancel}
        onRegistered={mockOnRegistered}
      />,
    );

    // Wait for the query to resolve — both adapters render and dify
    // placeholder should be filtered out.
    expect(await screen.findByText("Dify 已注册")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText(/Dify 知识库/)).not.toBeInTheDocument();
    });
    expect(screen.getByText(/AIDP 知识库/)).toBeInTheDocument();
  });

  it("does not render a delete button for the local adapter", async () => {
    renderWithProviders(
      <AdapterRegistrationModal
        visible={true}
        onCancel={mockOnCancel}
        onRegistered={mockOnRegistered}
      />,
    );
    await screen.findByText("本地知识库");
    // Only the health-check button and the switch are present for local;
    // no delete button.
    expect(screen.queryByRole("button", { name: /删除/ })).not.toBeInTheDocument();
  });
});
