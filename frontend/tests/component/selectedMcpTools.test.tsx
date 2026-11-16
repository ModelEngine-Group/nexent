// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Tool, ToolParam } from "@/types/agentConfig";
import ToolManagement from "@/app/agents/[agentId]/components/capability/ToolManagement";
import { render } from "./resourceDrawerTestUtils";

const state = vi.hoisted(() => ({
  agentId: 42,
  editedAgent: { tools: [] as Tool[] },
  catalog: [] as Tool[],
  readOnly: false,
  merge: vi.fn<(tool: Tool) => Promise<ToolParam[] | null>>(),
  updateTools: vi.fn(),
}));

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: Object.assign(
    (select: (value: typeof state) => unknown) => select(state),
    { getState: () => state }
  ),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    i18n: { language: "en" },
    t: (
      key: string,
      options?: { name?: string; selected?: number; total?: number }
    ) => {
      if (key === "toolPool.mcpSelectedToolCount" && options) {
        return `${options.selected}/${options.total} tools`;
      }
      return options?.name ? `${key} ${options.name}` : key;
    },
  }),
}));
vi.mock("@/hooks/agent/useToolList", () => ({
  useToolList: () => ({
    availableTools: state.catalog,
    selectableTools: state.catalog.filter(
      (tool) => tool.is_user_selectable !== false
    ),
  }),
}));
vi.mock("@/hooks/agent/useAgentReadOnly", () => ({
  useAgentReadOnly: () => state.readOnly,
}));
vi.mock("@/hooks/mcp/useMcpServerList", () => ({
  useMcpServerList: () => ({ serverList: [] }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { tenantId: "tenant" } }),
}));
vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({
    isImageUnderstandingAvailable: true,
    isVideoUnderstandingAvailable: true,
    isAudioUnderstandingAvailable: true,
    isEmbeddingAvailable: true,
  }),
}));
vi.mock("@/hooks/useKnowledgeBaseSelector", () => ({
  usePrefetchKnowledgeBases: () => ({ prefetchKnowledgeBases: vi.fn() }),
}));
vi.mock(
  "@/app/agents/[agentId]/components/capability/tool/useMergedToolParams",
  () => ({ useMergedToolParams: () => state.merge })
);
vi.mock("@/app/agents/components/capability/tool/ToolConfigModal", () => ({
  default: ({ tool }: { tool: Tool }) => <div>Configure {tool.name}</div>,
}));

const tool = (id: string, name: string, usage?: string): Tool => ({
  id,
  name,
  source: "mcp",
  usage,
  initParams: [],
  description: `Details for ${name}`,
});
const line = tool("1", "line", "vis");
const pie = tool("2", "pie", "vis");
const bars = tool("3", "bars", "vis");
const other = tool("4", "calendar", "calendar");
const local = { ...tool("5", "local"), source: "local" };
const unknown = tool("6", "legacy");

const renderManagement = () =>
  render(
    <App>
      <ToolManagement currentAgentId={42} highFidelity />
    </App>
  );

function openService() {
  fireEvent.click(
    screen.getByRole("button", { name: "toolPool.mcpSelectService vis" })
  );
  return screen.getByRole("dialog", { name: "toolPool.mcpSelectService vis" });
}

describe("selected MCP tools", () => {
  beforeEach(() => {
    state.agentId = 42;
    state.catalog = [line, pie, bars, other, local];
    state.editedAgent.tools = [line, pie, other, local, unknown];
    state.readOnly = false;
    state.merge
      .mockReset()
      .mockImplementation(async (entry) => entry.initParams);
  });

  it("groups selected bindings by service and preserves individual local and legacy rows", () => {
    state.editedAgent.tools[0] = { ...line, usage: undefined };
    renderManagement();
    const grid = within(screen.getByTestId("agent-selected-tool-grid"));
    expect(grid.getAllByText("vis")).toHaveLength(1);
    expect(grid.queryByText("MCP", { exact: true })).not.toBeInTheDocument();
    expect(grid.getByText("2/3 tools")).toBeVisible();
    expect(grid.getByText("1/1 tools")).toBeVisible();
    expect(grid.getByText("local")).toBeVisible();
    expect(grid.getByText("legacy")).toBeVisible();
    expect(grid.queryByText("line")).not.toBeInTheDocument();

    const dialog = within(openService());
    expect(dialog.getByRole("checkbox", { name: "line" })).toBeChecked();
    expect(dialog.getByRole("checkbox", { name: "bars" })).not.toBeChecked();
    expect(dialog.getByText("Details for bars")).toBeVisible();
  });

  it("adds only matching eligible tools in the current service and keeps existing bindings", async () => {
    renderManagement();
    const dialog = within(openService());
    fireEvent.change(dialog.getByRole("textbox"), {
      target: { value: "bars" },
    });
    expect(
      dialog.queryByRole("checkbox", { name: "pie" })
    ).not.toBeInTheDocument();
    fireEvent.click(dialog.getByRole("button", { name: "common.selectAll" }));
    await waitFor(() =>
      expect(state.updateTools).toHaveBeenCalledExactlyOnceWith([
        ...state.editedAgent.tools,
        bars,
      ])
    );
  });

  it("allows removing selected tools even when the catalog is unavailable", () => {
    state.catalog = [];
    renderManagement();
    const dialog = within(openService());
    fireEvent.click(dialog.getByRole("checkbox", { name: "line" }));
    expect(state.updateTools).toHaveBeenCalledExactlyOnceWith([
      pie,
      other,
      local,
      unknown,
    ]);
  });

  it("deselects only checked tools matching the search", () => {
    renderManagement();
    const dialog = within(openService());
    fireEvent.change(dialog.getByRole("textbox"), {
      target: { value: "Details for pie" },
    });
    fireEvent.click(dialog.getByRole("button", { name: "common.deselectAll" }));
    expect(state.updateTools).toHaveBeenCalledExactlyOnceWith([
      line,
      other,
      local,
      unknown,
    ]);
  });

  it("opens configuration when an individually checked tool needs a required parameter", async () => {
    state.merge.mockResolvedValueOnce([
      { name: "api_key", type: "string", required: true, value: undefined },
    ]);
    renderManagement();
    const dialog = within(openService());
    fireEvent.click(dialog.getByRole("checkbox", { name: "bars" }));
    expect(await screen.findByText("Configure bars")).toBeVisible();
    expect(state.updateTools).not.toHaveBeenCalled();
  });

  it("does not commit a delayed selection after switching Agents", async () => {
    let finishLookup: (params: ToolParam[]) => void = () => {};
    state.merge.mockReturnValueOnce(
      new Promise((resolve) => {
        finishLookup = resolve;
      })
    );
    renderManagement();
    const checkbox = within(openService()).getByRole("checkbox", {
      name: "bars",
    });
    fireEvent.click(checkbox);
    expect(checkbox).toBeDisabled();
    state.agentId = 43;
    finishLookup([]);
    await waitFor(() => expect(checkbox).toBeEnabled());
    expect(state.updateTools).not.toHaveBeenCalled();
  });

  it("leaves the draft unchanged after lookup failure and permits retry", async () => {
    state.merge.mockResolvedValueOnce(null);
    renderManagement();
    const checkbox = within(openService()).getByRole("checkbox", {
      name: "bars",
    });
    fireEvent.click(checkbox);
    await waitFor(() => expect(checkbox).toBeEnabled());
    expect(state.updateTools).not.toHaveBeenCalled();
    fireEvent.click(checkbox);
    await waitFor(() => expect(state.updateTools).toHaveBeenCalledTimes(1));
  });

  it("keeps the tool list inspectable in read-only mode", () => {
    state.readOnly = true;
    renderManagement();
    const dialog = within(openService());
    expect(dialog.getByRole("checkbox", { name: "line" })).toBeDisabled();
    expect(dialog.getByRole("checkbox", { name: "bars" })).toBeDisabled();
    expect(
      dialog.queryByRole("button", { name: "common.selectAll" })
    ).not.toBeInTheDocument();
    expect(state.updateTools).not.toHaveBeenCalled();
  });
});
