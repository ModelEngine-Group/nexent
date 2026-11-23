import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const append = vi.hoisted(() => vi.fn());
vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({
    thread: () => ({
      append,
      composer: () => ({
        getState: () => ({
          runConfig: { custom: { onNl2AgentState: "callback" } },
        }),
      }),
    }),
  }),
}));
vi.mock("@/components/interaction/clarification-card", () => ({
  ClarificationCard: ({
    disabled,
    onSubmit,
  }: {
    disabled: boolean;
    onSubmit: (answers: unknown[]) => void;
  }) => (
    <button disabled={disabled} onClick={() => onSubmit([])}>
      Clarify requirements
    </button>
  ),
}));

import { Nl2AgentFlowProvider } from "@/contexts/nl2AgentFlow";
import { RequirementClarificationCard } from "@/app/newchat/ui/requirement-clarification-card";

it("renders an NL2Agent wrapper card inside the Workbench flow provider", async () => {
  render(
    <Nl2AgentFlowProvider>
      <RequirementClarificationCard
        payload={{
          subtype: "requirement_clarification",
          agent_id: 42,
          questions: [],
        }}
      />
    </Nl2AgentFlowProvider>
  );
  expect(
    screen.getByRole("button", { name: "Clarify requirements" })
  ).not.toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Clarify requirements" }));
  expect(append).toHaveBeenCalledWith(
    expect.objectContaining({
      runConfig: {
        custom: {
          onNl2AgentState: "callback",
          runtimeMode: "nl2agent",
          agentId: 42,
        },
      },
      metadata: {
        custom: {
          nl2agentCardAction: expect.objectContaining({ agent_id: 42 }),
        },
      },
    })
  );
});
