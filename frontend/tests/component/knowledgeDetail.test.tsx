// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import DocumentList from "@/app/knowledges/components/document/DocumentList";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import type { Document, KnowledgeBase } from "@/types/knowledgeBase";

const groups = vi.hoisted(() => [
  { group_id: 1, group_name: "Default Group" },
  { group_id: 2, group_name: "Engineering" },
]);
const groupAccess = vi.hoisted(() => ({
  getAccessibleGroupIds: () => [1, 2],
  getTenantDefaultGroupId: vi.fn().mockResolvedValue(1),
}));

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return {
    initReactI18next: { type: "3rdParty", init: () => undefined },
    useTranslation: () => ({ t }),
  };
});
vi.mock("@/components/permission/Can", () => ({
  Can: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({ modelConfig: null }),
}));
vi.mock("@/hooks/model/useInferenceFieldSpecs", () => ({
  useInferenceFieldSpecs: () => ({ specs: [] }),
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({ data: { groups } }),
  useGroupDetails: () => ({ groups }),
}));
vi.mock("@/services/groupService", () => ({
  getTenantDefaultGroupId: groupAccess.getTenantDefaultGroupId,
}));
vi.mock("@/hooks/permission/usePermission", () => ({
  usePermission: () => ({ can: () => true }),
}));
vi.mock("@/services/knowledgeBasePollingService", () => ({
  default: { triggerKnowledgeBaseListUpdate: vi.fn() },
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: { tenantId: "tenant" },
    getAccessibleGroupIds: groupAccess.getAccessibleGroupIds,
  }),
}));
vi.mock("@/app/knowledges/contexts/DocumentContext", () => ({
  useDocumentContext: () => ({ state: { isLoadingDocuments: false } }),
}));
vi.mock("@/hooks/useTagManagement", () => ({
  useTagLibraries: () => ({ data: [], loading: false }),
  useTagDefinitions: () => ({ data: [], loading: false }),
}));
vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: { getDocumentBatchStatus: vi.fn().mockResolvedValue([]) },
}));
vi.mock("@/services/modelService", () => ({
  modelService: {
    getLLMModels: vi
      .fn()
      .mockResolvedValue([
        { id: 4, displayName: "Test model", connect_status: "available" },
      ]),
  },
}));
vi.mock("@/services/knowledgeBaseService", () => ({
  default: {
    getSummary: vi.fn().mockResolvedValue("Existing summary"),
    summaryIndex: vi.fn(),
    changeSummary: vi.fn(),
    updateKnowledgeBase: vi.fn(),
    fetchSummaryFrequencyOptions: vi
      .fn()
      .mockResolvedValue([{ value: "disabled", label: "Off" }]),
  },
}));
vi.mock("@/app/knowledges/components/document/DocumentChunk", () => ({
  default: ({ initialDocumentId }: { initialDocumentId: string }) => (
    <div>{initialDocumentId}</div>
  ),
}));
vi.mock("@/app/knowledges/components/document/DocumentStatus", () => ({
  default: () => null,
}));
vi.mock("@/components/tag/ResourceTagChips", () => ({
  default: () => null,
}));
vi.mock("@/components/tag/ResourceTagAssignmentModal", () => ({
  default: ({ open, canEdit }: { open: boolean; canEdit: boolean }) =>
    open ? <div data-testid="tag-assignment">{String(canEdit)}</div> : null,
}));
vi.mock("@/app/knowledges/components/knowledge/KnowledgeBaseEditModal", () => ({
  KnowledgeBaseEditModal: ({ open }: { open: boolean }) =>
    open ? <div role="dialog">Edit knowledge base</div> : null,
}));
vi.mock("@/components/tag/TagDefinitionManagementModal", () => ({
  default: () => null,
}));
vi.mock("@/components/common/markdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <p>{content}</p>,
}));
vi.mock("@/components/common/filePreviewDrawer", () => ({
  FilePreviewDrawer: () => null,
}));

const documents = [
  { id: "document-a", name: "Alpha.pdf", chunk_num: 2 },
  { id: "document-b", name: "Beta.pdf", chunk_num: 5 },
].map((doc) => ({
  ...doc,
  type: "pdf",
  size: 200,
  status: "done",
  create_time: "2026-11-26T03:00:00Z",
})) as Document[];

function renderDetail(
  permission = "EDIT",
  onUpload?: (files: File[]) => Promise<void>,
  onCatalogRefresh?: () => void
) {
  return render(
    <App>
      <DocumentList
        documents={documents}
        onDelete={vi.fn()}
        onDeleteKnowledgeBase={vi.fn()}
        onCatalogKnowledgeBaseChange={vi.fn()}
        onCatalogRefresh={onCatalogRefresh}
        onFileSelect={vi.fn()}
        onUpload={onUpload}
        knowledgeBaseId="test-kb"
        knowledgeBaseName="Test knowledge base"
        catalogKnowledgeBase={
          {
            id: "test-kb",
            name: "Test knowledge base",
            chunkCount: 7,
            ingroup_permission: "READ_ONLY",
            group_ids: [1],
            preserve_source_file: false,
          } as KnowledgeBase
        }
        permission={permission}
      />
    </App>
  );
}

function CreateFields({
  onQuotaChange,
  onCopyChange,
}: {
  onQuotaChange: (bytes: number | null) => void;
  onCopyChange?: (preserve: boolean) => void;
}) {
  const [copy, setCopy] = useState(true);
  const [permission, setPermission] = useState("READ_ONLY");
  const [groupIds, setGroupIds] = useState<number[]>([]);
  const [quota, setQuota] = useState<number | null>(null);

  return (
    <App>
      <DocumentList
        isCreatingMode
        documents={[]}
        onDelete={vi.fn()}
        onFileSelect={vi.fn()}
        knowledgeBaseId=""
        knowledgeBaseName="Test knowledge base"
        selectedEmbeddingModel="Test model::embedding"
        availableEmbeddingModels={[
          {
            id: 4,
            type: "embedding",
            displayName: "Test model",
            maxTokens: 768,
            expectedChunkSize: 256,
            connect_status: "available",
          } as import("@/types/modelConfig").ModelOption,
        ]}
        onEmbeddingModelChange={vi.fn()}
        ingroupPermission={permission}
        onIngroupPermissionChange={setPermission}
        selectedGroupIds={groupIds}
        onSelectedGroupIdsChange={setGroupIds}
        preserveSourceFile={copy}
        onPreserveSourceFileChange={(preserve) => {
          setCopy(preserve);
          onCopyChange?.(preserve);
        }}
        quotaLimitBytes={quota}
        onQuotaLimitBytesChange={(bytes) => {
          setQuota(bytes);
          onQuotaChange(bytes);
        }}
      />
    </App>
  );
}

it("shows create settings, applies the copy dropdown, and clears selected groups for private access", async () => {
  const onCopyChange = vi.fn();
  render(<CreateFields onQuotaChange={vi.fn()} onCopyChange={onCopyChange} />);

  expect(
    screen.getByRole("heading", { name: "knowledgeBase.create.basicInfo" })
  ).toBeInTheDocument();
  expect(screen.getByText("768")).toBeInTheDocument();
  const copySelect = screen.getByRole("combobox", {
    name: /knowledgeBase.create.field.preserve/,
  });
  fireEvent.mouseDown(copySelect);
  fireEvent.click(await screen.findByText("knowledgeBase.create.chunksOnly"));
  expect(onCopyChange).toHaveBeenLastCalledWith(false);

  const defaultGroup = screen.getByRole("checkbox", { name: "Default Group" });
  await waitFor(() => expect(defaultGroup).toBeChecked());
  const engineering = screen.getByRole("checkbox", { name: "Engineering" });
  expect(engineering).not.toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "common.selectAll" }));
  expect(engineering).toBeChecked();
  fireEvent.click(
    screen.getByRole("radio", { name: /knowledgeBase.create.access.PRIVATE/ })
  );
  expect(engineering).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("radio", { name: /knowledgeBase.create.access.EDIT/ })
  );
  expect(
    screen.getByRole("checkbox", { name: "Engineering" })
  ).not.toBeChecked();
  expect(
    screen.getByRole("checkbox", { name: "Default Group" })
  ).not.toBeChecked();
});

it("preserves the storage limit when changing units and clears it when the field is empty", () => {
  const onQuotaChange = vi.fn();
  render(<CreateFields onQuotaChange={onQuotaChange} />);
  const quota = screen.getByRole("spinbutton", {
    name: /knowledgeBase.create.field.quota/,
  });
  fireEvent.change(quota, { target: { value: "1" } });
  expect(onQuotaChange).toHaveBeenLastCalledWith(1024 ** 3);

  fireEvent.click(screen.getByRole("radio", { name: "MB" }));
  expect(quota).toHaveValue("1024");
  expect(onQuotaChange).toHaveBeenCalledTimes(1);

  fireEvent.change(quota, { target: { value: "" } });
  expect(onQuotaChange).toHaveBeenLastCalledWith(null);
});

describe("knowledge base detail", () => {
  it("opens the existing edit dialog from the detail title", async () => {
    renderDetail();
    fireEvent.click(
      screen.getByRole("button", { name: "tenantResources.knowledgeBase.edit" })
    );
    expect(screen.getByRole("dialog")).toHaveTextContent("Edit knowledge base");
    await screen.findByDisplayValue("Existing summary");
  });
  it("lets editors deselect the last user group and save without changing the copy setting", async () => {
    const update = vi.mocked(knowledgeBaseService.updateKnowledgeBase);
    update.mockResolvedValueOnce(undefined);
    renderDetail();
    await screen.findByDisplayValue("Existing summary");
    const group = screen.getByRole("button", { name: "Default Group" });
    expect(group).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(group);
    expect(group).toHaveAttribute("aria-pressed", "false");
    expect(update).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith("test-kb", { group_ids: [] })
    );
    expect(screen.getByText("common.disabled")).toBeVisible();
  });

  it("clears assigned groups when private access is selected", async () => {
    const update = vi.mocked(knowledgeBaseService.updateKnowledgeBase);
    update.mockClear().mockResolvedValueOnce(undefined);
    renderDetail();
    await screen.findByDisplayValue("Existing summary");
    fireEvent.mouseDown(
      screen.getByRole("combobox", {
        name: "knowledgeBase.create.field.permission",
      })
    );
    fireEvent.click(
      await screen.findByText("knowledgeBase.ingroup.permission.PRIVATE")
    );
    expect(screen.queryByRole("button", { name: "Default Group" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith("test-kb", {
        ingroup_permission: "PRIVATE",
        group_ids: [],
      })
    );
  });
  it("saves a generated summary automatically and refreshes the catalog", async () => {
    const refreshCatalog = vi.fn();
    vi.mocked(knowledgeBaseService.getSummary).mockResolvedValueOnce(
      "<p>Stored summary</p>\n\n<p>Second paragraph</p>"
    );
    vi.mocked(knowledgeBaseService.summaryIndex).mockResolvedValueOnce(
      "<p>Generated summary</p>"
    );
    vi.mocked(knowledgeBaseService.changeSummary).mockResolvedValueOnce(
      undefined
    );
    renderDetail("EDIT", undefined, refreshCatalog);

    const editor = await screen.findByRole("textbox", {
      name: "document.summary.title",
    });
    expect(editor).toHaveValue("Stored summary\n\nSecond paragraph");
    expect(screen.queryByRole("button", { name: "common.save" })).toBeNull();
    expect(screen.getByText("document.summary.retrievalHint")).toBeVisible();

    const generate = screen.getByRole("button", {
      name: "document.button.autoSummary",
    });
    await waitFor(() => expect(generate).toBeEnabled());
    fireEvent.click(generate);
    expect(await screen.findByDisplayValue("Generated summary")).toBeVisible();
    expect(knowledgeBaseService.changeSummary).toHaveBeenCalledWith(
      "test-kb",
      "Generated summary"
    );
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "common.save" })).toBeNull()
    );
    expect(refreshCatalog).toHaveBeenCalledOnce();
  });

  it("keeps a generated draft available for manual retry if autosave fails", async () => {
    const refreshCatalog = vi.fn();
    vi.mocked(knowledgeBaseService.summaryIndex).mockResolvedValueOnce(
      "New draft"
    );
    vi.mocked(knowledgeBaseService.changeSummary).mockRejectedValueOnce(
      new Error("Save failed")
    );
    vi.mocked(knowledgeBaseService.changeSummary).mockResolvedValueOnce(
      undefined
    );
    renderDetail("EDIT", undefined, refreshCatalog);
    await screen.findByDisplayValue("Existing summary");
    const generate = screen.getByRole("button", {
      name: "document.button.autoSummary",
    });
    await waitFor(() => expect(generate).toBeEnabled());
    fireEvent.click(generate);

    expect(await screen.findByDisplayValue("New draft")).toBeVisible();
    expect(screen.queryByRole("button", { name: "common.save" })).toBeNull();
    const retry = screen.getByRole("button", {
      name: "repository.common.retry",
    });
    expect(retry).toBeEnabled();
    expect(refreshCatalog).not.toHaveBeenCalled();
    fireEvent.click(retry);
    await waitFor(() => expect(refreshCatalog).toHaveBeenCalledOnce());
  });

  it("saves manual edits on blur without a Save button", async () => {
    const changeSummary = vi.mocked(knowledgeBaseService.changeSummary);
    changeSummary.mockClear().mockResolvedValueOnce(undefined);
    const refreshCatalog = vi.fn();
    renderDetail("EDIT", undefined, refreshCatalog);
    const editor = await screen.findByDisplayValue("Existing summary");

    fireEvent.change(editor, { target: { value: "Edited summary" } });
    expect(changeSummary).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "common.save" })).toBeNull();
    fireEvent.blur(editor);
    await waitFor(() => expect(refreshCatalog).toHaveBeenCalledOnce());
    expect(changeSummary).toHaveBeenCalledExactlyOnceWith(
      "test-kb",
      "Edited summary"
    );
    fireEvent.blur(editor);
    expect(changeSummary).toHaveBeenCalledTimes(1);
  });

  it("restores the draft when summary generation returns an error as a paragraph", async () => {
    vi.mocked(knowledgeBaseService.changeSummary).mockClear();
    vi.mocked(knowledgeBaseService.summaryIndex).mockResolvedValueOnce(
      "<p>Failed to generate summary: Runtime service is unavailable</p>"
    );
    renderDetail();
    const editor = await screen.findByDisplayValue("Existing summary");
    fireEvent.change(editor, { target: { value: "Unsaved draft" } });
    const generate = screen.getByRole("button", {
      name: "document.button.autoSummary",
    });
    await waitFor(() => expect(generate).toBeEnabled());
    fireEvent.blur(editor, { relatedTarget: generate });
    fireEvent.click(generate);
    expect(await screen.findByDisplayValue("Unsaved draft")).toBeVisible();
    expect(await screen.findByText("document.summary.error")).toBeVisible();
    expect(knowledgeBaseService.changeSummary).not.toHaveBeenCalled();
  });

  it("filters names and opens the selected document's chunks while keeping the summary", async () => {
    renderDetail();
    expect(await screen.findByDisplayValue("Existing summary")).toBeVisible();
    expect(screen.getByText("knowledgeBase.detail.access")).toBeVisible();
    expect(screen.getByText("common.disabled")).toBeVisible();
    const search = screen.getByRole("textbox", {
      name: "knowledgeBase.detail.documentSearch",
    });
    fireEvent.change(search, { target: { value: "missing" } });
    expect(
      screen.getByText("knowledgeBase.detail.noMatchingDocuments")
    ).toBeVisible();
    fireEvent.change(search, { target: { value: " BETA " } });
    expect(screen.getByText("Beta.pdf")).toBeVisible();
    expect(screen.queryByText("Alpha.pdf")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "knowledgeBase.detail.viewChunks" })
    );
    expect(screen.getByText("document-b")).toBeVisible();
    expect(screen.getByDisplayValue("Existing summary")).toBeVisible();
  });

  it("uploads from the header without rendering a drop zone below the table", async () => {
    const onUpload = vi
      .fn<(files: File[]) => Promise<void>>()
      .mockResolvedValue(undefined);
    const { container } = renderDetail("EDIT", onUpload);
    const button = screen.getByRole("button", {
      name: "knowledgeBase.detail.upload",
    });
    await waitFor(() => expect(button).toBeEnabled());
    const input =
      container.querySelector<HTMLInputElement>('input[type="file"]')!;
    const click = vi.spyOn(input, "click");
    fireEvent.click(button);
    expect(click).toHaveBeenCalledOnce();
    expect(screen.queryByText("knowledgeBase.upload.dragHint")).toBeNull();

    const note = new File(["notes"], "notes.txt", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [note] } });
    await waitFor(() => expect(onUpload).toHaveBeenCalledWith([note]));
  });

  it("keeps the summary readable without exposing upload, delete or edit for read-only access", async () => {
    renderDetail("READ_ONLY");
    expect(await screen.findByText("Existing summary")).toBeVisible();
    expect(
      screen.queryByRole("button", {
        name: "tenantResources.knowledgeBase.edit",
      })
    ).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "knowledgeBase.action.viewTags" })
    );
    expect(screen.getByTestId("tag-assignment")).toHaveTextContent("false");
    expect(
      screen.queryByRole("combobox", {
        name: "knowledgeBase.create.field.permission",
      })
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Default Group" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "knowledgeBase.detail.upload" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "knowledgeBase.detail.delete" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: "document.summary.title" })
    ).not.toBeInTheDocument();
  });
});
