import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import AgentSetupOrchestrator from "@/app/[locale]/agents/page";

const mocks = vi.hoisted(() => {
  const storeState: { currentAgentId: number | null; isReadOnly: boolean } = {
    currentAgentId: null,
    isReadOnly: false,
  };
  return {
    useAgentVersionDetail: vi.fn(),
    useAgentVersionList: vi.fn(),
    useAgentInfo: vi.fn(),
    storeState,
    agentIdParam: null as string | null,
  };
});

vi.mock("@/hooks/agent/useAgentVersionDetail", () => ({
  useAgentVersionDetail: (...args: unknown[]) =>
    mocks.useAgentVersionDetail(...args),
}));

vi.mock("@/hooks/agent/useAgentVersionList", () => ({
  useAgentVersionList: (...args: unknown[]) => mocks.useAgentVersionList(...args),
}));

vi.mock("@/hooks/agent/useAgentInfo", () => ({
  useAgentInfo: (...args: unknown[]) => mocks.useAgentInfo(...args),
}));

vi.mock("@/stores/agentStore", () => {
  const useAgentStore = (selector: (state: unknown) => unknown) =>
    selector(mocks.storeState);
  (useAgentStore as unknown as { getState: () => unknown }).getState = () =>
    mocks.storeState;
  return { useAgentStore };
});

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({
    get: (key: string) => (key === "agent_id" ? mocks.agentIdParam : null),
    toString: () => "",
  }),
}));

vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
  }),
}));

vi.mock("antd", () => {
  const Box = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return { Button: Box, Spin: Box, Switch: Box, Tag: Box, Tour: Box };
});

vi.mock("lucide-react", () => {
  const Icon = () => <span aria-hidden="true" />;
  return {
    History: Icon,
    Maximize2: Icon,
    Minimize2: Icon,
    Pencil: Icon,
    RefreshCw: Icon,
    Sparkles: Icon,
    X: Icon,
  };
});

vi.mock("@/services/agentConfigService", () => ({
  searchAgentInfo: vi.fn(),
}));

vi.mock("@/lib/logger", () => ({
  default: { warn: vi.fn(), error: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/app/[locale]/agents/agent-selector-header", () => ({
  default: () => <div data-testid="agent-selector-header" />,
}));

vi.mock("@/app/[locale]/agents/agent-config", () => ({
  default: () => <div data-testid="agent-config" />,
}));

vi.mock("@/app/[locale]/agents/agent-version", () => ({
  default: () => <div data-testid="agent-version" />,
}));

vi.mock("@/app/[locale]/agents/agent-debug", () => ({
  default: () => <div data-testid="agent-debug" />,
}));

vi.mock("@/app/[locale]/newchat/assistant-ui/nl2agent-chat-panel", () => ({
  Nl2AgentChatPanel: () => <div data-testid="nl2agent-chat-panel" />,
}));

vi.mock("@/contexts/nl2AgentFlow", () => ({
  Nl2AgentFlowProvider: ({ children }: { children?: ReactNode }) => (
    <>{children}</>
  ),
  useNl2AgentFlow: () => ({
    agentId: null,
    completionSyncFailed: false,
    isComposerDisabled: false,
    isFormLocked: false,
    markCompletionSynced: vi.fn(),
    markCompletionSyncFailed: vi.fn(),
    markGenerationCompleted: vi.fn(),
    markGenerationStopped: vi.fn(),
    markRunFinished: vi.fn(),
    markRunStarted: vi.fn(),
    markPromptGenerationFailed: vi.fn(),
    requestConfigFocus: vi.fn(),
    resetFlow: vi.fn(),
    sessionGeneration: 0,
  }),
}));

function hasHiddenMainContent(container: HTMLElement): boolean {
  return Array.from(container.querySelectorAll("div")).some(
    (el) => el.style.visibility === "hidden"
  );
}

describe("Agent 配置页版本切换守卫 shouldFetchVersionDetail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.agentIdParam = null;
    mocks.storeState.currentAgentId = null;
    mocks.storeState.isReadOnly = false;
  });

  it("UT-FE-AUTO-583566BA85F098F1 切换进行中 isRequestedAgentLoading=true 时跳过旧 Agent 版本详情加载", () => {
    mocks.storeState.currentAgentId = 101;
    mocks.agentIdParam = "202";

    mocks.useAgentVersionList.mockReturnValue({ total: 3 });
    mocks.useAgentInfo.mockReturnValue({
      agentInfo: { id: "101", name: "AgentA", current_version_no: 7 },
      refetch: vi.fn(),
    });
    mocks.useAgentVersionDetail.mockReturnValue({ agentVersionDetail: null });

    const { container } = render(<AgentSetupOrchestrator />);

    expect(mocks.useAgentVersionList).toHaveBeenCalledWith(101);
    expect(mocks.useAgentInfo).toHaveBeenCalledWith(101);
    expect(mocks.useAgentVersionDetail).toHaveBeenCalledWith(101, 7, false);
    expect(hasHiddenMainContent(container)).toBe(true);
  });

  it("切换完成后 isRequestedAgentLoading=false 且 total>0 时按新 Agent 当前版本加载", () => {
    mocks.storeState.currentAgentId = 202;
    mocks.agentIdParam = "202";

    mocks.useAgentVersionList.mockReturnValue({ total: 5 });
    mocks.useAgentInfo.mockReturnValue({
      agentInfo: { id: "202", name: "AgentB", current_version_no: 9 },
      refetch: vi.fn(),
    });
    mocks.useAgentVersionDetail.mockReturnValue({ agentVersionDetail: null });

    const { container } = render(<AgentSetupOrchestrator />);

    expect(mocks.useAgentVersionList).toHaveBeenCalledWith(202);
    expect(mocks.useAgentInfo).toHaveBeenCalledWith(202);
    expect(mocks.useAgentVersionDetail).toHaveBeenCalledWith(202, 9, true);
    expect(hasHiddenMainContent(container)).toBe(false);
  });
});
