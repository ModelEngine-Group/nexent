// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { render, changePageSize } from "./resourceDrawerTestUtils";
import { KnowledgeDrawer } from "@/components/resource-picker/KnowledgeDrawer";
import { tagManagementApi } from "@/services/tagManagementService";
import type { KnowledgeBase } from "@/types/knowledgeBase";

vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: {
    listLibraries: vi.fn(async () => []),
    listDefinitions: vi.fn(async () => []),
    getAssignments: vi.fn(async () => ({ assignments: [] })),
    getKnowledgeAssignmentsBatch: vi.fn(async () => []),
    filterResourceIds: vi.fn(async () => ({ matched_resource_ids: [] })),
  },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, value?: string | { count: number }) => {
      if (
        key === "resourcePicker.knowledge.documents" &&
        typeof value === "object"
      )
        return `${value.count} documents`;
      if (
        key === "resourcePicker.knowledge.chunks" &&
        typeof value === "object"
      )
        return `${value.count} chunks`;
      return typeof value === "string" ? value : key;
    },
  }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { tenantId: "tenant" } }),
}));
vi.mock("@/hooks/knowledge/useKnowledgeList", () => ({
  useKnowledgeList: () => ({ data: [], isLoading: false, refetch: vi.fn() }),
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({ data: { groups: [] } }),
}));
vi.mock("@/components/tool-config/KnowledgeModelMismatchModal", () => ({
  KnowledgeModelMismatchModal: () => null,
}));
vi.mock("@/components/tool-config/EmbeddingModelConfigDialog", () => ({
  default: () => null,
}));

const knowledgeBases = [
  {
    id: "kb:1",
    name: "Handbook",
    description: "Policies",
    documentCount: 128,
    chunkCount: 3420,
    source: "local",
    embeddingModel: "bge-m3",
    updatedAt: "2026-10-15T12:00:00Z",
  },
] as KnowledgeBase[];

it("changes the actual page size, returns to page one and retains off-page selection", async () => {
  const items = Array.from({ length: 21 }, (_, index) => ({
    ...knowledgeBases[0],
    id: `kb:${index + 1}`,
    name: `Knowledge ${index + 1}`,
  }));
  render(<KnowledgeDrawer open onClose={vi.fn()} knowledgeBases={items} />);
  expect(screen.getAllByRole("option")).toHaveLength(10);
  await waitFor(() =>
    expect(
      tagManagementApi.getKnowledgeAssignmentsBatch
    ).toHaveBeenCalledExactlyOnceWith(
      Array.from({ length: 10 }, (_, i) => `kb:${i + 1}`)
    )
  );
  fireEvent.click(screen.getByRole("button", { name: "3" }));
  await waitFor(() =>
    expect(
      tagManagementApi.getKnowledgeAssignmentsBatch
    ).toHaveBeenLastCalledWith(["kb:21"])
  );
  expect(tagManagementApi.getAssignments).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("option", { name: "Knowledge 21" }));
  await changePageSize(20);
  expect(screen.getAllByRole("option")).toHaveLength(20);
  expect(
    screen.getByRole("option", { name: "Knowledge 1" })
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "2" }));
  expect(screen.getByRole("option", { name: "Knowledge 21" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  await changePageSize(50);
  expect(screen.getAllByRole("option")).toHaveLength(21);
});

it("renders knowledge as an icon-free list by default with descriptive metadata", () => {
  render(
    <KnowledgeDrawer open onClose={vi.fn()} knowledgeBases={knowledgeBases} />
  );
  const row = screen
    .getByRole("option", { name: "Handbook" })
    .closest("[data-resource-view]");
  expect(row).toHaveAttribute("data-resource-view", "list");
  expect(row).toHaveTextContent("Policies");
  expect(row).toHaveTextContent("128 documents");
  expect(row).toHaveTextContent("3420 chunks");
  expect(row).toHaveTextContent("bge-m3");
  expect(row).not.toHaveTextContent("resourcePicker.knowledge.usedAt");
  expect(row).not.toHaveTextContent("2026-10-15");
  expect(row).toHaveClass("hover:bg-muted/50");
  expect(row?.querySelector(".lucide-database, img, .ant-avatar")).toBeNull();
});

it.each(["list", "card"] as const)(
  "hides AIDP count metadata in %s view and retains local counts",
  (viewMode) => {
    const props = {
      open: true,
      onClose: vi.fn(),
      viewMode,
      knowledgeBases,
    };
    const view = render(<KnowledgeDrawer {...props} isAidpSearch />);
    const row = () =>
      screen
        .getByRole("option", { name: "Handbook" })
        .closest("[data-resource-view]");
    expect(row()).toHaveTextContent("Policies");
    expect(row()).toHaveTextContent("bge-m3");
    expect(row()).not.toHaveTextContent("128 documents");
    expect(row()).not.toHaveTextContent("3420 chunks");
    expect(knowledgeBases[0].documentCount).toBe(128);
    expect(knowledgeBases[0].chunkCount).toBe(3420);
    view.rerender(<KnowledgeDrawer {...props} isAidpSearch={false} />);
    expect(row()).toHaveTextContent("128 documents");
    expect(row()).toHaveTextContent("3420 chunks");
  }
);

it("opens configurable tag management without committing knowledge selection", () => {
  const confirm = vi.fn();
  render(
    <KnowledgeDrawer
      open
      onClose={vi.fn()}
      onConfirm={confirm}
      enableTagManagement
      knowledgeBases={[{ ...knowledgeBases[0], permission: "READ_ONLY" }]}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "管理标签" }));
  expect(screen.getAllByRole("dialog")).toHaveLength(2);
  expect(document.querySelector(".ant-modal-title")).toHaveTextContent(
    "管理标签"
  );
  expect(
    screen
      .getAllByRole("button", { name: "管理标签" })
      .some((button) => button.hasAttribute("disabled"))
  ).toBe(true);
  expect(confirm).not.toHaveBeenCalled();
});

it("hides the fixed Elasticsearch description while retaining the source badge", () => {
  render(
    <KnowledgeDrawer
      open
      onClose={vi.fn()}
      knowledgeBases={[
        {
          ...knowledgeBases[0],
          source: "nexent",
          description: "Elasticsearch index",
        },
      ]}
    />
  );
  expect(screen.queryByText("Elasticsearch index")).toBeNull();
  expect(screen.getByRole("option", { name: "Handbook" })).toHaveTextContent(
    "nexent"
  );
});

it.each([
  [true, "多模态"],
  [false, "仅文本"],
] as const)(
  "shows modality %s and separates the source from ordinary tags",
  (is_multimodal, label) => {
    render(
      <KnowledgeDrawer
        open
        onClose={vi.fn()}
        knowledgeBases={[
          {
            ...knowledgeBases[0],
            description: "Elasticsearch index",
            source: "nexent",
            tags: ["Team", "Policies"],
            is_multimodal,
          },
        ]}
      />
    );
    const option = screen.getByRole("option", { name: "Handbook" });
    const name = screen.getByText("Handbook", { selector: "span[title]" });
    const tag = screen.getByText("Team");
    const source = screen.getByText("nexent");
    expect(option).toHaveTextContent(label);
    expect(name.parentElement).toContainElement(tag);
    expect(name.parentElement).not.toContainElement(source);
    expect(source.parentElement?.parentElement).toBe(
      name.parentElement?.parentElement
    );
    expect(option).toHaveClass("min-h-16");
  }
);

it("preserves knowledge selection across layouts and failed confirmation, with independent metadata actions", async () => {
  const close = vi.fn();
  const confirm = vi
    .fn()
    .mockRejectedValueOnce(new Error("Save failed"))
    .mockResolvedValueOnce(undefined);
  const props = {
    open: true,
    onClose: close,
    onConfirm: confirm,
    knowledgeBases,
  };
  const view = render(<KnowledgeDrawer {...props} viewMode="card" />);
  expect(screen.getByText("128 documents")).toBeInTheDocument();
  expect(screen.getByText("3420 chunks")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("option", { name: "Handbook" }));
  const details = vi.fn();
  view.rerender(
    <KnowledgeDrawer
      {...props}
      viewMode="list"
      slots={{
        renderMetadata: (item) => (
          <button onClick={details}>
            {item.raw.documentCount} documents: details
          </button>
        ),
      }}
    />
  );
  expect(screen.getByRole("option", { name: "Handbook" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  fireEvent.click(
    screen.getByRole("button", { name: "128 documents: details" })
  );
  expect(details).toHaveBeenCalledOnce();
  expect(screen.getByRole("option", { name: "Handbook" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  fireEvent.click(screen.getByRole("button", { name: "确认" }));
  await screen.findByText("Save failed");
  expect(close).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "确认" }));
  await waitFor(() => expect(close).toHaveBeenCalledOnce());
  expect(confirm.mock.calls[0][0]).toEqual(knowledgeBases);
  expect(confirm.mock.calls[1][0]).toEqual(knowledgeBases);
});

it("AIDP configuration accepts string IDs without local model checks and caps selections at ten", async () => {
  const confirm = vi.fn();
  const aidpKnowledge = Array.from({ length: 11 }, (_, i) => ({
    ...knowledgeBases[0],
    id: `kds:${i}`,
    name: `AIDP ${i}`,
    source: "aidp",
    embeddingModel: "unknown",
    documentCount: 0,
    chunkCount: 0,
  }));
  render(
    <KnowledgeDrawer
      open
      isAidpSearch
      maxSelect={10}
      knowledgeBases={aidpKnowledge}
      onClose={vi.fn()}
      onConfirm={confirm}
    />
  );
  await changePageSize(20);
  for (const kb of aidpKnowledge)
    fireEvent.click(screen.getByRole("option", { name: kb.name }));
  expect(screen.getByRole("option", { name: "AIDP 10" })).toHaveAttribute(
    "aria-selected",
    "false"
  );
  fireEvent.click(screen.getByRole("button", { name: "确认" }));
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
  expect(confirm.mock.calls[0][0].map((kb: KnowledgeBase) => kb.id)).toEqual(
    aidpKnowledge.slice(0, 10).map((kb) => kb.id)
  );
});
