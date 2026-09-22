import React from "react";
import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentUsageGuideModal } from "../../app/[locale]/agent-space/components/AgentUsageGuideModal";
import { MyAgentCard } from "../../app/[locale]/agent-space/components/MyAgentCard";
import { a2aClientService } from "@/services/a2aService";
import { configService } from "@/services/configService";
import type { MyEditableAgentItem } from "@/types/agentRepository";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { name?: string }) =>
      options?.name ? `${key}:${options.name}` : key,
  }),
}));
vi.mock("@/services/a2aService", () => ({
  a2aClientService: { getServerSettings: vi.fn() },
}));
vi.mock("@/services/configService", () => ({
  configService: { fetchRuntimeFrontendConfig: vi.fn() },
}));
vi.mock("@/app/[locale]/agents/components/a2a/A2AServerSettingsPanel", () => ({
  default: ({ endpointId }: { endpointId: string }) => (
    <section aria-label="a2a-settings">{endpointId}</section>
  ),
}));

const editableAgent: MyEditableAgentItem = {
  agent_id: 41,
  name: "Demo Agent",
  internal_name: "demo_agent",
  description: "Demo",
  current_version_no: 3,
  version_label: "v3",
  permission: "EDIT",
  repository_info: [],
};
function renderWithProviders(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <App>{node}</App>
    </QueryClientProvider>
  );
}

function renderCard(
  agent: MyEditableAgentItem,
  onUsageGuide = vi.fn(),
  guideMenuProps: Pick<
    React.ComponentProps<typeof MyAgentCard>,
    "guideMenuOpen" | "onGuideMenuOpenChange"
  > = {}
) {
  renderWithProviders(
    <MyAgentCard
      agent={agent}
      onEdit={vi.fn()}
      onView={vi.fn()}
      onApplyListing={vi.fn()}
      onViewReview={vi.fn()}
      onDelete={vi.fn()}
      onEvaluate={vi.fn()}
      onUsageGuide={onUsageGuide}
      {...guideMenuProps}
    />
  );
  return onUsageGuide;
}

async function openTab(user: ReturnType<typeof userEvent.setup>, key: string) {
  await user.click(await screen.findByRole("tab", { name: key }));
}

beforeEach(() => {
  vi.mocked(configService.fetchRuntimeFrontendConfig).mockResolvedValue({});
  vi.mocked(a2aClientService.getServerSettings).mockResolvedValue({
    success: true,
    data: { is_enabled: false },
  } as never);
});

describe("Agent usage guide component coverage", () => {
  it("UT-FE-AGUG-004 opens the selected published Agent guide from the keyboard-accessible card menu", async () => {
    const user = userEvent.setup();
    const onUsageGuide = renderCard(editableAgent);
    screen
      .getByRole("button", { name: "agentRepository.mine.menu.more" })
      .focus();
    await user.keyboard("{Enter}");
    const usageGuideItem = await screen.findByRole("menuitem", {
      name: "agentRepository.mine.menu.usageGuide",
    });
    await user.click(usageGuideItem);
    expect(onUsageGuide).toHaveBeenCalledOnce();
  });

  it("opens a published target card menu without opening the usage guide modal", async () => {
    const onUsageGuide = renderCard(editableAgent, vi.fn(), {
      guideMenuOpen: true,
      onGuideMenuOpenChange: vi.fn(),
    });

    const usageGuideItem = await screen.findByRole("menuitem", {
      name: "agentRepository.mine.menu.usageGuide",
    });
    expect(usageGuideItem.className).toContain("font-semibold");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.setup().click(usageGuideItem);
    expect(onUsageGuide).toHaveBeenCalledOnce();
  });

  it("UT-FE-AGUG-005 hides the usage guide action for a draft", async () => {
    const user = userEvent.setup();
    renderCard({ ...editableAgent, current_version_no: null });
    await user.click(
      screen.getByRole("button", { name: "agentRepository.mine.menu.more" })
    );
    expect(
      screen.queryByText("agentRepository.mine.menu.usageGuide")
    ).not.toBeInTheDocument();
  });

  it("UT-FE-AGUG-006 keeps northbound and A2A visible but performs no share request for read-only users", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AgentUsageGuideModal
        agent={{ ...editableAgent, permission: "READ_ONLY" }}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );
    expect(
      await screen.findByText(/\/en\/newchat\?agent_id=41/)
    ).toBeInTheDocument();
    await openTab(user, "agentUsageGuide.tabs.northbound");
    expect(
      await screen.findByText("agentUsageGuide.northbound.docs")
    ).toBeInTheDocument();
    await openTab(user, "agentUsageGuide.tabs.a2a");
    expect(
      await screen.findByText("agentUsageGuide.a2a.notEnabled")
    ).toBeInTheDocument();
  });

  it("UT-FE-AGUG-007 defaults to the compact share tab and switches tabs without navigation", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AgentUsageGuideModal
        agent={editableAgent}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );
    expect(
      await screen.findByText(/\/en\/newchat\?agent_id=41/)
    ).toBeInTheDocument();
    const shareTab = screen.getByRole("tab", {
      name: "agentUsageGuide.tabs.share",
    });
    expect(shareTab).toHaveAttribute("aria-selected", "true");
    shareTab.focus();
    await user.keyboard("{ArrowRight}");
    await user.keyboard("{Enter}");
    expect(
      screen.getByRole("tab", { name: /agentUsageGuide\.tabs\.northbound/ })
    ).toHaveAttribute("aria-selected", "true");
    await openTab(user, "agentUsageGuide.tabs.a2a");
    expect(window.location.pathname).toBe("/");
  });

  it("UT-FE-AGUG-008 renders the share link without a share-state request", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AgentUsageGuideModal
        agent={editableAgent}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );
    expect(
      await screen.findByText(/\/en\/newchat\?agent_id=41/)
    ).toBeInTheDocument();
    await openTab(user, "agentUsageGuide.tabs.northbound");
    expect(
      screen.getByText("agentUsageGuide.northbound.docs")
    ).toBeInTheDocument();
  });

  it("does not expose the legacy standalone Agent share path from the guide", async () => {
    renderWithProviders(
      <AgentUsageGuideModal
        agent={editableAgent}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );
    expect(
      await screen.findByText(/\/en\/newchat\?agent_id=41/)
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("/share/agent/");
  });

  it("UT-FE-AGUG-009 copies the deterministic Agent deep link", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    renderWithProviders(
      <AgentUsageGuideModal
        agent={editableAgent}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );
    await user.click(
      await screen.findByRole("button", { name: "common.copy" })
    );
    expect(writeText).toHaveBeenCalledWith(
      `${window.location.origin}/en/newchat?agent_id=41`
    );
  });

  it("UT-FE-AGUG-010 reopening reads the same deterministic link", async () => {
    const { rerender } = renderWithProviders(
      <AgentUsageGuideModal
        agent={editableAgent}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );
    expect(
      await screen.findByText(/\/en\/newchat\?agent_id=41/)
    ).toBeInTheDocument();
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <App>
          <AgentUsageGuideModal
            agent={editableAgent}
            locale="en"
            open
            onClose={vi.fn()}
          />
        </App>
      </QueryClientProvider>
    );
    expect(
      await screen.findByText(/\/en\/newchat\?agent_id=41/)
    ).toBeInTheDocument();
    expect(screen.getAllByText(/\/en\/newchat\?agent_id=41/)).toHaveLength(1);
  });

  it("UT-FE-AGUG-013 shows an unavailable state for draft Agents", async () => {
    renderWithProviders(
      <AgentUsageGuideModal
        agent={{ ...editableAgent, current_version_no: null }}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );
    expect(
      await screen.findByText("agentUsageGuide.share.unavailable")
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/\/en\/newchat\?agent_id=41/)
    ).not.toBeInTheDocument();
  });

  it("UT-FE-AGUG-017 renders and copies a safe northbound curl example", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AgentUsageGuideModal
        agent={editableAgent}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );
    await openTab(user, "agentUsageGuide.tabs.northbound");
    const example = await screen.findByText(/\/nb\/v1\/chat\/run/);
    expect(example.textContent).toContain("<YOUR_API_KEY>");
    expect(example.textContent).toContain("demo_agent");
  });

  it("keeps guide tab content stable and lets a backdrop click close the modal", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderWithProviders(
      <AgentUsageGuideModal
        agent={editableAgent}
        locale="en"
        open
        onClose={onClose}
      />
    );

    const content = await screen.findByTestId("agent-usage-guide-content");
    expect(content).toHaveAttribute("data-stable-height", "true");
    expect(content.className).toContain("min-h-[420px]");
    expect(content.className).toContain("overflow-y-auto");

    await user.click(document.querySelector(".ant-modal-wrap")!);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("adds breathing room between the share notice and its controls", async () => {
    renderWithProviders(
      <AgentUsageGuideModal
        agent={editableAgent}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );

    const notice = await screen.findByText("agentUsageGuide.share.notice");
    expect(notice.closest(".ant-alert")?.nextElementSibling).toHaveAttribute(
      "class",
      "pt-2"
    );
  });

  it("renders the northbound curl in a readable code block with an in-panel copy action", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AgentUsageGuideModal
        agent={editableAgent}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );

    await openTab(user, "agentUsageGuide.tabs.northbound");
    const codePanel = await screen.findByTestId("northbound-curl-example");
    expect(
      within(codePanel)
        .getByText(/\/nb\/v1\/chat\/run/)
        .closest("pre")
    ).not.toBeNull();
    expect(codePanel.className).toContain("bg-slate-950");
    expect(codePanel.className).toContain("text-slate-100");
    expect(
      within(codePanel).getByRole("button", { name: "common.copy" }).className
    ).toContain("absolute");
    expect(
      within(codePanel).getByRole("button", { name: "common.copy" })
    ).toHaveAttribute(
      "style",
      "position: absolute; right: 8px; top: 8px; color: rgb(248, 250, 252); background-color: rgb(30, 41, 59); border-color: rgb(71, 85, 105);"
    );
  });

  it("opens API Key management in a new tab without fetching or showing a real key", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AgentUsageGuideModal
        agent={editableAgent}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );

    await openTab(user, "agentUsageGuide.tabs.northbound");
    const apiKeyLink = await screen.findByRole("link", {
      name: "agentUsageGuide.northbound.stepKey",
    });
    expect(apiKeyLink).toHaveAttribute("target", "_blank");
    expect(apiKeyLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(document.body.textContent).not.toContain("sk-real-secret");
  });

  it("UT-FE-AGUG-018 uses the configured public northbound base URL", async () => {
    const user = userEvent.setup();
    vi.mocked(configService.fetchRuntimeFrontendConfig).mockResolvedValue({
      northboundBaseUrl: "https://api.example.com/root/",
    });
    renderWithProviders(
      <AgentUsageGuideModal
        agent={editableAgent}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );
    await openTab(user, "agentUsageGuide.tabs.northbound");
    expect(
      await screen.findByText(
        /https:\/\/api\.example\.com\/root\/nb\/v1\/chat\/run/
      )
    ).toBeInTheDocument();
  });

  it("UT-FE-AGUG-019 uses the current site origin when config is absent", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AgentUsageGuideModal
        agent={editableAgent}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );
    await openTab(user, "agentUsageGuide.tabs.northbound");
    expect(
      await screen.findByText(/http:\/\/localhost:\d+\/nb\/v1\/chat\/run/)
    ).toBeInTheDocument();
  });

  it("adds breathing room between the API key notice and documentation link", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AgentUsageGuideModal
        agent={editableAgent}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );
    await openTab(user, "agentUsageGuide.tabs.northbound");
    const docsLink = await screen.findByRole("link", {
      name: /agentUsageGuide\.northbound\.docs/,
    });
    expect(docsLink.parentElement).toHaveAttribute("class", "pt-2");
  });

  it("UT-FE-AGUG-020 states credential isolation and never renders a real API key", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AgentUsageGuideModal
        agent={editableAgent}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );
    await openTab(user, "agentUsageGuide.tabs.northbound");
    expect(
      await screen.findByText("agentUsageGuide.northbound.keyNotice")
    ).toBeInTheDocument();
    expect(document.body.textContent).toContain("<YOUR_API_KEY>");
    expect(document.body.textContent).not.toContain("sk-real-secret");
  });

  it("UT-FE-AGUG-021 lazily loads enabled A2A settings and exposes the authoritative endpoint", async () => {
    const user = userEvent.setup();
    vi.mocked(a2aClientService.getServerSettings).mockResolvedValue({
      success: true,
      data: {
        is_enabled: true,
        endpoint_id: "agent-card-41",
        supported_interfaces: [],
      },
    } as never);
    renderWithProviders(
      <AgentUsageGuideModal
        agent={editableAgent}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );
    expect(a2aClientService.getServerSettings).not.toHaveBeenCalled();
    await openTab(user, "agentUsageGuide.tabs.a2a");
    expect(
      await screen.findByRole("region", { name: "a2a-settings" })
    ).toHaveTextContent("agent-card-41");
    expect(a2aClientService.getServerSettings).toHaveBeenCalledOnce();
  });

  it("UT-FE-AGUG-022 shows publishing guidance without inventing an A2A address", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AgentUsageGuideModal
        agent={editableAgent}
        locale="en"
        open
        onClose={vi.fn()}
      />
    );
    await openTab(user, "agentUsageGuide.tabs.a2a");
    expect(
      await screen.findByText("agentUsageGuide.a2a.notEnabled")
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "a2a-settings" })
    ).not.toBeInTheDocument();
  });
});
