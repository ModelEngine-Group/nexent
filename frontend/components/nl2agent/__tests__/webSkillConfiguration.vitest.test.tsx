import React from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getNl2AgentSessionState,
  getWebSkillConfiguration,
  installWebSkill,
} from "@/services/nl2agentService";
import { Nl2AgentWorkflowProvider } from "../Nl2AgentWorkflowContext";
import { WebSkillCard } from "../WebSkillCard";

vi.mock("@/services/nl2agentService", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/nl2agentService")>()),
  getNl2AgentSessionState: vi.fn(),
  getWebSkillConfiguration: vi.fn(),
  installWebSkill: vi.fn(),
}));

describe("online Skill configuration", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.mocked(getNl2AgentSessionState).mockReset();
    vi.mocked(getNl2AgentSessionState).mockResolvedValue({
      agent_id: 202,
      models: [],
      tools: [],
      skills: [],
      local_tool_parameter_schemas: {},
      invalid_references: [],
      resource_review: {
        recommendation_batches: {},
        online_recommendation_batches: {},
        mcp_workflows: {},
      },
    } as never);
    vi.mocked(getWebSkillConfiguration).mockReset();
    vi.mocked(getWebSkillConfiguration).mockResolvedValue({
      skill_id: 12,
      skill_name: "writer",
      config_schemas: [
        { name: "api_key", type: "string", required: true, value: null },
        { name: "tone", type: "string", required: false },
      ],
      config_values: { tone: "formal" },
    });
    vi.mocked(installWebSkill).mockReset();
    vi.mocked(installWebSkill).mockResolvedValue({
      skill_id: 112,
      skill_name: "writer",
      installed: true,
      bound: true,
      installed_ids: [],
      installed_names: ["writer"],
    });
  });

  it("collects authoritative configuration before installing and binding", async () => {
    render(
      <Nl2AgentWorkflowProvider
        enabled
        agentId={202}
        scopeKey="conversation:1:draft:202"
        onContinue={vi.fn(async () => undefined)}
      >
        <WebSkillCard
          agentId={202}
          item={{ skill_id: 12, skill_name: "writer", name: "writer" }}
        />
      </Nl2AgentWorkflowProvider>
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Configure & Install" })
    );
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("api_key *"), {
      target: { value: "secret-key" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Install" }));

    await waitFor(() =>
      expect(installWebSkill).toHaveBeenCalledWith(202, {
        skill_id: 12,
        skill_name: "writer",
        config_values: { api_key: "secret-key", tone: "formal" },
      })
    );
    expect(
      await screen.findByRole("button", { name: "Installed" })
    ).toBeDisabled();
  });
});
