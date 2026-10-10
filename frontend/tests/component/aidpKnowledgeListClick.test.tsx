import { App } from "antd";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AidpKnowledgeList from "@/ext_components/aidp/components/AidpKnowledgeList";
import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";

const t = (key: string) => key;
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ t, i18n: { language: "zh" } }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { tenantId: "tenant" } }),
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({ data: { groups: [] } }),
}));
vi.mock("@/components/permission/Can", () => ({
  Can: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

describe("knowledge table navigation", () => {
  it("opens a knowledge base from its name, not from other cells in the row", () => {
    const onSelect = vi.fn();
    const kb = {
      kds_id: "kb-1",
      kds_name: "测试知识库",
      description: "知识库描述",
      permission: "READ_ONLY",
    } as AidpKnowledgeBaseItem;
    render(
      <App>
        <AidpKnowledgeList
          kbs={[kb]}
          isLoading={false}
          loadFailed={false}
          total={1}
          totalReliable
          hasMore={false}
          currentPage={1}
          pageSize={10}
          keyword=""
          viewMode="table"
          visibleColumns={[
            "name",
            "description",
            "creator",
            "created_at",
            "actions",
          ]}
          onKeywordChange={vi.fn()}
          onPageChange={vi.fn()}
          onPageSizeChange={vi.fn()}
          onViewModeChange={vi.fn()}
          onVisibleColumnsChange={vi.fn()}
          onSelect={onSelect}
          onRefresh={vi.fn()}
          onCreateNew={vi.fn()}
          onImport={vi.fn()}
          onDelete={vi.fn()}
          onRetry={vi.fn()}
        />
      </App>
    );

    const row = screen.getByRole("row", { name: /测试知识库/ });
    fireEvent.click(screen.getByText("知识库描述"));
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "测试知识库" }));
    expect(onSelect).toHaveBeenCalledExactlyOnceWith(kb);
    expect(row).toBeVisible();
  });
});
