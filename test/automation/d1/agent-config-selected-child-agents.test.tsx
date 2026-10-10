import { App } from "antd";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CollaborativeAgent from "../../../frontend/app/[locale]/agents/[agentId]/components/collaborative-agent";
import type { Agent } from "../../../frontend/types/agentConfig";
import type { A2AExternalAgent } from "../../../frontend/services/a2aService";

const mocks = vi.hoisted(() => ({
  readOnly: false,
  internalAgents: [] as Agent[],
  externalAgents: [] as A2AExternalAgent[],
  invalidate: vi.fn(),
  updateSubAgentIds: vi.fn(),
  updateSubAgentRelations: vi.fn(),
  updateExternalSubAgentIds: vi.fn(),
  getSubAgents: vi.fn(),
  addRelation: vi.fn(),
  removeRelation: vi.fn(),
  state: {} as {
    agentId: number | null;
    editedAgent: Agent;
    updateSubAgentIds: ReturnType<typeof vi.fn>;
    updateSubAgentRelations: ReturnType<typeof vi.fn>;
    updateExternalSubAgentIds: ReturnType<typeof vi.fn>;
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { name?: string }) => {
      if (key === "agent.collaborative.removeAria") {
        return `Remove ${options?.name}`;
      }
      if (key === "agent.collaborative.selector.versionName") {
        return `Version name: ${options?.name}`;
      }
      return key;
    },
  }),
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
vi.mock("@/hooks/agent/usePublishedAgentList", () => ({
  usePublishedAgentList: () => ({ availableAgents: mocks.internalAgents }),
}));
vi.mock("@/hooks/agent/useExternalAgents", () => ({
  useExternalAgents: () => ({
    availableAgents: mocks.externalAgents,
    invalidate: mocks.invalidate,
  }),
}));
vi.mock("@/services/a2aService", () => ({
  a2aClientService: {
    getSubAgents: mocks.getSubAgents,
    addRelation: mocks.addRelation,
    removeRelation: mocks.removeRelation,
  },
}));
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/advanced/collaborative-agent-selector-modal",
  () => ({
    default: ({ open, onCancel }: { open: boolean; onCancel: () => void }) =>
      open ? (
        <div role="dialog" aria-label="child-agent-selector">
          <button onClick={onCancel}>Cancel selection</button>
        </div>
      ) : null,
  }),
);
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/a2a/A2AAgentDiscoveryModal",
  () => ({
    default: ({ open, onClose }: { open: boolean; onClose: () => void }) =>
      open ? (
        <div role="dialog" aria-label="child-agent-discovery">
          <button onClick={onClose}>Cancel discovery</button>
        </div>
      ) : null,
  }),
);

function internalAgent(
  id: number,
  name: string,
  overrides: Partial<Agent> = {},
): Agent {
  return {
    id: String(id),
    name,
    description: "",
    model: "",
    max_step: 3,
    provide_run_summary: false,
    tools: [],
    ...overrides,
  };
}

function externalAgent(id: number, name: string): A2AExternalAgent {
  return {
    id,
    name,
    agent_url: "https://external-agent.invalid/a2a",
    source_type: "url",
    is_available: true,
  };
}

function setPopulatedDraft() {
  mocks.internalAgents = [
    internalAgent(3, "Research helper", { current_version_no: 4, tags: [] }),
    internalAgent(7, "Health helper full display name", {
      display_name: "Health helper full display name",
      current_version_no: 9,
      version_name: "Latest catalog version",
      icon_url: "/uploaded/icon.png?v=uploaded-revision",
      tags: ["Actual health tag"],
    }),
  ];
  mocks.externalAgents = [externalAgent(90, "External helper")];
  mocks.state.editedAgent = internalAgent(42, "Parent", {
    sub_agent_id_list: [7, 3],
    sub_agent_relations: [
      {
        agent_id: 7,
        version_no: 2,
        version_name: "Saved version name",
      },
      { agent_id: 3, version_no: 4, version_name: "Retained snapshot" },
    ],
    external_sub_agent_id_list: [90],
  });
}

function renderAgents(highFidelity = true) {
  return render(
    <App>
      <CollaborativeAgent
        highFidelity={highFidelity}
        renderSection={(content: ReactNode, actions: ReactNode) => (
          <section>
            {actions}
            {content}
          </section>
        )}
      />
    </App>,
  );
}

function expectNoWrites() {
  expect(mocks.updateSubAgentIds).not.toHaveBeenCalled();
  expect(mocks.updateSubAgentRelations).not.toHaveBeenCalled();
  expect(mocks.updateExternalSubAgentIds).not.toHaveBeenCalled();
  expect(mocks.addRelation).not.toHaveBeenCalled();
  expect(mocks.removeRelation).not.toHaveBeenCalled();
}

describe("AGENT-CONFIG-D1-003 selected child-Agent presentation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.readOnly = false;
    mocks.internalAgents = [];
    mocks.externalAgents = [];
    mocks.getSubAgents.mockResolvedValue({ success: true, data: [] });
    mocks.removeRelation.mockResolvedValue({ success: true });
    mocks.state = {
      agentId: null,
      editedAgent: internalAgent(42, "Parent"),
      updateSubAgentIds: mocks.updateSubAgentIds,
      updateSubAgentRelations: mocks.updateSubAgentRelations,
      updateExternalSubAgentIds: mocks.updateExternalSubAgentIds,
    };
  });

  it("renders one empty add entry and opens/closes selection without writing", () => {
    renderAgents();
    const grid = screen.getByTestId("agent-selected-child-grid");
    const add = screen.getByRole("button", {
      name: "agentConfig.layout.addAgent",
    });
    expect(grid).toHaveClass("grid", "grid-cols-1", "gap-2", "sm:grid-cols-2");
    expect(grid.children).toHaveLength(1);
    expect(add.parentElement).toBe(grid);
    expect(add).toHaveClass("!h-12");
    expectNoWrites();
    fireEvent.click(add);
    expect(
      screen.getByRole("dialog", { name: "child-agent-selector" }),
    ).toBeInTheDocument();
    expectNoWrites();
    fireEvent.click(screen.getByRole("button", { name: "Cancel selection" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expectNoWrites();
  });

  it("orders real compact internal/external rows before add and preserves real metadata", () => {
    setPopulatedDraft();
    renderAgents();
    const grid = screen.getByTestId("agent-selected-child-grid");
    const row = screen.getByTestId("agent-selected-child-internal-7");
    expect(
      Array.from(grid.children).map((element) =>
        element.getAttribute("data-testid"),
      ),
    ).toEqual([
      "agent-selected-child-internal-7",
      "agent-selected-child-internal-3",
      "agent-selected-child-external-90",
      null,
    ]);
    expect(row).toHaveClass(
      "h-12",
      "rounded-[4px]",
      "bg-white",
      "border-[#dfdfdf]",
    );
    expect(
      within(row).getByText("Health helper full display name"),
    ).toHaveClass("text-sm", "font-normal", "leading-[22px]", "text-[#191919]");
    expect(within(row).getByText("Actual health tag")).toHaveClass(
      "bg-[#f3f3f3]",
      "text-xs",
      "text-[#777777]",
    );
    const image = row.querySelector("img");
    expect(image).toHaveAttribute(
      "src",
      "/api/agent/7/icon?v=uploaded-revision",
    );
    expect(image?.parentElement).toHaveStyle({ width: "32px", height: "32px" });
    const remove = within(row).getByRole("button", {
      name: "Remove Health helper full display name",
    });
    expect(remove).toHaveClass("!h-6", "!w-6", "!text-[#777777]");
    expect(remove.querySelector("svg")).toHaveAttribute("width", "14");
    expect(screen.queryByText("保健")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Latest catalog version"),
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByTestId("agent-selected-child-internal-3")).queryByText(
        "Actual health tag",
      ),
    ).not.toBeInTheDocument();
    expect(
      screen
        .getByTestId("agent-selected-child-internal-3")
        .querySelector('[data-slot="selected-resource-name"]')
        ?.nextElementSibling,
    ).toBeNull();
    expect(
      within(
        screen.getByTestId("agent-selected-child-external-90"),
      ).queryByRole("img"),
    ).not.toBeInTheDocument();
    expectNoWrites();
  });

  it("keeps full long names and all actual tags reachable through compact overflow", () => {
    const longName =
      "A full actual child-Agent name with long descriptive text";
    mocks.internalAgents = [
      internalAgent(7, longName, {
        tags: [
          "First actual tag",
          "Second actual tag",
          "Third actual tag",
          "Fourth actual tag",
        ],
      }),
    ];
    mocks.state.editedAgent.sub_agent_id_list = [7];
    renderAgents();
    const row = screen.getByTestId("agent-selected-child-internal-7");
    expect(within(row).getByText(longName)).toHaveClass("truncate");
    expect(
      row.querySelectorAll('[data-slot="selected-resource-tag"]'),
    ).toHaveLength(3);
    expect(within(row).getByText("First actual tag")).toHaveAttribute(
      "title",
      "First actual tag",
    );
    expect(within(row).getByText("Second actual tag")).toHaveAttribute(
      "title",
      "Second actual tag",
    );
    expect(within(row).getByText("+2")).toHaveAttribute(
      "title",
      "Third actual tag, Fourth actual tag",
    );
    expect(within(row).queryByText("Third actual tag")).not.toBeInTheDocument();
    expect(
      within(row).getByRole("button", { name: `Remove ${longName}` }),
    ).toBeEnabled();
    expectNoWrites();
  });

  it("keeps stored external creation order when the catalog is ordered differently and preserves legacy catalog order", () => {
    mocks.externalAgents = [
      externalAgent(81, "External first"),
      externalAgent(82, "External second"),
    ];
    mocks.state.editedAgent.external_sub_agent_id_list = [82, 81];
    const view = renderAgents();
    expect(
      Array.from(screen.getByTestId("agent-selected-child-grid").children).map(
        (element) => element.getAttribute("data-testid"),
      ),
    ).toEqual([
      "agent-selected-child-external-82",
      "agent-selected-child-external-81",
      null,
    ]);
    expectNoWrites();
    view.unmount();
    renderAgents(false);
    const externalGroup = screen.getByText(
      "agent.collaborative.label.external · 2",
    ).parentElement;
    expect(
      Array.from(externalGroup?.children ?? [])
        .slice(1)
        .map((element) => element.textContent),
    ).toEqual(["External first", "External second"]);
    expectNoWrites();
  });

  it("keeps stored external edit order before relation-only agents without changing service state", async () => {
    mocks.state.agentId = 42;
    mocks.externalAgents = [
      externalAgent(81, "External first"),
      externalAgent(82, "External second"),
    ];
    mocks.state.editedAgent.external_sub_agent_id_list = [82, 81];
    mocks.getSubAgents.mockResolvedValue({
      success: true,
      data: [
        ...mocks.externalAgents,
        externalAgent(83, "Relation-only helper"),
      ],
    });
    renderAgents();
    await screen.findByTestId("agent-selected-child-external-83");
    expect(
      Array.from(screen.getByTestId("agent-selected-child-grid").children).map(
        (element) => element.getAttribute("data-testid"),
      ),
    ).toEqual([
      "agent-selected-child-external-82",
      "agent-selected-child-external-81",
      "agent-selected-child-external-83",
      null,
    ]);
    expect(mocks.state.editedAgent.external_sub_agent_id_list).toEqual([
      82, 81,
    ]);
    expectNoWrites();
  });

  it("keeps the full name and saved version snapshot in the actual name tooltip", async () => {
    setPopulatedDraft();
    renderAgents();
    fireEvent.mouseEnter(screen.getByText("Health helper full display name"));
    const tooltip = await screen.findByRole("tooltip");
    expect(
      within(tooltip).getByText("Health helper full display name"),
    ).toBeInTheDocument();
    expect(within(tooltip).getByText("V2")).toBeInTheDocument();
    expect(
      within(tooltip).getByText("Version name: Saved version name"),
    ).toBeInTheDocument();
    expect(within(tooltip).queryByText("V9")).not.toBeInTheDocument();
    expectNoWrites();
  });

  it("removes one internal ID and snapshot while retaining the other selection", () => {
    setPopulatedDraft();
    renderAgents();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Remove Health helper full display name",
      }),
    );
    expect(mocks.updateSubAgentIds).toHaveBeenCalledExactlyOnceWith([3]);
    expect(mocks.updateSubAgentRelations).toHaveBeenCalledExactlyOnceWith([
      { agent_id: 3, version_no: 4, version_name: "Retained snapshot" },
    ]);
    expect(mocks.updateExternalSubAgentIds).not.toHaveBeenCalled();
    expect(mocks.removeRelation).not.toHaveBeenCalled();
  });

  it("removes external creation-mode selections without a persisted relation request", () => {
    setPopulatedDraft();
    renderAgents();
    fireEvent.click(
      screen.getByRole("button", { name: "Remove External helper" }),
    );
    expect(mocks.updateExternalSubAgentIds).toHaveBeenCalledExactlyOnceWith([]);
    expect(mocks.removeRelation).not.toHaveBeenCalled();
    expect(mocks.updateSubAgentIds).not.toHaveBeenCalled();
  });

  it("uses the existing external relation removal and updates only after success", async () => {
    setPopulatedDraft();
    mocks.state.agentId = 42;
    mocks.getSubAgents.mockResolvedValue({
      success: true,
      data: mocks.externalAgents,
    });
    renderAgents();
    await waitFor(() => expect(mocks.getSubAgents).toHaveBeenCalledWith(42));
    expectNoWrites();
    fireEvent.click(
      screen.getByRole("button", { name: "Remove External helper" }),
    );
    await waitFor(() =>
      expect(mocks.updateExternalSubAgentIds).toHaveBeenCalledExactlyOnceWith(
        [],
      ),
    );
    expect(mocks.removeRelation).toHaveBeenCalledExactlyOnceWith(42, 90);
    expect(mocks.getSubAgents).toHaveBeenCalledTimes(2);
    expect(mocks.updateSubAgentIds).not.toHaveBeenCalled();
    expect(mocks.updateSubAgentRelations).not.toHaveBeenCalled();
  });

  it("retains external selection when the relation service rejects removal", async () => {
    setPopulatedDraft();
    mocks.state.agentId = 42;
    mocks.removeRelation.mockResolvedValue({ success: false });
    renderAgents();
    fireEvent.click(
      screen.getByRole("button", { name: "Remove External helper" }),
    );
    await waitFor(() =>
      expect(
        screen.getByText("a2a.service.removeRelationFailed"),
      ).toBeInTheDocument(),
    );
    expect(mocks.removeRelation).toHaveBeenCalledExactlyOnceWith(42, 90);
    expect(mocks.updateExternalSubAgentIds).not.toHaveBeenCalled();
    expect(
      screen.getByTestId("agent-selected-child-external-90"),
    ).toBeInTheDocument();
  });

  it("retains visible disabled actions in read-only rows and prevents all writes", () => {
    setPopulatedDraft();
    mocks.readOnly = true;
    renderAgents();
    const controls = screen.getAllByRole("button");
    expect(controls).toHaveLength(5);
    controls.forEach((control) => {
      expect(control).toBeDisabled();
      fireEvent.click(control);
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expectNoWrites();
  });

  it("preserves saved fallback names and default grouped presentation", () => {
    setPopulatedDraft();
    mocks.state.editedAgent.sub_agent_id_list?.push(15);
    mocks.state.editedAgent.sub_agent_relations?.push({
      agent_id: 15,
      agent_name: "Archived helper name",
      version_no: 6,
      version_name: "Archived snapshot",
    });
    renderAgents(false);
    expect(
      screen.getByText("agent.collaborative.label.internal · 3"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("agent.collaborative.label.external · 1"),
    ).toBeInTheDocument();
    expect(screen.getByText("Archived helper name")).toBeInTheDocument();
    expect(screen.getByText("V6")).toBeInTheDocument();
    expect(screen.getByText("V2")).toBeInTheDocument();
    expect(
      screen.queryByTestId("agent-selected-child-grid"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "agentConfig.layout.addAgent" }),
    ).not.toBeInTheDocument();
    expectNoWrites();
  });
});
