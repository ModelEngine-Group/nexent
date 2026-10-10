import { App } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AidpKnowledgeFilesPage from "@/ext_components/aidp/components/AidpKnowledgeFilesPage";
import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";

const mocks = vi.hoisted(() => ({
  t: (key: string) => key,
  groups: [],
  getKb: vi.fn(),
  listIngestedFiles: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: mocks.t, i18n: { language: "zh" } }),
}));
vi.mock("@/ext_components/aidp/services/aidpKnowledgeService", () => ({
  default: { getKb: mocks.getKb, listIngestedFiles: mocks.listIngestedFiles },
}));
vi.mock("@/ext_components/aidp/hooks/useAidpGroupOptions", () => ({
  useAidpGroupOptions: () => ({ groupOptions: mocks.groups }),
}));
vi.mock("@/ext_components/aidp/components/AidpImportDrawer", () => ({
  default: () => null,
}));
vi.mock("@/ext_components/aidp/components/AidpUpdateKbModal", () => ({
  default: () => null,
}));

describe("AIDP file page scope", () => {
  it("shows only ingested files and forwards search to the paginated file API", async () => {
    const kb = {
      kds_id: "kb-1",
      kds_name: "测试知识库",
      permission: "READ_ONLY",
    } as AidpKnowledgeBaseItem;
    mocks.getKb.mockResolvedValue(kb);
    mocks.listIngestedFiles.mockResolvedValue({
      value: [
        {
          file_uuid: "file-1",
          file_ino_no: "1",
          file_name: "使用说明.pdf",
          file_type: "pdf",
        },
      ],
      total_count: 1,
    });
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
    expect(await screen.findByText("使用说明.pdf")).toBeVisible();
    expect(screen.getAllByRole("tab")).toHaveLength(1);
    expect(screen.getByRole("tab")).toHaveTextContent(
      "aidpKnowledge.detailTabFiles"
    );
    expect(screen.queryByText("aidpKnowledge.detailTabTasks")).toBeNull();
    expect(screen.queryByText("aidpKnowledge.detailTabInfo")).toBeNull();
    expect(screen.getByText("aidpKnowledge.detailLocalImport")).toBeVisible();
    fireEvent.change(
      screen.getByPlaceholderText("aidpKnowledge.detailFileSearch"),
      { target: { value: " 使用说明 " } }
    );
    await waitFor(() =>
      expect(mocks.listIngestedFiles).toHaveBeenLastCalledWith(
        "kb-1",
        1,
        10,
        "使用说明"
      )
    );
  });
});
