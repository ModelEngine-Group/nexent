// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { App } from "antd";
import { describe, expect, it, vi } from "vitest";
import { render, changePageSize } from "./resourceDrawerTestUtils";
import { ToolDrawer } from "@/components/resource-picker/ToolDrawer";
import { tagManagementApi } from "@/services/tagManagementService";

const state = vi.hoisted(() => ({
  editedAgent: { tools: [] },
  updateTools: vi.fn(),
  merge: vi.fn(async () => []),
  tools: [
    {
      id: "1",
      name: "Alpha tool",
      description: "Details",
      source: "local",
      labels: ["Team"],
      initParams: [],
    },
    {
      id: "2",
      name: "Blocked tool",
      description: "Needs image support",
      source: "local",
      initParams: [],
    },
  ],
}));
vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: {
    listLibraries: vi.fn(async () => []),
    listDefinitions: vi.fn(async () => []),
    getAssignments: vi.fn(async () => ({ assignments: [] })),
    getToolAssignmentsBatch: vi.fn(async () => []),
    filterResourceIds: vi.fn(async () => ({ matched_resource_ids: [] })),
  },
}));
vi.mock("@/services/mcpService", () => ({
  updateToolList: vi.fn(async () => ({ success: true })),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));
vi.mock("@/hooks/agent/useToolList", () => ({
  useToolList: () => ({ selectableTools: state.tools, invalidate: vi.fn() }),
}));
vi.mock("@/hooks/mcp/useMcpServerList", () => ({
  useMcpServerList: () => ({ serverList: [] }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { tenantId: "tenant" } }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (value: typeof state) => unknown) =>
    selector(state),
}));
vi.mock("@/hooks/useKnowledgeBaseSelector", () => ({
  usePrefetchKnowledgeBases: () => ({ prefetchKnowledgeBases: vi.fn() }),
}));
vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({ isImageUnderstandingAvailable: false }),
}));
vi.mock("@/hooks/useConfirmModal", () => ({
  useConfirmModal: () => ({ confirm: vi.fn() }),
}));
vi.mock(
  "@/app/agents/[agentId]/components/capability/tool/useMergedToolParams",
  () => ({ useMergedToolParams: () => state.merge })
);
vi.mock("@/app/agents/components/capability/tool/utils", () => ({
  TOOLS_REQUIRING_IMAGE_UNDERSTANDING: ["Blocked tool"],
  TOOLS_REQUIRING_VIDEO_UNDERSTANDING: [],
  TOOLS_REQUIRING_AUDIO_UNDERSTANDING: [],
  TOOLS_REQUIRING_EMBEDDING: [],
  getToolKbType: () => null,
  getToolLabels: (tool: { labels?: string[] }) => tool.labels ?? [],
}));
vi.mock("@/app/agents/components/capability/tool/ToolConfigModal", () => ({
  default: ({ isOpen }: { isOpen: boolean }) =>
    isOpen ? <div>Tool configuration modal</div> : null,
}));

describe("ToolDrawer shared rows", () => {
  it("uses the chosen page size for tool rows and resets the current page", async () => {
    const original = state.tools;
    state.tools = Array.from({ length: 21 }, (_, index) => ({
      ...original[0],
      id: String(index + 1),
      name: `Tool ${String(index + 1).padStart(2, "0")}`,
    }));
    try {
      render(
        <App>
          <ToolDrawer open onClose={vi.fn()} />
        </App>
      );
      expect(screen.getAllByRole("option")).toHaveLength(10);
      await waitFor(() =>
        expect(
          tagManagementApi.getToolAssignmentsBatch
        ).toHaveBeenCalledExactlyOnceWith(
          Array.from({ length: 10 }, (_, index) => String(index + 1))
        )
      );
      expect(tagManagementApi.getAssignments).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: "3" }));
      expect(
        screen.getByRole("option", { name: "Tool 21" })
      ).toBeInTheDocument();
      await waitFor(() =>
        expect(
          tagManagementApi.getToolAssignmentsBatch
        ).toHaveBeenLastCalledWith(["21"])
      );
      await changePageSize(20);
      expect(screen.getAllByRole("option")).toHaveLength(20);
      expect(
        screen.getByRole("option", { name: "Tool 01" })
      ).toBeInTheDocument();
      await waitFor(() =>
        expect(
          tagManagementApi.getToolAssignmentsBatch
        ).toHaveBeenLastCalledWith(
          Array.from({ length: 20 }, (_, index) => String(index + 1))
        )
      );
      expect(tagManagementApi.getAssignments).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: "刷新" }));
      await waitFor(() =>
        expect(tagManagementApi.getToolAssignmentsBatch).toHaveBeenCalledTimes(
          4
        )
      );
    } finally {
      state.tools = original;
    }
  });

  it("keeps configuration separate from selection without a tag management entry", async () => {
    const props = { open: true, onClose: vi.fn() };
    render(
      <App>
        <ToolDrawer {...props} />
      </App>
    );
    expect(
      screen.queryByRole("button", { name: /管理标签|标签管理/ })
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: "repository.tagFilter.button" })
    ).toBeInTheDocument();
    const option = screen.getByRole("option", { name: "Alpha tool" });
    expect(option.firstElementChild).toHaveAttribute("data-resource-checkbox");
    expect(within(option).getByText("Team")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "toolPool.configure" }));
    await screen.findByText("Tool configuration modal");
    expect(option).toHaveAttribute("aria-selected", "false");
    fireEvent.click(option);
    await waitFor(() =>
      expect(option).toHaveAttribute("aria-selected", "true")
    );
    expect(state.updateTools).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(state.updateTools).toHaveBeenCalledWith([state.tools[0]]);
  });

  it("prevents unavailable tools from being selected or configured", () => {
    render(
      <App>
        <ToolDrawer open onClose={vi.fn()} />
      </App>
    );
    const option = screen.getByRole("option", { name: "Blocked tool" });
    expect(option).toBeDisabled();
    fireEvent.click(option);
    expect(option).toHaveAttribute("aria-selected", "false");
    expect(
      within(option.closest("[data-resource-view]") as HTMLElement).queryByRole(
        "button"
      )
    ).toBeNull();
  });
});
