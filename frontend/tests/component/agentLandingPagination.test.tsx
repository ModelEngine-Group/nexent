// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentLandingPage } from "@/app/newchat/assistant-ui/agent-landing";

const state = vi.hoisted(() => ({
  agents: Array.from({ length: 13 }, (_, index) => ({
    id: String(index + 1),
    agent_id: index + 1,
    name: `Agent ${String(index + 1).padStart(2, "0")}`,
    description: "Published agent",
  })),
  search: "",
  isLoading: false,
  updateSearch: vi.fn(),
}));

vi.mock("@/hooks/agent/usePublishedAgentList", () => ({
  usePublishedAgentList: () => ({
    filteredAgents: state.agents,
    search: state.search,
    isLoading: state.isLoading,
    updateSearch: state.updateSearch,
  }),
}));
vi.mock("@/hooks/chat/useConversationAgentHistory", () => ({
  useConversationAgentHistory: () => ({ data: [] }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

const cards = () => screen.queryAllByRole("button", { name: /^Agent \d+/ });

describe("Agent discovery pagination", () => {
  beforeEach(() => {
    state.search = "";
    state.isLoading = false;
    localStorage.clear();
    sessionStorage.clear();
  });

  it("defaults to 12 cards and offers the configuration page sizes", async () => {
    render(<AgentLandingPage onSelectAgent={vi.fn()} />);
    expect(cards()).toHaveLength(12);
    expect(screen.queryByText("Agent 13")).not.toBeInTheDocument();
    expect(screen.getByText("12 / page")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("combobox"));
    await waitFor(() =>
      expect(
        screen.getAllByRole("option").map((item) => item.textContent)
      ).toEqual(["10 / page", "12 / page", "20 / page", "50 / page"])
    );
  });

  it("shows the final partial page and resets when the size changes", async () => {
    const onSelectAgent = vi.fn();
    render(<AgentLandingPage onSelectAgent={onSelectAgent} />);
    fireEvent.click(screen.getByTitle("2"));
    expect(cards()).toHaveLength(1);
    expect(screen.getByText("Agent 13")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("combobox"));
    fireEvent.click(await screen.findByText("10 / page"));
    await waitFor(() => expect(cards()).toHaveLength(10));
    expect(screen.getByText("Agent 01")).toBeInTheDocument();
    expect(screen.queryByText("Agent 11")).not.toBeInTheDocument();
    expect(onSelectAgent).not.toHaveBeenCalled();
  });

  it("returns to page one when the search changes", () => {
    const view = render(<AgentLandingPage onSelectAgent={vi.fn()} />);
    fireEvent.click(screen.getByTitle("2"));
    state.search = "Agent";
    view.rerender(<AgentLandingPage onSelectAgent={vi.fn()} />);
    expect(cards()).toHaveLength(12);
    expect(screen.getByText("Agent 01")).toBeInTheDocument();
  });

  it("preserves empty favorites and resets the page when returning to all", () => {
    render(<AgentLandingPage onSelectAgent={vi.fn()} />);
    fireEvent.click(screen.getByTitle("2"));
    fireEvent.click(
      screen.getByRole("tab", { name: "chat.agentLanding.tabFavorites" })
    );
    expect(cards()).toHaveLength(0);
    expect(
      screen.getByText("chat.agentLanding.emptyFavorites")
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("tab", { name: "chat.agentLanding.tabAll" })
    );
    expect(cards()).toHaveLength(12);
    expect(screen.getByText("Agent 01")).toBeInTheDocument();
  });

  it("preserves the loading state", () => {
    state.isLoading = true;
    render(<AgentLandingPage onSelectAgent={vi.fn()} />);
    expect(cards()).toHaveLength(0);
    expect(screen.getByText("chat.chat.loadingAgents")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});
