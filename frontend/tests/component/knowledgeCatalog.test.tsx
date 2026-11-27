// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import KnowledgeBaseList from "../../app/[locale]/knowledges/components/knowledge/KnowledgeBaseList";
const menuPermissions = vi.hoisted(() => new Set(["kb:update", "kb:delete"]));
const tagDefinitions = vi.hoisted(() => vi.fn((): unknown[] => []));
vi.mock("@/hooks/permission/usePermission", () => ({
  usePermission: () => ({
    isReady: true,
    can: (permission: string) => menuPermissions.has(permission),
  }),
}));
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { tagManagementApi } from "@/services/tagManagementService";
import type { KnowledgeBase } from "@/types/knowledgeBase";

vi.mock("../../app/[locale]/i18n", () => ({ default: { language: "zh" } }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, args?: { count?: number }) =>
      args?.count === undefined ? key : `${key}:${args.count}`,
  }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: { tenantId: "tenant", role: "ADMIN" },
  }),
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({ data: { groups: [] } }),
}));
vi.mock("@/hooks/useTagManagement", () => ({
  useTagLibraries: () => ({
    data: [{ bucket_id: 1, bucket_key: "default_resource" }],
  }),
  useTagDefinitions: () => ({ data: tagDefinitions(), refresh: vi.fn() }),
}));
vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: { filterResourceIds: vi.fn() },
}));
vi.mock("@/services/knowledgeBaseService", () => ({
  default: {
    getKnowledgeBasesInfo: vi.fn(),
    previewBoundAgents: vi.fn(),
    deleteKnowledgeBase: vi.fn(),
  },
}));
vi.mock("@/components/permission/Can", () => ({
  Can: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/components/tag/ResourceTagChips", () => ({ default: () => null }));
vi.mock("@/components/tag/TagFilterControls", () => ({
  default: ({ onChange }: { onChange: (value: unknown[]) => void }) => (
    <button
      onClick={() => onChange([{ definition_id: 1, operator: "exists" }])}
    >
      apply-tag
    </button>
  ),
}));
vi.mock(
  "../../app/[locale]/knowledges/components/knowledge/PersonalKnowledgeBaseCapacityBar",
  () => ({ default: () => null })
);

function knowledge(id: number, permission = "EDIT"): KnowledgeBase {
  return {
    id: String(id),
    name: `Knowledge ${id}`,
    source: "nexent",
    permission,
    description: "Description",
    embeddingModel: "model",
    documentCount: 2,
    chunkCount: 3,
  } as KnowledgeBase;
}

const baseProps = () => ({
  knowledgeBases: [knowledge(1), knowledge(2)],
  activeKnowledgeBase: null,
  onClick: vi.fn(),
  onSync: vi.fn(),
  onCreateNew: vi.fn(),
  getModelDisplayName: (id: string) => id,
  onPageChange: vi.fn(),
  onPageSizeChange: vi.fn(),
});

describe("local knowledge catalog", () => {
  it("shows each saved summary and uses the default for an empty one", () => {
    const knowledgeBases = [
      { ...knowledge(1), description: "Approval workflow" },
      { ...knowledge(2), description: null },
    ];
    render(
      <KnowledgeBaseList {...baseProps()} knowledgeBases={knowledgeBases} />
    );
    expect(screen.getByText("Approval workflow")).toBeVisible();
    expect(screen.getByText("knowledgeBase.description.default")).toBeVisible();
  });

  it("keeps synchronization without a toolbar tag management or card menu", () => {
    render(<KnowledgeBaseList {...baseProps()} />);
    expect(
      screen.getByRole("button", { name: /knowledgeBase.button.sync/ })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "knowledgeBase.button.tagManagement",
      })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "skillRepository.common.moreActions",
      })
    ).not.toBeInTheDocument();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    tagDefinitions.mockReset().mockReturnValue([]);
    menuPermissions.clear();
    menuPermissions.add("kb:update");
    menuPermissions.add("kb:delete");
    vi.mocked(knowledgeBaseService.previewBoundAgents).mockReset();
    vi.mocked(knowledgeBaseService.deleteKnowledgeBase).mockReset();
  });

  it("hides bulk management without delete permission", () => {
    menuPermissions.delete("kb:delete");
    render(<KnowledgeBaseList {...baseProps()} />);
    expect(
      screen.queryByRole("button", { name: "knowledgeBase.batch.manage" })
    ).not.toBeInTheDocument();
  });

  it("selects only deletable knowledge bases and clears selection on page change", () => {
    const props = {
      ...baseProps(),
      knowledgeBases: [
        knowledge(1),
        knowledge(2, "READ_ONLY"),
        { ...knowledge(3), source: "datamate" },
      ],
      totalCount: 6,
      serverFiltered: true,
    };
    const { rerender } = render(
      <KnowledgeBaseList {...props} page={1} pageSize={3} />
    );
    fireEvent.click(
      screen.getByRole("button", { name: "knowledgeBase.batch.manage" })
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "knowledgeBase.batch.selectPage" })
    );
    expect(screen.getByRole("checkbox", { name: "Knowledge 1" })).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Knowledge 2" })
    ).toBeDisabled();
    expect(
      screen.getByRole("checkbox", { name: "Knowledge 3" })
    ).toBeDisabled();
    expect(
      screen.getByText("knowledgeBase.batch.selectedCount:1")
    ).toBeVisible();
    rerender(<KnowledgeBaseList {...props} page={2} pageSize={3} />);
    expect(
      screen.getByText("knowledgeBase.batch.selectedCount:0")
    ).toBeVisible();
    expect(props.onClick).not.toHaveBeenCalled();
  });

  it("previews deletion, cancels without mutations, and keeps failed targets selected after confirmation", async () => {
    const refresh = vi.fn();
    vi.mocked(knowledgeBaseService.previewBoundAgents).mockResolvedValue({
      agents: [{ agent_id: 5, display_name: "Bound agent" }],
    });
    vi.mocked(knowledgeBaseService.deleteKnowledgeBase).mockImplementation(
      async (id) => {
        if (id === "2") throw new Error("Blocked");
      }
    );
    render(<KnowledgeBaseList {...baseProps()} onCatalogRefresh={refresh} />);
    fireEvent.click(
      screen.getByRole("button", { name: "knowledgeBase.batch.manage" })
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "knowledgeBase.batch.selectPage" })
    );
    const toolbar = screen.getByRole("toolbar", {
      name: "knowledgeBase.batch.manage",
    });
    const deleteButton = within(toolbar).getByRole("button", {
      name: "knowledgeBase.batch.deleteSelected",
    });
    fireEvent.click(deleteButton);
    let dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findAllByText("Bound agent")).toHaveLength(2);
    fireEvent.click(
      within(dialog).getByRole("button", { name: "common.cancel" })
    );
    expect(knowledgeBaseService.deleteKnowledgeBase).not.toHaveBeenCalled();
    expect(
      screen.getByText("knowledgeBase.batch.selectedCount:2")
    ).toBeVisible();
    fireEvent.click(deleteButton);
    dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", {
      name: "knowledgeBase.batch.deleteSelected",
    });
    await waitFor(() => expect(confirm).toBeEnabled());
    fireEvent.click(confirm);

    expect(
      await screen.findByText("knowledgeBase.batch.partialFailure:1")
    ).toBeVisible();
    expect(knowledgeBaseService.deleteKnowledgeBase).toHaveBeenNthCalledWith(
      1,
      "1"
    );
    expect(knowledgeBaseService.deleteKnowledgeBase).toHaveBeenNthCalledWith(
      2,
      "2"
    );
    expect(
      screen.getByRole("checkbox", { name: "Knowledge 1" })
    ).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Knowledge 2" })).toBeChecked();
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("applies one tag from the dropdown and clears it with All tags", async () => {
    tagDefinitions.mockReturnValue([
      {
        definition_id: 10,
        definition_key: "topic",
        status: "active",
        values: [
          { value_id: 11, display_value: "Engineering", status: "active" },
          { value_id: 12, display_value: "Archived", status: "disabled" },
        ],
      },
    ]);
    vi.mocked(tagManagementApi.filterResourceIds).mockResolvedValue({
      resource_type: "knowledge_base",
      matched_resource_ids: ["1"],
    });
    const props = baseProps();
    render(<KnowledgeBaseList {...props} />);

    fireEvent.click(
      screen.getByRole("button", { name: "knowledgeBase.tagFilter.all" })
    );
    expect(screen.queryByText("Archived")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByText("Engineering"));

    await waitFor(() => expect(screen.queryByText("Knowledge 2")).toBeNull());
    expect(screen.getByText("Knowledge 1")).toBeVisible();
    expect(tagManagementApi.filterResourceIds).toHaveBeenCalledWith(
      "knowledge_base",
      ["1", "2"],
      [{ definition_id: 10, value_ids: [11] }]
    );
    expect(props.onPageChange).toHaveBeenCalledWith(1);

    fireEvent.click(screen.getByRole("button", { name: "Engineering" }));
    fireEvent.click(await screen.findByText("knowledgeBase.tagFilter.all"));
    expect(await screen.findByText("Knowledge 2")).toBeVisible();
  });

  it("opens a card directly and keeps creation and card metadata available", () => {
    const props = baseProps();
    const { container } = render(<KnowledgeBaseList {...props} />);
    expect(
      screen.getByRole("heading", { name: "sidebar.knowledgeBaseConfig" })
    ).toBeVisible();
    expect(
      screen.queryByText("knowledgeBase.page.all")
    ).not.toBeInTheDocument();
    expect(container.querySelectorAll("article")).toHaveLength(2);
    fireEvent.click(
      screen.getByRole("button", { name: "knowledgeBase.card.create" })
    );
    expect(props.onCreateNew).toHaveBeenCalledOnce();
    const card = container.querySelector("article")!;
    fireEvent.click(card);
    expect(props.onClick).toHaveBeenCalledExactlyOnceWith(
      props.knowledgeBases[0]
    );
    expect(
      within(card).queryByRole("button", {
        name: "skillRepository.common.moreActions",
      })
    ).not.toBeInTheDocument();
    expect(within(card).getByText(/knowledgeBase.tag.documents/)).toBeVisible();
    expect(within(card).getByText(/knowledgeBase.tag.chunks/)).toBeVisible();
    expect(within(card).getByText(/knowledgeBase.tag.updatedAt/)).toBeVisible();
    expect(within(card).getByText("model").className).not.toContain("rounded");
  });

  it("shows limited and unlimited capacity inline without progress", () => {
    const quotaUsage = {
      breakdown: [
        {
          index_name: "1",
          actual_bytes: 512,
          actual_readable: "512 B",
          soft_quota_bytes: 1024,
          soft_quota_readable: "1 KB",
          usage_pct: 50,
          kb_warning_level: "normal",
        },
        {
          index_name: "2",
          actual_bytes: 0,
          actual_readable: "0 B",
          soft_quota_bytes: null,
          usage_pct: null,
          kb_warning_level: "normal",
        },
      ],
    } as import("@/types/quota").QuotaUsageResponse;
    render(<KnowledgeBaseList {...baseProps()} quotaUsage={quotaUsage} />);
    const capacities = screen.getAllByTestId("knowledge-capacity");
    expect(capacities[0]).toHaveTextContent("512 B/1 KB");
    expect(
      within(capacities[0]).queryByRole("progressbar")
    ).not.toBeInTheDocument();
    expect(capacities[1]).toHaveTextContent(
      "0 B/knowledgeBase.capacity.unlimited"
    );
    expect(
      within(capacities[1]).queryByRole("progressbar")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("knowledgeBase.card.viewDocuments")
    ).not.toBeInTheDocument();
  });

  it("reserves a single fixed-height tag row", () => {
    render(<KnowledgeBaseList {...baseProps()} />);
    expect(screen.getAllByTestId("knowledge-tags")[0]).toHaveClass("h-6");
  });

  it("pages a supplied local collection and clamps an out-of-range page", () => {
    const props = {
      ...baseProps(),
      knowledgeBases: Array.from({ length: 25 }, (_, i) => knowledge(i + 1)),
    };
    const { container, rerender } = render(
      <KnowledgeBaseList {...props} page={2} pageSize={12} />
    );
    expect(container.querySelectorAll("article")).toHaveLength(12);
    expect(screen.getByText("Knowledge 13")).toBeVisible();
    expect(screen.queryByText("Knowledge 1")).not.toBeInTheDocument();
    rerender(<KnowledgeBaseList {...props} page={4} pageSize={12} />);
    expect(props.onPageChange).toHaveBeenCalledWith(3);
    expect(container.querySelectorAll("article")).toHaveLength(1);
  });

  it("uses server total without slicing a server page a second time", () => {
    const props = baseProps();
    const { container } = render(
      <KnowledgeBaseList
        {...props}
        page={2}
        pageSize={12}
        totalCount={30}
        serverFiltered
      />
    );
    expect(container.querySelectorAll("article")).toHaveLength(2);
    expect(screen.getByText("agentConfig.list.total:30")).toBeVisible();
    fireEvent.change(
      screen.getByRole("spinbutton", { name: "agentConfig.list.jumpPage" }),
      { target: { value: "3" } }
    );
    fireEvent.click(
      screen.getByRole("button", { name: "agentConfig.list.jump" })
    );
    expect(props.onPageChange).toHaveBeenCalledWith(3);
  });

  it("shows retry rather than an empty catalog on failure", () => {
    const props = baseProps();
    const retry = vi.fn();
    const { container } = render(
      <KnowledgeBaseList
        {...props}
        error="Catalog unavailable"
        onRetry={retry}
      />
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Catalog unavailable");
    expect(container.querySelectorAll("article")).toHaveLength(0);
    expect(
      screen.queryByText("knowledgeBase.list.empty")
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "repository.common.retry" })
    );
    expect(retry).toHaveBeenCalledOnce();
  });

  it("selects one through four columns at actual content-width boundaries", () => {
    const observers: ResizeObserverCallback[] = [];
    let width = 320;
    const original = window.ResizeObserver;
    window.ResizeObserver = class {
      constructor(callback: ResizeObserverCallback) {
        observers.push(callback);
      }
      observe() {}
      disconnect() {}
      unobserve() {}
    } as typeof ResizeObserver;
    const widthSpy = vi
      .spyOn(HTMLElement.prototype, "clientWidth", "get")
      .mockImplementation(() => width);
    try {
      render(<KnowledgeBaseList {...baseProps()} />);
      const grid = screen.getByTestId("knowledge-catalog-grid");
      for (const [nextWidth, columns] of [
        [320, 1],
        [655, 1],
        [656, 2],
        [991, 2],
        [992, 3],
        [1327, 3],
        [1328, 4],
        [2200, 4],
        [280, 1],
      ]) {
        width = nextWidth;
        act(() =>
          observers.forEach((callback) => callback([], {} as ResizeObserver))
        );
        expect(grid.style.gridTemplateColumns).toBe(
          `repeat(${columns}, minmax(0, 1fr))`
        );
      }
    } finally {
      widthSpy.mockRestore();
      window.ResizeObserver = original;
    }
  });

  it("finds tag matches outside the current server page", async () => {
    vi.mocked(knowledgeBaseService.getKnowledgeBasesInfo)
      .mockResolvedValueOnce({
        knowledgeBases: [knowledge(1)],
        hasMore: true,
        nextOffset: 100,
        total: 101,
      })
      .mockResolvedValueOnce({
        knowledgeBases: [knowledge(101)],
        hasMore: false,
        total: 101,
      });
    vi.mocked(tagManagementApi.filterResourceIds).mockResolvedValue({
      matched_resource_ids: ["101"],
    } as never);
    render(
      <KnowledgeBaseList {...baseProps()} serverFiltered totalCount={101} />
    );
    fireEvent.click(
      screen.getByRole("button", { name: "knowledgeBase.filter.button" })
    );
    fireEvent.click(await screen.findByRole("button", { name: "apply-tag" }));
    await waitFor(() =>
      expect(screen.getByText("Knowledge 101")).toBeVisible()
    );
    expect(knowledgeBaseService.getKnowledgeBasesInfo).toHaveBeenLastCalledWith(
      true,
      false,
      null,
      null,
      expect.objectContaining({ offset: 100, limit: 100 }),
      { strict: true }
    );
    expect(tagManagementApi.filterResourceIds).toHaveBeenCalledWith(
      "knowledge_base",
      ["1", "101"],
      expect.any(Array)
    );
    expect(screen.getByText("agentConfig.list.total:1")).toBeVisible();
  }, 15000);
});
