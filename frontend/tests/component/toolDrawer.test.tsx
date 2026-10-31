// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { McpServer, Tool, ToolParam } from "@/types/agentConfig";
import { render, changePageSize } from "./resourceDrawerTestUtils";
import { ToolDrawer } from "@/components/resource-picker/ToolDrawer";
import { tagManagementApi } from "@/services/tagManagementService";

const state = vi.hoisted(() => ({
  editedAgent: { tools: [] as Tool[] },
  updateTools: vi.fn(),
  merge: vi.fn<(tool: Tool) => Promise<ToolParam[] | null>>(async () => []),
  servers: [] as McpServer[],
  confirm: vi.fn(),
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
  ] as Tool[],
}));
vi.mock("@/services/mcpService", () => ({
  updateToolList: vi.fn(async () => ({
    success: true,
    data: {},
    message: "ok",
  })),
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
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string | { name?: string; count?: number }) => {
      if (typeof fallback === "string") return fallback;
      if (fallback?.name) return `${key} ${fallback.name}`;
      if (fallback?.count !== undefined) return `${fallback.count} tools`;
      return key;
    },
  }),
}));
vi.mock("@/hooks/agent/useToolList", () => ({
  useToolList: () => ({ selectableTools: state.tools, invalidate: vi.fn() }),
}));
vi.mock("@/hooks/mcp/useMcpServerList", () => ({
  useMcpServerList: () => ({ serverList: state.servers }),
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
  useConfirmModal: () => ({ confirm: state.confirm }),
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

function mcpTool(id: string, name: string, usage = "charts"): Tool {
  return {
    id,
    name,
    usage,
    description: `Description of ${name}`,
    source: "mcp",
    initParams: [],
  } as Tool;
}

function service(name: string): McpServer {
  return {
    service_name: name,
    mcp_url: `https://${name}.example/mcp`,
    mcp_id: 1,
    enabled: true,
    status: true,
    description: `${name} service description`,
    tags: ["visual"],
  };
}

function showPicker() {
  return render(
    <App>
      <ToolDrawer open onClose={vi.fn()} />
    </App>
  );
}

function groupCheckbox(name = "charts") {
  return screen.getByRole("checkbox", {
    name: `toolPool.mcpSelectService ${name}`,
  });
}

describe("ToolDrawer MCP service groups", () => {
  beforeEach(() => {
    state.tools = [
      mcpTool("11", "bar_chart"),
      mcpTool("12", "line_chart"),
      mcpTool("13", "read_file", "files"),
    ];
    state.servers = [service("charts"), service("files")];
    state.editedAgent.tools = [];
    state.merge.mockReset().mockResolvedValue([]);
  });

  it("expands service tools without selecting and retains partial selection through collapse", async () => {
    showPicker();
    const expand = await screen.findByRole("button", {
      name: "charts",
      expanded: false,
    });
    expect(screen.queryByRole("option", { name: "bar_chart" })).toBeNull();
    expect(screen.getByText("charts service description")).toBeInTheDocument();
    expect(screen.getByText("2 tools")).toBeInTheDocument();
    fireEvent.click(expand);
    expect(screen.getByText("Description of bar_chart")).toBeInTheDocument();
    expect(state.merge).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("option", { name: "bar_chart" }));
    await waitFor(() =>
      expect(groupCheckbox()).toHaveAttribute("aria-checked", "mixed")
    );
    fireEvent.click(expand);
    fireEvent.click(expand);
    expect(screen.getByRole("option", { name: "bar_chart" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(screen.getByRole("option", { name: "line_chart" })).toHaveAttribute(
      "aria-selected",
      "false"
    );
    expect(state.updateTools).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(state.updateTools).toHaveBeenCalledWith([state.tools[0]]);
  });

  it("selects remaining service tools and deselects only that service", async () => {
    state.editedAgent.tools = [state.tools[0], state.tools[2]];
    showPicker();
    const checkbox = await screen.findByRole("checkbox", {
      name: "toolPool.mcpSelectService charts",
    });
    expect(checkbox).toHaveAttribute("aria-checked", "mixed");
    fireEvent.click(checkbox);
    await waitFor(() =>
      expect(checkbox).toHaveAttribute("aria-checked", "true")
    );
    fireEvent.click(checkbox);
    expect(checkbox).toHaveAttribute("aria-checked", "false");
    expect(groupCheckbox("files")).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(state.updateTools).toHaveBeenCalledWith([state.tools[2]]);
  });

  it("discards group edits on cancellation and restores the saved tool subset on reopen", async () => {
    state.editedAgent.tools = [state.tools[0]];
    const onClose = vi.fn();
    const view = render(
      <App>
        <ToolDrawer open onClose={onClose} />
      </App>
    );
    fireEvent.click(
      await screen.findByRole("checkbox", {
        name: "toolPool.mcpSelectService charts",
      })
    );
    await waitFor(() =>
      expect(groupCheckbox()).toHaveAttribute("aria-checked", "true")
    );
    fireEvent.click(screen.getAllByRole("button", { name: "关闭" })[0]);
    expect(onClose).toHaveBeenCalledOnce();
    expect(state.updateTools).not.toHaveBeenCalled();
    view.rerender(
      <App>
        <ToolDrawer open={false} onClose={onClose} />
      </App>
    );
    view.rerender(
      <App>
        <ToolDrawer open onClose={onClose} />
      </App>
    );
    await waitFor(() =>
      expect(groupCheckbox()).toHaveAttribute("aria-checked", "mixed")
    );
  });

  it("paginates services without splitting children and selects only the current MCP page", async () => {
    state.tools = Array.from({ length: 11 }, (_, index) =>
      mcpTool(
        String(index + 20),
        `tool_${index}`,
        `service_${String(index).padStart(2, "0")}`
      )
    );
    state.tools.push(mcpTool("99", "second_child", "service_00"));
    state.servers = [];
    showPicker();
    await screen.findByRole("button", { name: "service_00" });
    expect(screen.queryByRole("button", { name: "service_10" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "service_00" }));
    expect(screen.getAllByRole("option")).toHaveLength(2);
    fireEvent.click(
      screen.getByRole("checkbox", { name: "toolPool.mcpSelectPage" })
    );
    await waitFor(() =>
      expect(groupCheckbox("service_00")).toHaveAttribute(
        "aria-checked",
        "true"
      )
    );
    expect(state.merge).toHaveBeenCalledTimes(11);
    fireEvent.click(screen.getByRole("button", { name: "2" }));
    expect(groupCheckbox("service_10")).toHaveAttribute(
      "aria-checked",
      "false"
    );
    fireEvent.click(groupCheckbox("service_10"));
    await waitFor(() =>
      expect(groupCheckbox("service_10")).toHaveAttribute(
        "aria-checked",
        "true"
      )
    );
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(state.updateTools.mock.calls[0][0]).toHaveLength(12);
  });

  it("searches service metadata and limits group selection to matching tools while retaining hidden selections", async () => {
    state.editedAgent.tools = [state.tools[2]];
    showPicker();
    await screen.findByRole("button", { name: "charts" });
    const search = screen.getByPlaceholderText(
      "toolPool.searchToolsPlaceholder"
    );
    fireEvent.change(search, { target: { value: "charts service" } });
    expect(
      screen.getByRole("option", { name: "line_chart" })
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "files" })).toBeNull();
    fireEvent.change(search, { target: { value: "bar_chart" } });
    expect(screen.queryByRole("option", { name: "line_chart" })).toBeNull();
    fireEvent.click(groupCheckbox());
    await waitFor(() =>
      expect(groupCheckbox()).toHaveAttribute("aria-checked", "true")
    );
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(state.updateTools).toHaveBeenCalledWith([
      state.tools[2],
      state.tools[0],
    ]);
  });

  it("keeps configuration independent and skips capability-disabled, required-parameter and duplicate tools in batches", async () => {
    state.tools.push(
      mcpTool("14", "Blocked tool"),
      {
        ...mcpTool("15", "needs_config"),
        initParams: [{ name: "key", required: true, value: "" } as ToolParam],
      },
      mcpTool("16", "bar_chart")
    );
    showPicker();
    fireEvent.click(await screen.findByRole("button", { name: "charts" }));
    const blocked = screen.getByRole("option", { name: "Blocked tool" });
    expect(blocked).toBeDisabled();
    const line = screen
      .getByRole("option", { name: "line_chart" })
      .closest("[data-resource-view]") as HTMLElement;
    fireEvent.click(
      within(line).getByRole("button", { name: "toolPool.configure" })
    );
    await screen.findByText("Tool configuration modal");
    expect(groupCheckbox()).toHaveAttribute("aria-checked", "false");
    fireEvent.click(groupCheckbox());
    await waitFor(() => expect(state.merge).toHaveBeenCalledTimes(4));
    await waitFor(() => expect(groupCheckbox()).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    const saved = state.updateTools.mock.calls[0][0] as Tool[];
    expect(saved.map((tool) => tool.name)).toEqual(["bar_chart", "line_chart"]);
  });

  it("keeps drafts atomic on batch lookup failure and allows retry", async () => {
    state.merge.mockRejectedValueOnce(new Error("lookup failed"));
    showPicker();
    fireEvent.click(
      await screen.findByRole("checkbox", {
        name: "toolPool.mcpSelectService charts",
      })
    );
    await screen.findByText("toolPool.selectionFailed");
    expect(groupCheckbox()).toHaveAttribute("aria-checked", "false");
    expect(state.updateTools).not.toHaveBeenCalled();
    fireEvent.click(groupCheckbox());
    await waitFor(() =>
      expect(groupCheckbox()).toHaveAttribute("aria-checked", "true")
    );
  });

  it("ignores a pending batch after closing and reopening the picker", async () => {
    let resolve!: (params: ToolParam[]) => void;
    state.merge.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    state.tools = [state.tools[0]];
    const view = showPicker();
    fireEvent.click(
      await screen.findByRole("checkbox", {
        name: "toolPool.mcpSelectService charts",
      })
    );
    expect(screen.getByRole("button", { name: "确认" })).toBeDisabled();
    fireEvent.click(screen.getAllByRole("button", { name: "关闭" })[0]);
    view.rerender(
      <App>
        <ToolDrawer open={false} onClose={vi.fn()} />
      </App>
    );
    view.rerender(
      <App>
        <ToolDrawer open onClose={vi.fn()} />
      </App>
    );
    resolve([]);
    await waitFor(() => expect(groupCheckbox()).not.toBeDisabled());
    expect(groupCheckbox()).toHaveAttribute("aria-checked", "false");
  });

  it("retains permission filtering and shows tools whose service metadata is missing", async () => {
    state.servers = [
      { ...service("charts"), permission: "PRIVATE" } as unknown as McpServer,
    ];
    showPicker();
    await screen.findByRole("button", { name: "files" });
    expect(screen.queryByRole("button", { name: "charts" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "files" }));
    expect(
      screen.getByRole("option", { name: "read_file" })
    ).toBeInTheDocument();
  });

  it("does not add a partial batch when an existing configuration lookup returns no data", async () => {
    state.merge.mockResolvedValueOnce(null);
    showPicker();
    fireEvent.click(
      await screen.findByRole("checkbox", {
        name: "toolPool.mcpSelectService charts",
      })
    );
    await waitFor(() => expect(groupCheckbox()).not.toBeDisabled());
    expect(groupCheckbox()).toHaveAttribute("aria-checked", "false");
    fireEvent.click(groupCheckbox());
    await waitFor(() =>
      expect(groupCheckbox()).toHaveAttribute("aria-checked", "true")
    );
  });

  it("still opens parameter configuration for an individually selected required tool", async () => {
    state.merge.mockResolvedValue([
      { name: "key", required: true, value: "" } as ToolParam,
    ]);
    showPicker();
    fireEvent.click(await screen.findByRole("button", { name: "charts" }));
    fireEvent.click(screen.getByRole("option", { name: "bar_chart" }));
    await screen.findByText("Tool configuration modal");
    expect(groupCheckbox()).toHaveAttribute("aria-checked", "false");
    expect(state.updateTools).not.toHaveBeenCalled();
  });
});
