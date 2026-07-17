import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  Nl2AgentRequestError,
  registerRequirementsSummary,
  registerLocalResourceRecommendations,
  registerOnlineResourceRecommendations,
} from "@/services/nl2agentService";
import { Nl2AgentWorkflowProvider } from "../Nl2AgentWorkflowContext";
import { OnlineRecommendationGroup } from "..";
import { LocalResourcesCard } from "../LocalResourcesCard";
import { RequirementsSummaryCard } from "../RequirementsSummaryCard";

vi.mock("@/services/nl2agentService", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/nl2agentService")>()),
  registerLocalResourceRecommendations: vi.fn(),
  registerOnlineResourceRecommendations: vi.fn(),
  registerRequirementsSummary: vi.fn(),
}));

const renderGroup = (onRegistered: () => Promise<void>) =>
  render(
    <Nl2AgentWorkflowProvider
      enabled
      scopeKey="conversation:1:draft:202"
      onContinue={vi.fn(async () => undefined)}
    >
      <OnlineRecommendationGroup
        agentId={202}
        recommendationBatchId="online_mcp"
        resourceType="mcp"
        itemKeys={[]}
        onRegistered={onRegistered}
      >
        <span>Registered content</span>
      </OnlineRecommendationGroup>
    </Nl2AgentWorkflowProvider>
  );

describe("online recommendation registration lifecycle", () => {
  beforeEach(() => {
    vi.mocked(registerOnlineResourceRecommendations).mockReset();
    vi.mocked(registerOnlineResourceRecommendations).mockResolvedValue(
      {} as never
    );
    vi.mocked(registerLocalResourceRecommendations).mockReset();
    vi.mocked(registerLocalResourceRecommendations).mockResolvedValue(
      {} as never
    );
    vi.mocked(registerRequirementsSummary).mockReset();
    vi.mocked(registerRequirementsSummary).mockResolvedValue({
      status: "awaiting_confirmation",
      fingerprint: "a".repeat(64),
      is_current: true,
    } as never);
  });

  it("omits the card agent ID from the requirements registration body", async () => {
    const onRegistered = vi.fn(async () => undefined);
    render(
      <Nl2AgentWorkflowProvider
        enabled
        scopeKey="conversation:1:draft:202"
        onContinue={vi.fn(async () => undefined)}
      >
        <RequirementsSummaryCard
          agentId={202}
          summary={{
            agent_id: 202,
            goal: "Build presentations",
            audience_or_scenario: "Office users",
            primary_input: "DOCX files",
            expected_output: "PPT files",
            key_constraints: "Preserve source facts",
          }}
          onRegistered={onRegistered}
        />
      </Nl2AgentWorkflowProvider>
    );

    await waitFor(() =>
      expect(registerRequirementsSummary).toHaveBeenCalledOnce()
    );
    expect(registerRequirementsSummary).toHaveBeenCalledWith(202, {
      goal: "Build presentations",
      audience_or_scenario: "Office users",
      primary_input: "DOCX files",
      expected_output: "PPT files",
      key_constraints: "Preserve source facts",
    });
    expect(onRegistered).toHaveBeenCalledWith({
      cardType: "requirements_summary",
    });
  });

  it("does not automatically retry a failed requirements registration", async () => {
    vi.mocked(registerRequirementsSummary).mockRejectedValue(
      new Nl2AgentRequestError("invalid requirements payload", 422)
    );
    render(
      <Nl2AgentWorkflowProvider
        enabled
        scopeKey="conversation:1:draft:202"
        onContinue={vi.fn(async () => undefined)}
      >
        <RequirementsSummaryCard
          agentId={202}
          summary={{
            agent_id: 202,
            goal: "Build presentations",
            audience_or_scenario: "Office users",
            primary_input: "DOCX files",
            expected_output: "PPT files",
            key_constraints: "Preserve source facts",
          }}
        />
      </Nl2AgentWorkflowProvider>
    );

    await screen.findByText("invalid requirements payload");
    await waitFor(() =>
      expect(registerRequirementsSummary).toHaveBeenCalledOnce()
    );
  });

  it("retries registration when the rendered receipt fails", async () => {
    const onRegistered = vi
      .fn<() => Promise<void>>()
      .mockRejectedValueOnce(new Error("receipt rejected"))
      .mockResolvedValueOnce(undefined);
    renderGroup(onRegistered);

    await screen.findByText("receipt rejected");
    expect(screen.getByText("Registered content").parentElement).toHaveClass(
      "pointer-events-none"
    );

    fireEvent.click(screen.getByRole("button", { name: "Retry registration" }));

    await waitFor(() => expect(onRegistered).toHaveBeenCalledTimes(2));
    expect(registerOnlineResourceRecommendations).toHaveBeenCalledTimes(2);
    expect(
      screen.getByText("Registered content").parentElement
    ).not.toHaveClass("pointer-events-none");
  });

  it("keeps a local card registration retryable when its receipt fails", async () => {
    const onRegistered = vi
      .fn<() => Promise<void>>()
      .mockRejectedValueOnce(new Error("local receipt rejected"))
      .mockResolvedValueOnce(undefined);
    render(
      <Nl2AgentWorkflowProvider
        enabled
        scopeKey="conversation:1:draft:202"
        onContinue={vi.fn(async () => undefined)}
      >
        <LocalResourcesCard
          agentId={202}
          recommendationBatchId="local_empty"
          tools={[]}
          skills={[]}
          onRegistered={onRegistered}
        />
      </Nl2AgentWorkflowProvider>
    );

    await screen.findByText("local receipt rejected");
    const continueButton = screen.getByRole("button", {
      name: /Continue Without Resources/,
    });
    expect(continueButton).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Retry registration" }));

    await waitFor(() => expect(onRegistered).toHaveBeenCalledTimes(2));
    expect(registerLocalResourceRecommendations).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(continueButton).not.toBeDisabled());
  });

  it("does not retry or block input for a stale online card", async () => {
    vi.mocked(registerOnlineResourceRecommendations).mockRejectedValue(
      new Nl2AgentRequestError("workflow conflict", 409)
    );
    renderGroup(vi.fn(async () => undefined));

    await screen.findByText("workflow conflict");
    expect(
      screen.queryByRole("button", { name: "Retry registration" })
    ).not.toBeInTheDocument();
    await waitFor(() =>
      expect(registerOnlineResourceRecommendations).toHaveBeenCalledOnce()
    );
  });

  it("does not retry a stale local card", async () => {
    vi.mocked(registerLocalResourceRecommendations).mockRejectedValue(
      new Nl2AgentRequestError("local workflow conflict", 409)
    );
    render(
      <Nl2AgentWorkflowProvider
        enabled
        scopeKey="conversation:1:draft:202"
        onContinue={vi.fn(async () => undefined)}
      >
        <LocalResourcesCard
          agentId={202}
          recommendationBatchId="local_stale"
          tools={[]}
          skills={[]}
          onRegistered={vi.fn(async () => undefined)}
        />
      </Nl2AgentWorkflowProvider>
    );

    await screen.findByText("local workflow conflict");
    expect(
      screen.queryByRole("button", { name: "Retry registration" })
    ).not.toBeInTheDocument();
    await waitFor(() =>
      expect(registerLocalResourceRecommendations).toHaveBeenCalledOnce()
    );
  });
});
