import { App } from "antd";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ToolManagement from "../../../frontend/app/[locale]/agents/[agentId]/components/capability/ToolManagement";
import type { Tool, ToolParam } from "@/types/agentConfig";

const mocks = vi.hoisted(() => ({
  readOnly: false,
  catalog: [] as Tool[],
  state: { editedAgent: { tools: [] as Tool[] }, updateTools: vi.fn() },
  searchToolConfig: vi.fn(),
  prefetch: vi.fn(),
  modal: vi.fn(),
  config: {
    isImageUnderstandingAvailable: true,
    isVideoUnderstandingAvailable: true,
    isAudioUnderstandingAvailable: true,
    isEmbeddingAvailable: true,
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: Object.assign(
    (selector: (state: typeof mocks.state) => unknown) => selector(mocks.state),
    { getState: () => mocks.state },
  ),
}));
vi.mock("@/hooks/agent/useAgentReadOnly", () => ({
  useAgentReadOnly: () => mocks.readOnly,
}));
vi.mock("@/hooks/agent/useToolList", () => ({
  useToolList: () => ({ availableTools: mocks.catalog }),
}));
vi.mock("@/hooks/useKnowledgeBaseSelector", () => ({
  usePrefetchKnowledgeBases: () => ({ prefetchKnowledgeBases: mocks.prefetch }),
}));
vi.mock("@/hooks/useConfig", () => ({ useConfig: () => mocks.config }));
vi.mock("@/services/agentConfigService", () => ({
  searchToolConfig: mocks.searchToolConfig,
}));
vi.mock(
  "../../../frontend/app/[locale]/agents/components/capability/tool/ToolConfigModal",
  () => ({
    default: (props: {
      tool: Tool;
      initialParams: ToolParam[];
      currentAgentId?: number;
      onCancel: () => void;
    }) => {
      mocks.modal(props);
      return (
        <div role="dialog" aria-label="tool-config">
          <button type="button" onClick={props.onCancel}>
            close-tool-config
          </button>
        </div>
      );
    },
  }),
);

function tool(id: string, name: string, overrides: Partial<Tool> = {}): Tool {
  return {
    id,
    name,
    description: `${name} description`,
    source: "local",
    initParams: [],
    ...overrides,
  };
}

function renderTools(highFidelity = true, hideEmpty = true) {
  return render(
    <App>
      <ToolManagement
        highFidelity={highFidelity}
        hideEmpty={hideEmpty}
        currentAgentId={42}
        addEntry={<button type="button">Add tool</button>}
      />
    </App>,
  );
}

describe("AGENT-CONFIG-D1-003 populated selected tools", () => {
  beforeEach(() => {
    mocks.readOnly = false;
    mocks.config.isImageUnderstandingAvailable = true;
    mocks.config.isVideoUnderstandingAvailable = true;
    mocks.config.isAudioUnderstandingAvailable = true;
    mocks.config.isEmbeddingAvailable = true;
    mocks.state.editedAgent.tools = [
      tool("3", "remote_tool", {
        source: "mcp",
        usage: "Remote server",
        unavailable_reasons: ["mcp_model_unavailable"],
      }),
      tool("9", "knowledge_base_search", {
        initParams: [
          {
            name: "index_names",
            type: "array",
            required: false,
            value: ["kb-a"],
          },
        ],
      }),
      tool("2", "local_tool", {
        labels: ["Outdated label"],
        initParams: [
          { name: "limit", type: "number", required: true, value: 17 },
        ],
      }),
      tool("8", "internal_only"),
      tool("4", "chain_tool", { source: "langchain" }),
    ];
    mocks.catalog = [
      tool("2", "local_tool", {
        labels: ["Current catalog label", "Second label", "Overflow label"],
        inputs: '{"query": "string"}',
        initParams: [
          { name: "limit", type: "number", required: true, value: 99 },
        ],
      }),
      tool("8", "internal_only", { is_user_selectable: false }),
    ];
    mocks.state.updateTools.mockReset();
    mocks.searchToolConfig.mockReset();
    mocks.prefetch.mockReset();
    mocks.modal.mockReset();
  });

  it("keeps selected order, real catalog labels, hidden managed tools and a trailing add entry without writes", () => {
    renderTools();
    const grid = screen.getByTestId("agent-selected-tool-grid");
    expect(grid).toHaveClass("grid", "grid-cols-1", "sm:grid-cols-2", "gap-2");
    expect(
      Array.from(grid.children).map((node) => node.getAttribute("data-testid")),
    ).toEqual([
      "agent-selected-tool-3",
      "agent-selected-tool-2",
      "agent-selected-tool-4",
      null,
    ]);
    expect(grid.lastElementChild).toBe(
      screen.getByRole("button", { name: "Add tool" }),
    );
    expect(screen.queryByText("knowledge_base_search")).not.toBeInTheDocument();
    expect(screen.queryByText("internal_only")).not.toBeInTheDocument();
    expect(screen.getByText("Current catalog label")).toBeVisible();
    expect(screen.queryByText("Outdated label")).not.toBeInTheDocument();
    expect(screen.getByText("+1")).toBeVisible();
    expect(screen.getByText("+1")).toHaveAttribute("title", "Overflow label");
    expect(
      screen.getByLabelText("toolPool.mcpModelUnavailableTooltip"),
    ).toBeVisible();
    const local = screen.getByTestId("agent-selected-tool-2");
    expect(
      screen
        .getByTestId("agent-selected-tool-4")
        .querySelector('[data-slot="selected-resource-tag"]'),
    ).toBeNull();
    expect(
      within(local).getByRole("button", {
        name: "toolPool.configure local_tool",
      }),
    ).toBeVisible();
    expect(
      within(local).getByRole("button", { name: "toolPool.remove local_tool" }),
    ).toBeVisible();
    expect(mocks.state.updateTools).not.toHaveBeenCalled();
    expect(mocks.searchToolConfig).not.toHaveBeenCalled();
  });

  it("opens the existing configuration controller with canonical inputs and persisted parameter values", async () => {
    renderTools();
    fireEvent.click(
      screen.getByRole("button", { name: "toolPool.configure local_tool" }),
    );
    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: "tool-config" })).toBeVisible(),
    );
    const props = mocks.modal.mock.lastCall?.[0];
    expect(props.tool.id).toBe("2");
    expect(props.tool.inputs).toBe('{"query": "string"}');
    expect(props.tool.initParams).toEqual(
      mocks.state.editedAgent.tools[2].initParams,
    );
    expect(props.initialParams).toEqual([
      { name: "limit", type: "number", required: true, value: 17 },
    ]);
    expect(props.currentAgentId).toBe(42);
    expect(mocks.state.updateTools).not.toHaveBeenCalled();
    expect(mocks.searchToolConfig).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "close-tool-config" }));
    expect(
      screen.queryByRole("dialog", { name: "tool-config" }),
    ).not.toBeInTheDocument();
    expect(mocks.state.updateTools).not.toHaveBeenCalled();
  });

  it("keeps availability warnings outside clipped metadata for long tool names and labels", () => {
    const longName = "Long remote tool name ".repeat(20);
    mocks.state.editedAgent.tools[0].name = longName;
    mocks.state.editedAgent.tools[0].labels = [
      "Long catalog label ".repeat(20),
      "Second label",
    ];
    renderTools();
    const row = screen.getByTestId("agent-selected-tool-3");
    const warning = within(row).getByLabelText(
      "toolPool.mcpModelUnavailableTooltip",
    );
    expect(warning).toBeVisible();
    expect(warning.closest(".overflow-hidden")).toBeNull();
    expect(within(row).getByText(longName.trim())).toBeVisible();
    expect(
      within(row).getByRole("button", {
        name: `toolPool.configure ${longName.trim()}`,
      }),
    ).toBeEnabled();
    expect(
      within(row).getByRole("button", {
        name: `toolPool.remove ${longName.trim()}`,
      }),
    ).toBeEnabled();
    expect(mocks.state.updateTools).not.toHaveBeenCalled();
  });

  it("removes only the requested tool while preserving managed selections and all remaining values", () => {
    renderTools();
    const original = mocks.state.editedAgent.tools;
    fireEvent.click(
      screen.getByRole("button", { name: "toolPool.remove local_tool" }),
    );
    expect(mocks.state.updateTools).toHaveBeenCalledExactlyOnceWith(
      original.filter((item) => item.id !== "2"),
    );
    const remaining = mocks.state.updateTools.mock.lastCall?.[0] as Tool[];
    expect(remaining.map((item) => item.id)).toEqual(["3", "9", "8", "4"]);
    expect(remaining[1]).toBe(original[1]);
    expect(remaining[1].initParams[0].value).toEqual(["kb-a"]);
  });

  it("keeps visible inspection metadata while disabling configure/remove in read-only mode", () => {
    mocks.readOnly = true;
    renderTools();
    const configure = screen.getByRole("button", {
      name: "toolPool.configure local_tool",
    });
    const remove = screen.getByRole("button", {
      name: "toolPool.remove local_tool",
    });
    expect(configure).toBeDisabled();
    expect(remove).toBeDisabled();
    expect(screen.getByText("Current catalog label")).toBeVisible();
    fireEvent.click(configure);
    fireEvent.click(remove);
    expect(mocks.modal).not.toHaveBeenCalled();
    expect(mocks.state.updateTools).not.toHaveBeenCalled();
    expect(mocks.searchToolConfig).not.toHaveBeenCalled();
  });

  it("retains a single add entry for an empty or managed-only high-fidelity selection", () => {
    mocks.state.editedAgent.tools = [mocks.state.editedAgent.tools[1]];
    const { rerender } = renderTools();
    expect(
      screen.getByTestId("agent-selected-tool-grid").children,
    ).toHaveLength(1);
    mocks.state.editedAgent.tools = [];
    rerender(
      <App>
        <ToolManagement
          highFidelity
          hideEmpty
          addEntry={<button type="button">Add tool</button>}
        />
      </App>,
    );
    expect(screen.getByRole("button", { name: "Add tool" })).toBeVisible();
    expect(
      screen.getByTestId("agent-selected-tool-grid").children,
    ).toHaveLength(1);
    expect(mocks.state.updateTools).not.toHaveBeenCalled();
  });

  it("preserves the default grouped presentation and empty state", () => {
    const { unmount } = renderTools(false, false);
    expect(screen.getByText("toolPool.selectedToolsLabel")).toBeVisible();
    expect(
      screen.queryByTestId("agent-selected-tool-grid"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add tool" }),
    ).not.toBeInTheDocument();
    unmount();
    mocks.state.editedAgent.tools = [];
    renderTools(false, false);
    expect(screen.getByText("toolPool.noToolsSelected")).toBeVisible();
    expect(mocks.state.updateTools).not.toHaveBeenCalled();
  });
});
