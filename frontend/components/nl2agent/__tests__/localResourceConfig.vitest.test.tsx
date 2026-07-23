import React from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  dispatchNl2AgentAction,
  getNl2AgentSessionState,
} from "@/services/nl2agentService";
import { LocalResourcesCard } from "../LocalResourcesCard";
import { Nl2AgentWorkflowProvider } from "../Nl2AgentWorkflowContext";

vi.mock("@/services/nl2agentService", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/nl2agentService")>()),
  dispatchNl2AgentAction: vi.fn(),
  getNl2AgentSessionState: vi.fn(),
}));

const sessionState = (
  schemas: Array<Record<string, unknown>> = [],
  status: "searched" | "applied" | "skipped" = "searched"
) =>
  ({
    agent_id: 202,
    revision: 18,
    models: [],
    tools:
      status === "applied"
        ? [
            {
              tool_id: 42,
              name: "Configured Tool",
              source: "local",
              origin: "local",
              configuration: {
                endpoint: {
                  value: "https://example.test",
                  configured: true,
                  secret: false,
                },
                api_key: { value: null, configured: true, secret: true },
              },
            },
          ]
        : [],
    skills: [],
    local_tool_parameter_schemas: {
      local_tools: { "42": schemas },
    },
    invalid_references: [],
    resource_review: {
      recommendations: {
        local_tools: {
          resource_type: "local",
          status,
          tool_ids: [42],
          skill_ids: [],
          applied_tool_ids: status === "applied" ? [42] : [],
          applied_skill_ids: [],
        },
      },
      mcp_workflows: {},
    },
  }) as never;

const renderCard = () =>
  render(
    <Nl2AgentWorkflowProvider
      enabled
      agentId={202}
      scopeKey="conversation:1:draft:202"
      onContinue={vi.fn(async () => undefined)}
    >
      <LocalResourcesCard
        agentId={202}
        recommendationBatchId="local_tools"
        tools={[{ tool_id: 42, name: "Configured Tool", kind: "tool" }]}
        skills={[]}
      />
    </Nl2AgentWorkflowProvider>
  );

describe("local Tool configuration", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.mocked(getNl2AgentSessionState).mockReset();
    vi.mocked(getNl2AgentSessionState).mockResolvedValue(sessionState());
    vi.mocked(dispatchNl2AgentAction).mockReset();
    vi.mocked(dispatchNl2AgentAction).mockResolvedValue({
      action_id: "action-1",
      action: "apply_local_resources",
      status: "applied",
      workflow_revision: 19,
      result: {},
    });
  });

  it("submits configured instance values through the unified action client", async () => {
    vi.mocked(getNl2AgentSessionState).mockResolvedValueOnce(
      sessionState([
        {
          name: "top_k",
          type: "integer",
          optional: false,
          description: "Result count",
        },
      ])
    );
    renderCard();

    fireEvent.change(await screen.findByRole("spinbutton"), {
      target: { value: "8" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Apply All/ }));

    await waitFor(() => expect(dispatchNl2AgentAction).toHaveBeenCalledOnce());
    expect(dispatchNl2AgentAction).toHaveBeenCalledWith(
      202,
      expect.objectContaining({
        action: "apply_local_resources",
        expected_revision: 18,
        payload: {
          recommendation_batch_id: "local_tools",
          tool_ids: [42],
          skill_ids: [],
          tool_config_values: { "42": { top_k: 8 } },
        },
      })
    );
  });

  it("does not dispatch an incomplete required configuration", async () => {
    vi.mocked(getNl2AgentSessionState).mockResolvedValueOnce(
      sessionState([{ name: "endpoint", type: "string", optional: false }])
    );
    renderCard();
    const applyButton = await screen.findByRole("button", {
      name: /Apply All/,
    });
    await waitFor(() => expect(applyButton).not.toBeDisabled());

    fireEvent.click(applyButton);

    expect(dispatchNl2AgentAction).not.toHaveBeenCalled();
  });

  it("preserves one-click apply for a Tool without configuration", async () => {
    renderCard();
    const applyButton = await screen.findByRole("button", {
      name: /Apply All/,
    });
    await waitFor(() => expect(applyButton).not.toBeDisabled());
    fireEvent.click(applyButton);

    await waitFor(() => expect(dispatchNl2AgentAction).toHaveBeenCalledOnce());
    expect(dispatchNl2AgentAction).toHaveBeenCalledWith(
      202,
      expect.objectContaining({
        payload: expect.objectContaining({ tool_config_values: {} }),
      })
    );
  });

  it("restores an applied subset and safely masked Tool configuration", async () => {
    vi.mocked(getNl2AgentSessionState).mockResolvedValueOnce(
      sessionState(
        [
          { name: "endpoint", type: "string", optional: false },
          {
            name: "api_key",
            type: "string",
            optional: false,
            isSecret: true,
          },
        ],
        "applied"
      )
    );
    renderCard();

    expect(
      await screen.findByRole("button", { name: /Applied/ })
    ).toBeDisabled();
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(screen.getByLabelText("endpoint *")).toHaveValue(
      "https://example.test"
    );
    expect(screen.getByLabelText("api_key *")).toHaveValue("••••••••");
    expect(dispatchNl2AgentAction).not.toHaveBeenCalled();
  });
});
