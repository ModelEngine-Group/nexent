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
  applyLocalResources,
  registerLocalResourceRecommendations,
} from "@/services/nl2agentService";
import { LocalResourcesCard } from "../LocalResourcesCard";
import { Nl2AgentWorkflowProvider } from "../Nl2AgentWorkflowContext";

vi.mock("@/services/nl2agentService", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/nl2agentService")>()),
  applyLocalResources: vi.fn(),
  registerLocalResourceRecommendations: vi.fn(),
}));

const renderCard = () =>
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
        onRegistered={vi.fn(async () => undefined)}
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
      chat_injection_text: "continue",
    } as never);
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

    await waitFor(() => expect(applyLocalResources).toHaveBeenCalledOnce());
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

    fireEvent.click(applyButton);

    await waitFor(() => expect(applyLocalResources).toHaveBeenCalledOnce());
    expect(applyLocalResources).toHaveBeenCalledWith(
      202,
      expect.objectContaining({ tool_config_values: {} })
    );
  });
});
