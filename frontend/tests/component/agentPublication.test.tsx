// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { AgentPublication } from "../../app/[locale]/agents/[agentId]/components/agent-publication";

const mocks = vi.hoisted(() => ({
  settings: vi.fn(),
  config: vi.fn(),
  published: vi.fn(),
  copy: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("next/navigation", () => ({
  useParams: () => ({ locale: "zh" }),
}));
vi.mock("@/services/a2aService", () => ({
  a2aClientService: { getServerSettings: mocks.settings },
}));
vi.mock("@/services/configService", () => ({
  configService: { fetchRuntimeFrontendConfig: mocks.config },
}));
vi.mock("@/services/agentConfigService", () => ({
  fetchPublishedAgentList: mocks.published,
}));

function PublishedAgentConsumer() {
  const { availableAgents } = usePublishedAgentList();
  return (
    <span data-testid="published-agent-count">{availableAgents.length}</span>
  );
}

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <PublishedAgentConsumer />
        <AgentPublication agentId={42} agentName="draft_name" />
      </App>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mocks.copy.mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: mocks.copy },
  });
  mocks.config.mockResolvedValue({
    northboundBaseUrl: "https://api.example.test",
  });
  mocks.published.mockResolvedValue({
    success: true,
    data: [{ id: "42", name: "published_name" }],
  });
  mocks.settings.mockResolvedValue({
    success: true,
    data: {
      is_enabled: true,
      endpoint_id: "a2a_example",
      supported_interfaces: [
        {
          protocolBinding: "HTTP+JSON",
          url: "/nb/a2a/a2a_example",
          protocolVersion: "1.0",
        },
        {
          protocolBinding: "JSONRPC",
          url: "/nb/a2a/a2a_example/v1",
          protocolVersion: "1.0",
        },
      ],
    },
  });
});

describe("published agent access information", () => {
  it("uses the published name and configured service address for the API example", async () => {
    setup();
    await waitFor(() =>
      expect(screen.getByText(/published_name/)).toBeInTheDocument()
    );
    expect(screen.getByText(/published_name/).textContent).toContain(
      "https://api.example.test/nb/v1/chat/run"
    );
    expect(screen.getByText(/published_name/).textContent).toContain(
      "<YOUR_API_KEY>"
    );
    expect(screen.getByLabelText("a2a.server.agentCardUrl")).toHaveValue(
      "/nb/a2a/a2a_example/.well-known/agent-card.json"
    );
    expect(
      screen.getByText("/nb/a2a/a2a_example/message:stream")
    ).toBeInTheDocument();
    expect(screen.getByText("/nb/a2a/a2a_example/v1")).toBeInTheDocument();
    expect(mocks.settings).toHaveBeenCalledWith(42);
    expect(screen.getByTestId("published-agent-count")).toHaveTextContent("1");
  });

  it("copies the selected agent link and opens preview and API key settings in the current tab", async () => {
    setup();
    fireEvent.click(
      screen.getByRole("button", { name: "agent.publication.share" })
    );
    await waitFor(() =>
      expect(mocks.copy).toHaveBeenCalledWith(
        `${window.location.origin}/zh/newchat?agent_id=42`
      )
    );
    const preview = screen.getByRole("link", {
      name: "agent.publication.preview",
    });
    expect(preview).toHaveAttribute(
      "href",
      `${window.location.origin}/zh/newchat?agent_id=42`
    );
    expect(preview).not.toHaveAttribute("target");
    expect(screen.getByRole("link", { name: /API Key/ })).not.toHaveAttribute(
      "target"
    );
    expect(screen.getByRole("link", { name: /API Key/ })).toHaveAttribute(
      "href",
      "/zh/users"
    );
  });

  it("shows disabled A2A guidance without inventing endpoints", async () => {
    mocks.settings.mockResolvedValue({
      success: true,
      data: { is_enabled: false },
    });
    setup();
    expect(
      await screen.findByText("agentUsageGuide.a2a.notEnabled")
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("a2a.server.agentCardUrl")
    ).not.toBeInTheDocument();
  });

  it("shows a retry action for a server-declared A2A failure", async () => {
    mocks.settings.mockResolvedValue({
      success: false,
      message: "unavailable",
    });
    setup();
    const retry = await screen.findByRole("button", { name: "common.retry" });
    mocks.settings.mockResolvedValue({
      success: true,
      data: { is_enabled: false },
    });
    fireEvent.click(retry);
    expect(
      await screen.findByText("agentUsageGuide.a2a.notEnabled")
    ).toBeInTheDocument();
  });
});
