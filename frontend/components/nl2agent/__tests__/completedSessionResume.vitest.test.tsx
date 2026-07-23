import React from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getNl2AgentSessionState,
  Nl2AgentRequestError,
  resumeNl2AgentSession,
  type Nl2AgentSessionState,
} from "@/services/nl2agentService";
import { FinalizeCard } from "../FinalizeCard";
import { Nl2AgentWorkflowProvider } from "../Nl2AgentWorkflowContext";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useParams: () => ({ locale: "en" }),
}));

vi.mock("@/services/nl2agentService", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/services/nl2agentService")>();
  return {
    ...actual,
    dispatchNl2AgentAction: vi.fn(),
    getNl2AgentSessionState: vi.fn(),
    resumeNl2AgentSession: vi.fn(),
  };
});

const completedState = {
  agent_id: 202,
  session_status: "completed",
  identity_confirmed: true,
  display_name: "Document Assistant",
  internal_name: "document_assistant",
  models: [],
  tools: [],
  skills: [],
  invalid_references: [],
} as unknown as Nl2AgentSessionState;

const renderCard = (onSessionResumed = vi.fn()) =>
  render(
    <Nl2AgentWorkflowProvider
      enabled
      editable={false}
      agentId={202}
      scopeKey="conversation:902:draft:202"
      onContinue={vi.fn(async () => undefined)}
      onSessionResumed={onSessionResumed}
    >
      <FinalizeCard
        data={{
          agent_id: 202,
          business_description: "Build presentations",
          duty_prompt: "Create accurate slides.",
          greeting_message: "Hello",
        }}
      />
    </Nl2AgentWorkflowProvider>
  );

describe("completed NL2AGENT final review", () => {
  beforeEach(() => {
    vi.mocked(getNl2AgentSessionState).mockReset();
    vi.mocked(resumeNl2AgentSession).mockReset();
    push.mockReset();
  });

  it("loads read-only state and explicitly resumes editing", async () => {
    vi.mocked(getNl2AgentSessionState)
      .mockResolvedValueOnce(completedState)
      .mockResolvedValueOnce(completedState)
      .mockResolvedValue({
        ...completedState,
        session_status: "active",
        current_stage: "revision_routing",
      });
    const activeSession = {
      nl2agent_agent_id: 101,
      draft_agent_id: 202,
      conversation_id: 902,
      status: "active" as const,
    };
    vi.mocked(resumeNl2AgentSession).mockResolvedValue(activeSession);
    const onSessionResumed = vi.fn();
    renderCard(onSessionResumed);

    const resumeButton = await screen.findByRole("button", {
      name: "Continue Editing",
    });
    fireEvent.click(resumeButton);

    await waitFor(() =>
      expect(resumeNl2AgentSession).toHaveBeenCalledWith(202)
    );
    expect(onSessionResumed).toHaveBeenCalledWith(activeSession);
    await screen.findByText("Editing is in progress");
    expect(
      screen.queryByRole("button", { name: "Review & Publish" })
    ).not.toBeInTheDocument();
  });

  it("falls back to the persisted proposal after session retention expires", async () => {
    vi.mocked(getNl2AgentSessionState).mockRejectedValue(
      new Nl2AgentRequestError("not found", 404, "030201")
    );
    const { container } = renderCard();

    await within(container).findByText(
      "The editable NL2AGENT session has expired"
    );
    expect(
      within(container).getByText("Build presentations")
    ).toBeInTheDocument();
    expect(
      within(container).queryByRole("button", { name: "Continue Editing" })
    ).not.toBeInTheDocument();
  });

  it("allows an active final review to enter another editing round", async () => {
    const activeState = {
      ...completedState,
      session_status: "active" as const,
      current_stage: "final_review" as const,
    };
    vi.mocked(getNl2AgentSessionState).mockResolvedValue(activeState);
    vi.mocked(resumeNl2AgentSession).mockResolvedValue({
      nl2agent_agent_id: 101,
      draft_agent_id: 202,
      conversation_id: 902,
      status: "active",
    });
    render(
      <Nl2AgentWorkflowProvider
        enabled
        editable
        agentId={202}
        scopeKey="conversation:902:draft:202"
        onContinue={vi.fn(async () => undefined)}
      >
        <FinalizeCard
          data={{
            agent_id: 202,
            business_description: "Build presentations",
            duty_prompt: "Create accurate slides.",
            greeting_message: "Hello",
          }}
        />
      </Nl2AgentWorkflowProvider>
    );

    expect(
      await screen.findByRole("button", { name: "Continue Editing" })
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Apply to configuration" })
    ).toBeEnabled();
  });
});
