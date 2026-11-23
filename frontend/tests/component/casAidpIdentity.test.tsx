// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { render, screen } from "@testing-library/react";
import { App } from "antd";
import { describe, expect, it, vi } from "vitest";
import AidpKnowledgeList from "@/ext_components/aidp/pages/knowledge-list/AidpKnowledgeList";
import AidpKnowledgeFilesPage from "@/ext_components/aidp/pages/knowledge-files/AidpKnowledgeFilesPage";
import type { AidpKnowledgeBaseItem } from "@/ext_components/aidp/shared/types/knowledge";
const session = vi.hoisted(() => ({ provider: "cas" }));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { authProvider: session.provider } }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/hooks/permission/usePermission", () => ({
  usePermission: () => ({ can: () => false }),
}));
vi.mock("@/ext_components/aidp/shared/hooks/useAidpGroupOptions", () => ({
  useAidpGroupOptions: () => ({
    groupOptions: [],
    canReadGroups: false,
    groupsError: null,
  }),
}));
vi.mock(
  "@/ext_components/aidp/pages/knowledge-files/hooks/useAidpKnowledgeDetail",
  () => ({
    useAidpKnowledgeDetail: () => ({
      data: undefined,
      isLoading: false,
      refetch: vi.fn(),
    }),
  })
);
vi.mock(
  "@/ext_components/aidp/pages/knowledge-files/hooks/useAidpKnowledgeFiles",
  () => ({
    useAidpKnowledgeFiles: () => ({
      data: { value: [], total_count: 0, has_more: false },
      refetch: vi.fn(),
    }),
  })
);
vi.mock("@/ext_components/aidp/features/file-import/AidpImportDrawer", () => ({
  default: () => null,
}));
vi.mock(
  "@/ext_components/aidp/pages/knowledge-files/AidpUpdateKbModal",
  () => ({ default: () => null })
);
const kb = {
  kds_id: "kb-1",
  kds_name: "Knowledge",
  creator_name: "owner@test",
  creator_cas_username: "知识库作者",
  permission: "READ_ONLY",
} as AidpKnowledgeBaseItem;
const callbacks = {
  onKeywordChange: vi.fn(),
  onPageChange: vi.fn(),
  onPageSizeChange: vi.fn(),
  onViewModeChange: vi.fn(),
  onVisibleColumnsChange: vi.fn(),
  onSelect: vi.fn(),
  onRefresh: vi.fn(),
  onCreateNew: vi.fn(),
  onImport: vi.fn(),
  onDelete: vi.fn(),
  onRetry: vi.fn(),
};
describe("AIDP creator presentation", () => {
  it.each(["cards", "table"] as const)(
    "uses CAS names in %s view and preserves local fallback",
    (viewMode) => {
      session.provider = "cas";
      const props = {
        ...callbacks,
        kbs: [kb],
        isLoading: false,
        loadFailed: false,
        loadError: undefined,
        total: 1,
        totalReliable: true,
        hasMore: false,
        currentPage: 1,
        pageSize: 10,
        keyword: "",
        viewMode,
        visibleColumns: ["name", "creator", "actions"] as Array<
          "name" | "creator" | "actions"
        >,
      };
      const { rerender } = render(<AidpKnowledgeList {...props} />);
      expect(screen.getByText("知识库作者")).toBeInTheDocument();
      session.provider = "local";
      rerender(<AidpKnowledgeList {...props} />);
      expect(screen.getByText("owner@test")).toBeInTheDocument();
    }
  );
  it("uses linked creator metadata in details", () => {
    session.provider = "cas";
    render(
      <App>
        <AidpKnowledgeFilesPage
          knowledgeBase={kb}
          onBack={vi.fn()}
          onDelete={vi.fn()}
          onUpdated={vi.fn()}
        />
      </App>
    );
    expect(screen.getByText("知识库作者")).toBeInTheDocument();
  });
  it("falls back when creator metadata is blank", () => {
    session.provider = "cas";
    render(
      <App>
        <AidpKnowledgeFilesPage
          knowledgeBase={{ ...kb, creator_cas_username: "  " }}
          onBack={vi.fn()}
          onDelete={vi.fn()}
          onUpdated={vi.fn()}
        />
      </App>
    );
    expect(screen.getByText("owner@test")).toBeInTheDocument();
  });
});
