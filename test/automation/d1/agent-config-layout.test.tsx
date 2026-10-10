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
import { searchAgentInfo } from "@/services/agentConfigService";
import AgentConfig from "../../../frontend/app/[locale]/agents/[agentId]/agent-config";

const mocks = vi.hoisted(() => ({
  save: vi.fn(),
  clearSaveError: vi.fn(),
  replaceServerSnapshot: vi.fn(),
  clearConfigFocusRequest: vi.fn(),
  onManualUnlock: vi.fn(),
  onToggleDebug: vi.fn(),
  readOnly: false,
  flow: { configFocusRequest: null as null | Record<string, unknown> },
  state: {
    agentId: 42,
    editedAgent: {
      display_name: "Health Assistant",
      name: "health_assistant",
      description: "An existing draft",
    },
    serverSnapshotRevision: 0,
    saveError: null as string | null,
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: Object.assign(
    (selector: (state: unknown) => unknown) =>
      selector({
        ...mocks.state,
        clearSaveError: mocks.clearSaveError,
        replaceServerSnapshot: mocks.replaceServerSnapshot,
      }),
    { getState: () => mocks.state },
  ),
}));
vi.mock("@/hooks/agent/useSaveGuard", () => ({
  useSaveGuard: () => ({ save: mocks.save }),
}));
vi.mock("@/hooks/agent/useAgentReadOnly", () => ({
  useAgentReadOnly: () => mocks.readOnly,
}));
vi.mock("@/contexts/nl2AgentFlow", () => ({
  useNl2AgentFlow: () => ({
    configFocusRequest: mocks.flow.configFocusRequest,
    clearConfigFocusRequest: mocks.clearConfigFocusRequest,
  }),
}));
vi.mock("@/services/agentConfigService", () => ({ searchAgentInfo: vi.fn() }));
vi.mock("@/lib/agentLabelMapper", () => ({
  getUnavailableReasonLabels: () => [],
}));
vi.mock("@/lib/agentUsageGuide", () => ({
  buildDefaultAgentVersionName: () => "Draft",
}));
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/agent-info",
  async () => {
    const { Form, Input } = await import("antd");
    return {
      default: () => (
        <div data-testid="display-info-content">
          <Form.Item
            name="display_name"
            rules={[{ required: true, message: "display-name-required" }]}
          >
            <Input aria-label="display-name-validation-field" />
          </Form.Item>
        </div>
      ),
    };
  },
);
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/agent-prompt",
  () => ({ default: () => <div data-testid="role-model-content" /> }),
);
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/agent-capability",
  () => ({
    AgentToolCapability: ({
      renderSection,
    }: {
      renderSection: (content: ReactNode, actions: ReactNode) => ReactNode;
    }) => renderSection(<div data-testid="tools-content" />, null),
    AgentSkillCapability: ({
      renderSection,
    }: {
      renderSection: (content: ReactNode, actions: ReactNode) => ReactNode;
    }) => renderSection(<div data-testid="skills-content" />, null),
  }),
);
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/agent-run-policy",
  () => ({
    default: () => <div data-testid="run-strategy-content" />,
    AgentProtocolRepairOption: () => (
      <div data-testid="protocol-repair-content" />
    ),
  }),
);
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/agent-guide",
  () => ({ default: () => <div data-testid="conversation-guide-content" /> }),
);
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/agent-deployment",
  () => ({ default: () => <div data-testid="publish-attributes-content" /> }),
);
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/collaborative-agent",
  () => ({
    default: ({
      renderSection,
    }: {
      renderSection: (content: ReactNode, actions: ReactNode) => ReactNode;
    }) =>
      renderSection(<div data-testid="collaborative-agents-content" />, null),
  }),
);
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/advanced/GuardrailConfigContent",
  () => ({
    default: () => <div data-testid="guardrail-content" />,
    GuardrailConfigActions: () => null,
  }),
);
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/knowledge-base-search",
  () => ({
    default: ({
      renderSection,
    }: {
      renderSection: (content: ReactNode, actions: ReactNode) => ReactNode;
    }) => renderSection(<div data-testid="knowledge-base-content" />, null),
  }),
);
vi.mock(
  "../../../frontend/app/[locale]/agents/versions/AgentVersionPubulishModal",
  () => ({
    default: ({ open }: { open: boolean }) =>
      open ? <div data-testid="publish-modal" /> : null,
  }),
);

const resourceContents = [
  "knowledge-base-content",
  "conversation-guide-content",
  "skills-content",
  "tools-content",
  "collaborative-agents-content",
];
function agentConfigTree() {
  return (
    <App>
      <AgentConfig
        canManualUnlock
        onManualUnlock={mocks.onManualUnlock}
        onToggleDebug={mocks.onToggleDebug}
      />
    </App>
  );
}

describe("AGENT-CONFIG-D1-001 four-card composition and preserved workflow gates", () => {
  beforeEach(() => {
    mocks.readOnly = false;
    mocks.state.editedAgent.display_name = "Health Assistant";
    mocks.flow.configFocusRequest = null;
    mocks.clearConfigFocusRequest.mockReset();
    mocks.onManualUnlock.mockReset();
    mocks.onToggleDebug.mockReset();
    vi.mocked(searchAgentInfo).mockClear();
    mocks.save.mockReset().mockResolvedValue(true);
    vi.mocked(window.HTMLElement.prototype.scrollIntoView).mockClear();
  });

  it("groups the existing field components into four cards and keeps actions outside scrolling", () => {
    render(agentConfigTree());
    const scrollRegion = screen.getByTestId("agent-config-scroll-region");
    const cards = ["info", "model", "resources", "advanced"].map((name) =>
      within(scrollRegion).getByTestId(`agent-config-card-${name}`),
    );
    expect(
      Array.from(
        scrollRegion.querySelectorAll('[data-testid^="agent-config-card-"]'),
      ),
    ).toEqual(cards);
    expect(cards[0]).toContainElement(
      screen.getByTestId("display-info-content"),
    );
    expect(cards[1]).toContainElement(screen.getByTestId("role-model-content"));
    const resourceNodes = Array.from(
      cards[2].querySelectorAll("[data-testid]"),
    ).map((node) => node.getAttribute("data-testid"));
    expect(
      resourceNodes.filter((value) => resourceContents.includes(value ?? "")),
    ).toEqual(resourceContents);
    expect(cards[3]).toContainElement(
      screen.getByTestId("run-strategy-content"),
    );
    expect(cards[3]).toContainElement(
      screen.getByTestId("publish-attributes-content"),
    );
    expect(screen.getByTestId("guardrail-content")).not.toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "agent.highFidelity.moreSettings" }),
    );
    expect(screen.getByRole("dialog")).toContainElement(
      screen.getByTestId("guardrail-content"),
    );
    const header = screen.getByTestId("agent-config-header");
    expect(scrollRegion).not.toContainElement(header);
    expect(header).toContainElement(
      screen.getByRole("button", { name: "agent.highFidelity.debugMode" }),
    );
    expect(header).toContainElement(
      screen.getByRole("button", { name: "agent.config.button.publish" }),
    );
    expect(
      screen.queryByText("agent.config.tab.basic"),
    ).not.toBeInTheDocument();
    expect(searchAgentInfo).not.toHaveBeenCalled();
  });

  it("keeps unlock, debug, and publication connected to successful guarded callbacks", async () => {
    render(agentConfigTree());
    fireEvent.click(
      screen.getByRole("button", {
        name: "agent.page.panel.nl2agent.manualUnlockAction",
      }),
    );
    expect(mocks.onManualUnlock).toHaveBeenCalledOnce();
    fireEvent.click(
      screen.getByRole("button", { name: "agent.highFidelity.debugMode" }),
    );
    await waitFor(() => expect(mocks.onToggleDebug).toHaveBeenCalledOnce());
    fireEvent.click(
      screen.getByRole("button", { name: "agent.config.button.publish" }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("publish-modal")).toBeInTheDocument(),
    );
    expect(mocks.save).toHaveBeenCalledTimes(2);
  });

  it("reopens the requested collapsed resource and preserves prompt focus support without a write", async () => {
    const view = render(agentConfigTree());
    fireEvent.click(
      screen.getByRole("button", { name: /agent\.highFidelity\.toolTitle/ }),
    );
    expect(
      screen
        .getByTestId("tools-content")
        .closest("[data-slot=collapsible-content]"),
    ).toHaveAttribute("data-state", "closed");
    mocks.flow.configFocusRequest = {
      agentId: 42,
      requestId: 1,
      target: { section: "tools_skills", capabilityTab: "tools" },
    };
    view.rerender(agentConfigTree());
    await waitFor(() =>
      expect(
        screen
          .getByTestId("tools-content")
          .closest("[data-slot=collapsible-content]"),
      ).toHaveAttribute("data-state", "open"),
    );
    await waitFor(() =>
      expect(
        window.HTMLElement.prototype.scrollIntoView,
      ).toHaveBeenCalledOnce(),
    );
    expect(mocks.clearConfigFocusRequest).toHaveBeenCalledOnce();
    fireEvent.click(
      screen.getByRole("button", { name: /agent\.highFidelity\.modelTitle/ }),
    );
    mocks.flow.configFocusRequest = {
      agentId: 42,
      requestId: 2,
      target: { section: "role_model", promptTab: "constraint" },
    };
    view.rerender(agentConfigTree());
    await waitFor(() =>
      expect(
        screen
          .getByTestId("role-model-content")
          .closest("[data-slot=collapsible-content]"),
      ).toHaveAttribute("data-state", "open"),
    );
    await waitFor(() =>
      expect(window.HTMLElement.prototype.scrollIntoView).toHaveBeenCalledTimes(
        2,
      ),
    );
    expect(mocks.save).not.toHaveBeenCalled();
    expect(searchAgentInfo).not.toHaveBeenCalled();
  });

  it("prevents downstream debug/publication when saving fails", async () => {
    mocks.save.mockResolvedValue(false);
    render(agentConfigTree());
    fireEvent.click(
      screen.getByRole("button", { name: "agent.highFidelity.debugMode" }),
    );
    await waitFor(() => expect(mocks.save).toHaveBeenCalledOnce());
    fireEvent.click(
      screen.getByRole("button", { name: "agent.config.button.publish" }),
    );
    await waitFor(() => expect(mocks.save).toHaveBeenCalledTimes(2));
    expect(mocks.onToggleDebug).not.toHaveBeenCalled();
    expect(screen.queryByTestId("publish-modal")).not.toBeInTheDocument();
  });

  it("prevents downstream actions on field validation errors and gates read-only edits/publication", async () => {
    mocks.state.editedAgent.display_name = "";
    const view = render(agentConfigTree());
    fireEvent.click(
      screen.getByRole("button", { name: "agent.highFidelity.debugMode" }),
    );
    await waitFor(() =>
      expect(screen.getByText("display-name-required")).toBeInTheDocument(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "agent.config.button.publish" }),
    );
    await waitFor(() =>
      expect(screen.getByText("display-name-required")).toBeInTheDocument(),
    );
    expect(mocks.save).not.toHaveBeenCalled();
    expect(mocks.onToggleDebug).not.toHaveBeenCalled();
    expect(screen.queryByTestId("publish-modal")).not.toBeInTheDocument();
    mocks.readOnly = true;
    view.rerender(agentConfigTree());
    expect(
      screen.getByRole("button", { name: "agent.config.button.publish" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("textbox", { name: "display-name-validation-field" }),
    ).toBeDisabled();
  });
});
