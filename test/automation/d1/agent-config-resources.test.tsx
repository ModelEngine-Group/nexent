import { App } from "antd";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentToolCapability } from "../../../frontend/app/[locale]/agents/[agentId]/components/agent-capability";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  invalidate: vi.fn(),
  update: vi.fn(),
  readOnly: false,
  state: { agentId: 42 },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: Object.assign(
    (selector: (state: unknown) => unknown) => selector(mocks.state),
    { getState: () => mocks.state },
  ),
}));
vi.mock("@/hooks/agent/useAgentReadOnly", () => ({
  useAgentReadOnly: () => mocks.readOnly,
}));
vi.mock("@/hooks/agent/useToolList", () => ({
  useToolList: () => ({ invalidate: mocks.invalidate, availableTools: [] }),
}));
vi.mock("@/hooks/agent/useSkillList", () => ({
  useSkillList: () => ({ invalidate: mocks.invalidate }),
}));
vi.mock("@/services/mcpService", () => ({ updateToolList: mocks.update }));
vi.mock("@/services/agentConfigService", () => ({
  searchAgentInfo: mocks.update,
}));
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/capability/ToolManagement",
  () => ({
    default: ({
      hideEmpty,
      highFidelity,
      addEntry,
    }: {
      hideEmpty?: boolean;
      highFidelity?: boolean;
      addEntry?: ReactNode;
    }) =>
      highFidelity ? (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">{addEntry}</div>
      ) : hideEmpty ? null : (
        <div>legacy-tool-empty</div>
      ),
  }),
);
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/capability/SelectedSkillManagement",
  () => ({ default: () => null }),
);
vi.mock(
  "../../../frontend/app/[locale]/agents/components/capability/SkillBuildModal",
  () => ({ default: () => null }),
);
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/capability/McpConfigModal",
  () => ({ default: () => null }),
);
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/capability/tool/SelectToolsDialog",
  () => ({
    default: ({ open }: { open: boolean }) =>
      open ? <div role="dialog" aria-label="associate-tool" /> : null,
  }),
);
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/capability/tool/LabelManagementModal",
  () => ({ default: () => null }),
);
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/capability/skill/SelectSkillsDialog",
  () => ({ default: () => null }),
);
vi.mock(
  "../../../frontend/app/[locale]/agents/[agentId]/components/capability/skill/SkillTagManagementModal",
  () => ({ default: () => null }),
);

function renderTool(highFidelity = true) {
  return render(
    <App>
      <AgentToolCapability
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

describe("AGENT-CONFIG-D1-003 actionable resource entry", () => {
  beforeEach(() => {
    mocks.readOnly = false;
    mocks.push.mockReset();
    mocks.update.mockReset();
  });

  it("uses the actual48px left-column control and opens association separately from creation", () => {
    renderTool();
    const add = screen.getByRole("button", {
      name: "agentConfig.layout.addTool",
    });
    expect(add.parentElement).toHaveClass(
      "grid",
      "grid-cols-1",
      "sm:grid-cols-2",
      "gap-2",
    );
    expect(add.parentElement?.children).toHaveLength(1);
    expect(add).toHaveClass("!h-12");
    expect(add).toHaveClass("!rounded-lg");
    expect(mocks.update).not.toHaveBeenCalled();
    fireEvent.click(add);
    expect(
      screen.getByRole("dialog", { name: "associate-tool" }),
    ).toBeInTheDocument();
    expect(mocks.push).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "agentConfig.layout.newTool" }),
    );
    expect(mocks.push).toHaveBeenCalledExactlyOnceWith("/mcp-space");
    expect(mocks.update).not.toHaveBeenCalled();
  });

  it("disables association and creation for read-only resources", () => {
    mocks.readOnly = true;
    renderTool();
    const add = screen.getByRole("button", {
      name: "agentConfig.layout.addTool",
    });
    const create = screen.getByRole("button", {
      name: "agentConfig.layout.newTool",
    });
    expect(add).toBeDisabled();
    expect(create).toBeDisabled();
    fireEvent.click(add);
    fireEvent.click(create);
    expect(
      screen.queryByRole("dialog", { name: "associate-tool" }),
    ).not.toBeInTheDocument();
    expect(mocks.push).not.toHaveBeenCalled();
    expect(mocks.update).not.toHaveBeenCalled();
  });

  it("keeps the default legacy presentation compatible", () => {
    renderTool(false);
    expect(screen.getByText("legacy-tool-empty")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "toolPool.selectTools" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "agentConfig.layout.addTool" }),
    ).not.toBeInTheDocument();
  });
});
