/**
 * 
 * MCP 结构化标签分配/展示：详情弹窗赋值、Mine 卡片 Chips 展示、发布只读继承与权限编辑｜核心流程
 */
import type { ReactNode } from "react";
import type { TFunction } from "i18next";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  McpHealthStatus,
  McpServiceStatus,
  McpSource,
  McpTransportType,
} from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";
import type {
  TagAssignment,
  TagAssignmentValue,
  TagDefinition,
  TagLibrary,
} from "@/types/tagManagement";
import { getTagSearchPredicates } from "@/lib/systemTagLabels";
import { tagManagementApi } from "@/services/tagManagementService";

import ResourceTagChips from "@/components/tag/ResourceTagChips";
import ResourceTagAssignmentModal from "@/components/tag/ResourceTagAssignmentModal";
import MineMcpServiceCard from "@/app/[locale]/mcp-space/components/MineMcpServiceCard";
import McpServiceDetailModal from "@/app/[locale]/mcp-space/components/McpServiceDetailModal";
import PublishConfirmModal from "@/app/[locale]/mcp-space/components/PublishConfirmModal";

vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && typeof opts.count === "number" ? `${key}:${opts.count}` : key,
    i18n: { language: "zh", changeLanguage: vi.fn() },
  }),
}));

vi.mock("antd", async (importOriginal) => {
  const actual = await importOriginal<typeof import("antd")>();
  const noop = vi.fn();
  return {
    ...actual,
    App: {
      ...actual.App,
      useApp: () => ({
        message: { success: noop, error: noop, warning: noop, info: noop },
        modal: { error: noop, confirm: noop, info: noop, warning: noop, success: noop },
        notification: { error: noop, info: noop, success: noop, warning: noop },
      }),
    },
  };
});

vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: {
    listLibraries: vi.fn(),
    listDefinitions: vi.fn(),
    getAssignments: vi.fn(),
    replaceAssignments: vi.fn(),
    replaceAssignmentsBulk: vi.fn(),
    filterResourceIds: vi.fn(),
  },
  buildResourcePredicate: (definitionId: number, valueIds: number[]) => ({
    definition_id: definitionId,
    value_ids: valueIds,
  }),
  buildDocumentPredicate: (definitionId: number, valueIds: number[]) => ({
    definition_id: definitionId,
    value_ids: valueIds,
  }),
}));

vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({ data: { groups: [] }, allGroupIds: [] }),
  useGroupDetails: () => ({ groups: [] }),
}));

vi.mock("@/components/permission/Can", () => ({
  Can: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/providers/AuthorizationProvider", () => ({
  AuthorizationProvider: ({ children }: { children?: ReactNode }) => <>{children}</>,
  useAuthorizationContext: () => ({ user: { tenantId: "tenant-1" } }),
}));

vi.mock("@/hooks/mcpTools/useMcpServiceDetail", () => ({
  useMcpServiceDetail: ({ selectedService }: { selectedService: McpServiceItem | null }) => ({
    draft: selectedService,
    setDraft: vi.fn(),
    addTag: vi.fn(),
    removeTag: vi.fn(),
    tagSaving: false,
    hasUnsavedChanges: false,
    healthChecking: false,
    runHealthCheck: vi.fn(),
    toolsState: { visible: false, tools: [] },
    loadingTools: false,
    loadTools: vi.fn(),
    refreshTools: vi.fn(),
    closeToolsModal: vi.fn(),
    publishing: false,
    publish: vi.fn(async () => true),
    saving: false,
    save: vi.fn(async () => true),
    deleting: false,
    remove: vi.fn(),
  }),
}));

const defaultLibrary: TagLibrary = {
  bucket_id: 1,
  bucket_key: "default_resource",
  bucket_name: "Default Resource",
  status: "active",
  resource_types: ["mcp_service"],
  definition_count: 2,
  definition_capacity: 100,
};

const definitions: TagDefinition[] = [
  {
    definition_id: 11,
    bucket_id: 1,
    definition_key: "scenario",
    definition_name: "Scenario",
    selection_mode: "single_select",
    sort_order: 1,
    status: "active",
    active_value_count: 2,
    value_capacity: 20,
    values: [
      { value_id: 111, display_value: "online", normalized_value: "online", sort_order: 1, status: "active" },
      { value_id: 112, display_value: "offline", normalized_value: "offline", sort_order: 2, status: "active" },
    ],
  },
  {
    definition_id: 12,
    bucket_id: 1,
    definition_key: "team",
    definition_name: "Team",
    selection_mode: "multi_select",
    sort_order: 2,
    status: "active",
    active_value_count: 3,
    value_capacity: 20,
    values: [
      { value_id: 121, display_value: "core", normalized_value: "core", sort_order: 1, status: "active" },
      { value_id: 122, display_value: "growth", normalized_value: "growth", sort_order: 2, status: "active" },
      { value_id: 123, display_value: "research", normalized_value: "research", sort_order: 3, status: "active" },
    ],
  },
];

const assignmentValues: TagAssignmentValue[] = [
  { definition_id: 11, definition_key: "scenario", definition_name: "Scenario", selection_mode: "single_select", value_id: 111, display_value: "online", value_status: "active" },
  { definition_id: 12, definition_key: "team", definition_name: "Team", selection_mode: "multi_select", value_id: 121, display_value: "core", value_status: "active" },
];

const assignment: TagAssignment = {
  resource_type: "mcp_service",
  resource_id: "100",
  assignment_count: 2,
  assignment_capacity: 100,
  assignments: assignmentValues,
};

const baseService: McpServiceItem = {
  mcpId: 100,
  name: "my-mcp",
  description: "a test mcp",
  source: McpSource.LOCAL,
  enabled: McpServiceStatus.ENABLED,
  updatedAt: "2026-01-01T00:00:00Z",
  createTime: "2026-01-01T00:00:00Z",
  tags: ["legacy-tag"],
  transportType: McpTransportType.HTTP,
  serverUrl: "https://example.com",
  version: "1.0.0",
  tools: [],
  healthStatus: McpHealthStatus.UNCHECKED,
  permission: "EDIT",
};

afterEach(() => cleanup());

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(tagManagementApi.listLibraries).mockResolvedValue([defaultLibrary]);
  vi.mocked(tagManagementApi.listDefinitions).mockResolvedValue(definitions);
  vi.mocked(tagManagementApi.getAssignments).mockResolvedValue(assignment);
  vi.mocked(tagManagementApi.replaceAssignments).mockResolvedValue(assignment);
  vi.mocked(tagManagementApi.replaceAssignmentsBulk).mockResolvedValue([]);
  vi.mocked(tagManagementApi.filterResourceIds).mockResolvedValue({
    resource_type: "mcp_service",
    matched_resource_ids: ["100"],
  });
});

describe("ResourceTagChips", () => {
  it("UT-FE-AUTO-B3718E0BBA849044 renders structured tags for mcp_service without mixing free-text tags", async () => {
    render(<ResourceTagChips resourceType="mcp_service" resourceId="100" max={3} />);
    expect(await screen.findByText("online")).toBeTruthy();
    expect(screen.getByText("core")).toBeTruthy();
    expect(vi.mocked(tagManagementApi.getAssignments)).toHaveBeenCalledWith(
      "mcp_service",
      "100",
      {}
    );
  });

  it("truncates chips to the max parameter and shows overflow", async () => {
    vi.mocked(tagManagementApi.getAssignments).mockResolvedValue({
      ...assignment,
      assignments: [
        assignmentValues[0],
        assignmentValues[1],
        { definition_id: 12, definition_key: "team", definition_name: "Team", selection_mode: "multi_select", value_id: 122, display_value: "growth", value_status: "active" },
        { definition_id: 12, definition_key: "team", definition_name: "Team", selection_mode: "multi_select", value_id: 123, display_value: "research", value_status: "active" },
      ],
    });
    render(<ResourceTagChips resourceType="mcp_service" resourceId="100" max={3} />);
    await screen.findByText("online");
    expect(screen.queryByText("research")).toBeNull();
    expect(screen.getByText("+1")).toBeTruthy();
  });

  it("falls back to empty state when the assignment request fails", async () => {
    vi.mocked(tagManagementApi.getAssignments).mockRejectedValue(new Error("boom"));
    const { container } = render(
      <ResourceTagChips
        resourceType="mcp_service"
        resourceId="100"
        emptyText={<span>—</span>}
      />
    );
    await waitFor(() => expect(container.textContent).toContain("—"));
  });
});

describe("MineMcpServiceCard", () => {
  it("shows free-text tags truncated and renders structured chips for local items", async () => {
    const service: McpServiceItem = {
      ...baseService,
      tags: ["alpha", "beta", "gamma", "delta", "epsilon"],
    };
    render(
      <MineMcpServiceCard
        item={{ kind: "local", service }}
        onEditLocal={vi.fn()}
        onEditCommunity={vi.fn()}
        onToggle={vi.fn()}
        onSubmitVersionUpdate={vi.fn()}
        onUnpublishOnline={vi.fn()}
        onDelete={vi.fn()}
      />
    );
    expect(screen.getByText("alpha")).toBeTruthy();
    expect(screen.getByText("beta")).toBeTruthy();
    expect(screen.getByText("gamma")).toBeTruthy();
    expect(screen.queryByText("delta")).toBeNull();
    expect(screen.getByText("+2")).toBeTruthy();
    expect(await screen.findByText("core")).toBeTruthy();
    expect(vi.mocked(tagManagementApi.getAssignments)).toHaveBeenCalledWith(
      "mcp_service",
      "100",
      {}
    );
  });
});

describe("McpServiceDetailModal", () => {
  it("EDIT permission enables edit-tags and opens the assignment modal", async () => {
    render(<McpServiceDetailModal selectedService={baseService} onClose={vi.fn()} />);
    const editButton = await screen.findByRole("button", {
      name: "tagManagement.action.editTags",
    });
    expect(editButton.disabled).toBe(false);

    fireEvent.click(editButton);
    expect(await screen.findByText("tagManagement.action.manageDefinitions")).toBeTruthy();
  });

  it("READ_ONLY disables edit-tags and save entry", async () => {
    const readOnly: McpServiceItem = { ...baseService, permission: "READ_ONLY" };
    render(<McpServiceDetailModal selectedService={readOnly} onClose={vi.fn()} />);

    const editButton = await screen.findByRole("button", {
      name: "tagManagement.action.editTags",
    });
    expect(editButton.disabled).toBe(true);

    const saveButton = screen.getByRole("button", {
      name: "mcpTools.detail.noEditPermission",
    });
    expect(saveButton.disabled).toBe(true);
  });
});

describe("ResourceTagAssignmentModal", () => {
  it("saves selection via replaceAssignments with correct resource identity and closes", async () => {
    const onClose = vi.fn();
    render(
      <ResourceTagAssignmentModal
        open
        onClose={onClose}
        resourceType="mcp_service"
        resourceId="100"
        definitions={definitions}
        canEdit
      />
    );

    await screen.findByText("2/100");
    fireEvent.click(screen.getByRole("button", { name: "tagManagement.action.save" }));

    await waitFor(() => {
      expect(vi.mocked(tagManagementApi.replaceAssignments)).toHaveBeenCalledWith(
        "mcp_service",
        "100",
        { value_ids: [111, 121] },
        expect.anything()
      );
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});

describe("PublishConfirmModal", () => {
  it("renders inherited structured tags read-only and submits inherited tags", async () => {
    const onConfirm = vi.fn(async () => true);
    render(
      <PublishConfirmModal
        open
        source={baseService}
        publishing={false}
        tenantId="tenant-1"
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />
    );

    expect(await screen.findByText("core")).toBeTruthy();
    expect(screen.getByText("online")).toBeTruthy();
    expect(screen.getByText("mcpTools.publish.tagsInheritedHint")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "mcpTools.community.publish" }));

    await waitFor(() => expect(onConfirm).toHaveBeenCalled());
    const submitted = onConfirm.mock.calls[0][0] as { tags: string[] };
    expect(submitted.tags).toEqual(["online", "core"]);
  });
});

describe("getTagSearchPredicates", () => {
  const t: TFunction = ((key: string) => key) as unknown as TFunction;

  it("matches definition key and active value to build search predicates", () => {
    expect(getTagSearchPredicates(definitions, "core", t)).toEqual([
      { definition_id: 12, value_ids: [121] },
    ]);
  });

  it("returns empty predicates for a blank search", () => {
    expect(getTagSearchPredicates(definitions, "   ", t)).toEqual([]);
  });
});
