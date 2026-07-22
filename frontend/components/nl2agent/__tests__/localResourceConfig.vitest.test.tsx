import React from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  applyLocalResources,
  getNl2AgentSessionState,
  registerLocalResourceRecommendations,
} from "@/services/nl2agentService";
import { LocalResourcesCard } from "../LocalResourcesCard";
import { Nl2AgentWorkflowProvider } from "../Nl2AgentWorkflowContext";

vi.mock("@/services/nl2agentService", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/nl2agentService")>()),
  applyLocalResources: vi.fn(),
  getNl2AgentSessionState: vi.fn(),
  registerLocalResourceRecommendations: vi.fn(),
}));

const renderCard = (
  onRegistered: () => Promise<void> = vi.fn(async () => undefined)
) =>
  render(
    <Nl2AgentWorkflowProvider
      enabled
      scopeKey="conversation:1:draft:202"
      onContinue={vi.fn(async () => undefined)}
    >
      <LocalResourcesCard
        agentId={202}
        recommendationBatchId="local_tools"
        tools={[
          {
            tool_id: 42,
            name: "Configured Tool",
            kind: "tool",
          },
        ]}
        skills={[]}
        onRegistered={onRegistered}
      />
    </Nl2AgentWorkflowProvider>
  );

describe("local Tool configuration", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.mocked(registerLocalResourceRecommendations).mockReset();
    vi.mocked(registerLocalResourceRecommendations).mockResolvedValue({
      recommendation_batch_id: "local_tools",
      status: "recommendations_ready",
      tool_ids: [42],
      skill_ids: [],
      applied_tool_ids: [],
      applied_skill_ids: [],
      tool_parameter_schemas: {},
    });
    vi.mocked(applyLocalResources).mockReset();
    vi.mocked(applyLocalResources).mockResolvedValue({
      bound_tool_count: 1,
      bound_skill_count: 0,
      tool_ids: [42],
      skill_ids: [],
      chat_injection_text: "continue",
    } as never);
    vi.mocked(getNl2AgentSessionState).mockReset();
  });

  it("submits configured instance values for the selected Tool", async () => {
    vi.mocked(registerLocalResourceRecommendations).mockResolvedValueOnce({
      recommendation_batch_id: "local_tools",
      status: "recommendations_ready",
      tool_ids: [42],
      skill_ids: [],
      applied_tool_ids: [],
      applied_skill_ids: [],
      tool_parameter_schemas: {
        "42": [
          {
            name: "top_k",
            type: "integer",
            optional: false,
            description: "Result count",
          },
        ],
      },
    });
    renderCard();

    await waitFor(() =>
      expect(registerLocalResourceRecommendations).toHaveBeenCalledOnce()
    );
    const applyButton = await screen.findByRole("button", {
      name: /Apply All/,
    });
    fireEvent.change(screen.getByRole("spinbutton"), {
      target: { value: "8" },
    });
    fireEvent.click(applyButton);

    await waitFor(() => expect(applyLocalResources).toHaveBeenCalledOnce(), {
      timeout: 3000,
    });
    expect(applyLocalResources).toHaveBeenCalledWith(202, {
      recommendation_batch_id: "local_tools",
      tool_ids: [42],
      skill_ids: [],
      tool_config_values: { "42": { top_k: 8 } },
    });
  });

  it("does not send an incomplete required configuration", async () => {
    vi.mocked(registerLocalResourceRecommendations).mockResolvedValueOnce({
      recommendation_batch_id: "local_tools",
      status: "recommendations_ready",
      tool_ids: [42],
      skill_ids: [],
      applied_tool_ids: [],
      applied_skill_ids: [],
      tool_parameter_schemas: {
        "42": [{ name: "endpoint", type: "string", optional: false }],
      },
    });
    renderCard();
    await waitFor(() =>
      expect(registerLocalResourceRecommendations).toHaveBeenCalledOnce()
    );
    const applyButton = await screen.findByRole("button", {
      name: /Apply All/,
    });
    await waitFor(() => expect(applyButton).not.toBeDisabled());

    fireEvent.click(applyButton);

    expect(applyLocalResources).not.toHaveBeenCalled();
  });

  it("preserves one-click apply for a Tool without configuration", async () => {
    renderCard();
    await waitFor(() =>
      expect(registerLocalResourceRecommendations).toHaveBeenCalledOnce()
    );
    const applyButton = await screen.findByRole("button", {
      name: /Apply All/,
    });
    await waitFor(() => expect(applyButton).not.toBeDisabled());

    fireEvent.click(applyButton);

    await waitFor(() => expect(applyLocalResources).toHaveBeenCalledOnce(), {
      timeout: 3000,
    });
    expect(applyLocalResources).toHaveBeenCalledWith(
      202,
      expect.objectContaining({ tool_config_values: {} })
    );
  });

  it("enables actions only after registration lifecycle completion", async () => {
    let resolveReceipt: (() => void) | undefined;
    const onRegistered = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveReceipt = resolve;
        })
    );
    renderCard(onRegistered);

    await waitFor(() => expect(onRegistered).toHaveBeenCalledOnce());
    expect(screen.getByRole("button", { name: /Applying/ })).toBeDisabled();

    await act(async () => resolveReceipt?.());
    const applyButton = await screen.findByRole("button", {
      name: /Apply All/,
    });
    await waitFor(() => expect(applyButton).not.toBeDisabled());
    fireEvent.click(applyButton);

    await waitFor(() => expect(applyLocalResources).toHaveBeenCalledOnce());
  });

  it.each([
    ["applied", /Applied/],
    ["skipped", /Skipped/],
  ] as const)(
    "restores a %s batch as completed",
    async (status, buttonName) => {
      vi.mocked(registerLocalResourceRecommendations).mockResolvedValueOnce({
        recommendation_batch_id: "local_tools",
        status,
        tool_ids: [42],
        skill_ids: [],
        applied_tool_ids: status === "applied" ? [42] : [],
        applied_skill_ids: [],
        tool_parameter_schemas: {},
      });

      renderCard();

      const button = await screen.findByRole("button", { name: buttonName });
      expect(button).toBeDisabled();
      expect(applyLocalResources).not.toHaveBeenCalled();
    }
  );

  it("restores the applied subset and safely masked Tool configuration", async () => {
    vi.mocked(getNl2AgentSessionState).mockResolvedValue({
      agent_id: 202,
      tools: [
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
      ],
      local_tool_parameter_schemas: {
        local_tools: {
          "42": [
            { name: "endpoint", type: "string", optional: false },
            {
              name: "api_key",
              type: "string",
              optional: false,
              isSecret: true,
            },
          ],
        },
      },
      resource_review: {
        model_selection_confirmed: true,
        recommendations: {
          local_tools: {
            resource_type: "local",
            status: "applied",
            tool_ids: [42],
            skill_ids: [],
            applied_tool_ids: [42],
            applied_skill_ids: [],
          },
        },
        mcp_workflows: {},
      },
      models: [],
      skills: [],
      invalid_references: [],
    } as never);

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
          tools={[
            { tool_id: 42, name: "Configured Tool", kind: "tool" },
            { tool_id: 43, name: "Not Applied", kind: "tool" },
          ]}
          skills={[]}
          registrationEnabled={false}
        />
      </Nl2AgentWorkflowProvider>
    );

    const appliedButton = await screen.findByRole("button", {
      name: /Applied/,
    });
    expect(appliedButton).toBeDisabled();
    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes[0]).toBeChecked();
    expect(checkboxes[1]).not.toBeChecked();
    expect(screen.getByLabelText("endpoint *")).toHaveValue(
      "https://example.test"
    );
    expect(screen.getByLabelText("api_key *")).toHaveValue("••••••••");
    expect(registerLocalResourceRecommendations).not.toHaveBeenCalled();
  });
});
