import React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getAvailablePlatformLlms,
  getNl2AgentSessionState,
  getWebSkillConfiguration,
} from "@/services/nl2agentService";
import { OnlineRecommendationGroup } from "..";
import { ModelSelectionCard } from "../ModelSelectionCard";
import { Nl2AgentWorkflowProvider } from "../Nl2AgentWorkflowContext";
import { WebMcpCard } from "../WebMcpCard";
import { WebSkillCard } from "../WebSkillCard";

vi.mock("@/services/nl2agentService", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/nl2agentService")>()),
  getAvailablePlatformLlms: vi.fn(),
  getNl2AgentSessionState: vi.fn(),
  getWebSkillConfiguration: vi.fn(),
}));

describe("persisted NL2AGENT card state", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.mocked(getAvailablePlatformLlms).mockReset();
    vi.mocked(getAvailablePlatformLlms).mockResolvedValue([
      { id: 7, displayName: "Primary LLM" },
      { id: 8, displayName: "Fallback LLM" },
    ]);
    vi.mocked(getNl2AgentSessionState).mockReset();
    vi.mocked(getWebSkillConfiguration).mockReset();
    vi.mocked(getWebSkillConfiguration).mockResolvedValue({
      skill_id: 12,
      skill_name: "search-web-tavily",
      config_schemas: [],
      config_values: {},
    });
    vi.mocked(getNl2AgentSessionState).mockResolvedValue({
      agent_id: 202,
      business_logic_model_id: 7,
      model_ids: [7, 8],
      models: [
        {
          model_id: 7,
          display_name: "Primary LLM",
          role: "primary",
          valid: true,
        },
        {
          model_id: 8,
          display_name: "Fallback LLM",
          role: "fallback",
          valid: true,
        },
      ],
      tools: [],
      skills: [
        {
          skill_id: 112,
          name: "search-web-tavily",
          source: "official",
          origin: "online",
        },
      ],
      local_tool_parameter_schemas: {},
      invalid_references: [],
      resource_review: {
        model_selection_confirmed: true,
        recommendations: {
          skill_batch: {
            resource_type: "skill",
            item_keys: ["skill:12"],
            status: "completed",
          },
        },
        mcp_workflows: {
          "registry:github": {
            recommendation_id: "registry:github",
            option_id: "remote",
            status: "tools_bound",
            mcp_id: 55,
            discovered_tool_ids: [91, 92],
            bound_tool_ids: [92],
            discovered_tools: [
              { tool_id: 91, name: "Issues" },
              { tool_id: 92, name: "Pull requests" },
            ],
          },
        },
      },
    } as never);
  });

  it("hydrates model, MCP, and web Skill cards from one authoritative request", async () => {
    render(
      <Nl2AgentWorkflowProvider
        enabled
        agentId={202}
        scopeKey="conversation:1:draft:202"
        onContinue={vi.fn(async () => undefined)}
      >
        <ModelSelectionCard agentId={202} />
        <WebMcpCard
          agentId={202}
          item={{
            recommendation_id: "registry:github",
            name: "GitHub",
            install_options: [
              {
                option_id: "remote",
                type: "remote",
                label: "Remote",
                requires_configuration: false,
                supported: true,
                fields: [],
              },
            ],
          }}
        />
        <OnlineRecommendationGroup
          agentId={202}
          recommendationBatchId="skill_batch"
          resourceType="skill"
          itemKeys={["skill:12"]}
          registrationEnabled={false}
        >
          <WebSkillCard
            agentId={202}
            item={{
              name: "search-web-tavily",
              skill_name: "search-web-tavily",
              skill_id: 12,
            }}
          />
        </OnlineRecommendationGroup>
      </Nl2AgentWorkflowProvider>
    );

    expect(
      await screen.findByRole("button", { name: "Models saved" })
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Tools bound" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Issues" })).not.toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Pull requests" })
    ).toBeChecked();
    const installedButton = screen.getByRole("button", { name: "Installed" });
    expect(installedButton).toBeDisabled();
    expect(installedButton.closest(".pointer-events-none")).toHaveClass(
      "opacity-60"
    );
    await waitFor(() =>
      expect(getNl2AgentSessionState).toHaveBeenCalledTimes(1)
    );
  });
});
