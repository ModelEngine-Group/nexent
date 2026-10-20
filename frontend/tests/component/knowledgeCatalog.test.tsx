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
  useTagDefinitions: () => ({ data: [], refresh: vi.fn() }),
}));
vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: { filterResourceIds: vi.fn() },
}));
vi.mock("@/services/knowledgeBaseService", () => ({
  default: { getKnowledgeBasesInfo: vi.fn() },
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
vi.mock("@/components/tag/ResourceTagAssignmentModal", () => ({
  default: ({ open, canEdit }: { open: boolean; canEdit: boolean }) =>
    open ? <div data-testid="assign-dialog">{String(canEdit)}</div> : null,
}));
vi.mock("@/components/tag/TagDefinitionManagementModal", () => ({
  default: () => null,
}));
vi.mock(
  "../../app/[locale]/knowledges/components/knowledge/KnowledgeBaseEditModal",
  () => ({ KnowledgeBaseEditModal: () => null })
);
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
  onDelete: vi.fn(),
  onSync: vi.fn(),
  onCreateNew: vi.fn(),
  getModelDisplayName: (id: string) => id,
  onPageChange: vi.fn(),
  onPageSizeChange: vi.fn(),
});

describe("local knowledge catalog", () => {
  it("removes toolbar tag management while retaining synchronization and resource actions", () => {
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
      screen.getAllByRole("button", {
        name: "skillRepository.common.moreActions",
      })
    ).toHaveLength(2);
  });

  beforeEach(() => {
    vi.clearAllMocks();
    menuPermissions.clear();
    menuPermissions.add("kb:update");
    menuPermissions.add("kb:delete");
  });

  it("hides menu actions without the corresponding permission", async () => {
    menuPermissions.delete("kb:update");
    const props = { ...baseProps(), knowledgeBases: [knowledge(1)] };
    render(<KnowledgeBaseList {...props} />);
    fireEvent.click(
      screen.getByRole("button", { name: "skillRepository.common.moreActions" })
    );
    await waitFor(() =>
      expect(
        screen.getByRole("menuitem", { name: "common.delete" })
      ).toBeVisible()
    );
    expect(
      screen.queryByRole("menuitem", { name: "common.edit" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", {
        name: "knowledgeBase.action.assignTags",
      })
    ).not.toBeInTheDocument();
  });

  it("has one create entry and independent card/document/menu interactions", async () => {
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
    props.onClick.mockClear();
    fireEvent.click(
      within(card).getByRole("button", {
        name: "skillRepository.common.moreActions",
      })
    );
    const deleteItem = await screen.findByRole("menuitem", {
      name: "common.delete",
    });
    expect(deleteItem.querySelector("svg")).toBeNull();
    fireEvent.click(deleteItem);
    expect(within(card).getAllByText("|")).toHaveLength(2);
    expect(within(card).getByText("model").className).not.toContain("rounded");
    expect(props.onDelete).toHaveBeenCalledWith("1");
    expect(props.onClick).not.toHaveBeenCalled();
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

  it("retains read-only tag assignment while hiding edit and delete", async () => {
    const props = {
      ...baseProps(),
      knowledgeBases: [knowledge(1, "READ_ONLY")],
    };
    render(<KnowledgeBaseList {...props} />);
    fireEvent.click(
      screen.getByRole("button", { name: "skillRepository.common.moreActions" })
    );
    expect(
      screen.queryByRole("menuitem", { name: "common.delete" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: "common.edit" })
    ).not.toBeInTheDocument();
    fireEvent.click(
      await screen.findByRole("menuitem", {
        name: "knowledgeBase.action.assignTags",
      })
    );
    expect(screen.getByTestId("assign-dialog")).toHaveTextContent("false");
    expect(props.onClick).not.toHaveBeenCalled();
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
