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
  dispatchNl2AgentAction,
  getNl2AgentSessionState,
  getWebSkillConfiguration,
} from "@/services/nl2agentService";
import { Nl2AgentWorkflowProvider } from "../Nl2AgentWorkflowContext";
import { WebSkillCard } from "../WebSkillCard";

vi.mock("@/services/nl2agentService", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/nl2agentService")>()),
  dispatchNl2AgentAction: vi.fn(),
  getNl2AgentSessionState: vi.fn(),
  getWebSkillConfiguration: vi.fn(),
}));

describe("online Skill configuration", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.mocked(getNl2AgentSessionState).mockReset();
    vi.mocked(getNl2AgentSessionState).mockResolvedValue({
      agent_id: 202,
      revision: 18,
      models: [],
      tools: [],
      skills: [],
      local_tool_parameter_schemas: {},
      invalid_references: [],
      resource_review: {
        recommendations: {},
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
    vi.mocked(dispatchNl2AgentAction).mockReset();
    vi.mocked(dispatchNl2AgentAction).mockResolvedValue({
      action_id: "action-1",
      action: "install_web_skill",
      status: "applied",
      workflow_revision: 19,
      result: {},
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
          recommendationBatchId="skill-batch"
          itemKey="skill:12"
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
      expect(dispatchNl2AgentAction).toHaveBeenCalledWith(
        202,
        expect.objectContaining({
          action: "install_web_skill",
          expected_revision: 18,
          payload: {
            recommendation_batch_id: "skill-batch",
            item_key: "skill:12",
            config_values: { api_key: "secret-key", tone: "formal" },
          },
        })
      )
    );
    expect(
      await screen.findByRole("button", { name: "Installed" })
    ).toBeDisabled();
  });

  it("installs a runtime-only Skill without opening a configuration dialog", async () => {
    vi.mocked(getWebSkillConfiguration).mockResolvedValueOnce({
      skill_id: 13,
      skill_name: "create-docx",
      config_schemas: [],
      config_values: {},
    });

    render(
      <Nl2AgentWorkflowProvider
        enabled
        agentId={202}
        scopeKey="conversation:1:draft:202"
        onContinue={vi.fn(async () => undefined)}
      >
        <WebSkillCard
          agentId={202}
          recommendationBatchId="skill-batch"
          itemKey="skill:13"
          item={{
            skill_id: 13,
            skill_name: "create-docx",
            name: "create-docx",
          }}
        />
      </Nl2AgentWorkflowProvider>
    );

    fireEvent.click(await screen.findByRole("button", { name: "Install" }));

    await waitFor(() =>
      expect(dispatchNl2AgentAction).toHaveBeenCalledWith(
        202,
        expect.objectContaining({
          action: "install_web_skill",
          payload: {
            recommendation_batch_id: "skill-batch",
            item_key: "skill:13",
            config_values: {},
          },
        })
      )
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
