// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { render, screen, within } from "@testing-library/react";
import { App } from "antd";
import { describe, expect, it, vi } from "vitest";

import AidpKnowledgeFilesPage from "@/ext_components/aidp/pages/knowledge-files/AidpKnowledgeFilesPage";
import { fileDeleteStatusCode } from "@/ext_components/aidp/pages/knowledge-files/utils/aidpKnowledgeDetailUtils";
import type { AidpKnowledgeBaseItem } from "@/ext_components/aidp/shared/types/knowledge";

const mockFiles = vi.hoisted(() => [
  {
    file_uuid: "uuid-normal",
    file_ino_no: "1",
    file_name: "normal.txt",
    file_status: 0,
  },
  {
    file_uuid: "uuid-deleting",
    file_ino_no: "2",
    file_name: "deleting.txt",
    file_status: 1,
  },
  {
    file_uuid: "uuid-failed",
    file_ino_no: "3",
    file_name: "failed.txt",
    file_status: 2,
  },
]);
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { authProvider: "local" } }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/hooks/permission/usePermission", () => ({
  usePermission: () => ({ can: () => true }),
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
      data: {
        value: mockFiles,
        total_count: mockFiles.length,
        has_more: false,
        total_reliable: true,
      },
      isFetching: false,
      isSuccess: true,
      isError: false,
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

describe("fileDeleteStatusCode", () => {
  it("maps the reported numeric contract unchanged", () => {
    expect(fileDeleteStatusCode(0)).toBe(0);
    expect(fileDeleteStatusCode(1)).toBe(1);
    expect(fileDeleteStatusCode(2)).toBe(2);
  });

  it("accepts numeric strings like the other AIDP status readers", () => {
    expect(fileDeleteStatusCode("1")).toBe(1);
    expect(fileDeleteStatusCode("2")).toBe(2);
    expect(fileDeleteStatusCode(" 1 ")).toBe(1);
  });

  it("falls back to ingested for any other reported value", () => {
    // Safety-net rule: only 1 (deleting) and 2 (delete failed) are recognized;
    // everything else - including 0, out-of-contract numbers and missing
    // fields - must keep showing "ingested".
    expect(fileDeleteStatusCode(undefined)).toBe(0);
    expect(fileDeleteStatusCode(null)).toBe(0);
    expect(fileDeleteStatusCode("0")).toBe(0);
    expect(fileDeleteStatusCode(3)).toBe(0);
    expect(fileDeleteStatusCode(-1)).toBe(0);
    expect(fileDeleteStatusCode(Number.NaN)).toBe(0);
    expect(fileDeleteStatusCode("deleting")).toBe(0);
    expect(fileDeleteStatusCode("")).toBe(0);
    expect(fileDeleteStatusCode(true)).toBe(0);
  });
});

describe("AIDP file delete guard", () => {
  const kb = {
    kds_id: "kb-1",
    kds_name: "Knowledge",
    permission: "EDIT",
  } as AidpKnowledgeBaseItem;

  const rowOf = (name: string) => {
    const cell = screen.getByText(name);
    return within(cell.closest("tr") as HTMLElement);
  };

  it("disables the batch checkbox and row delete for deleting files only", () => {
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

    const deletingRow = rowOf("deleting.txt");
    expect(deletingRow.getByRole("checkbox")).toBeDisabled();
    expect(
      deletingRow.getByRole("button", { name: "common.delete" })
    ).toBeDisabled();

    // Ingested and delete-failed rows keep their removal entry points so a
    // failed deletion can be retried.
    for (const name of ["normal.txt", "failed.txt"]) {
      const row = rowOf(name);
      expect(row.getByRole("checkbox")).toBeEnabled();
      expect(row.getByRole("button", { name: "common.delete" })).toBeEnabled();
    }
  });
});
