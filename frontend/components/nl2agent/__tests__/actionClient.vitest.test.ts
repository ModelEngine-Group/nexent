import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchWithAuth } from "@/lib/auth";
import { dispatchNl2AgentAction } from "@/services/nl2agentService";

vi.mock("@/lib/auth", () => ({ fetchWithAuth: vi.fn() }));

describe("NL2AGENT unified action client", () => {
  beforeEach(() => {
    vi.mocked(fetchWithAuth).mockReset();
  });

  it("posts every business action through the single dispatcher endpoint", async () => {
    const responseBody = {
      action_id: "2f8567b1-7080-4d7e-9f57-fac9db39cd20",
      action: "save_identity" as const,
      status: "applied" as const,
      workflow_revision: 19,
      result: { display_name: "Research Agent" },
    };
    vi.mocked(fetchWithAuth).mockResolvedValue({
      ok: true,
      json: async () => responseBody,
    } as Response);

    await expect(
      dispatchNl2AgentAction(202, {
        action_id: responseBody.action_id,
        action: "save_identity",
        expected_revision: 18,
        display_text: "Agent name saved: Research Agent",
        payload: { display_name: "Research Agent" },
      })
    ).resolves.toEqual(responseBody);

    expect(fetchWithAuth).toHaveBeenCalledWith(
      "/api/nl2agent/session/202/actions",
      {
        method: "POST",
        body: JSON.stringify({
          action_id: responseBody.action_id,
          action: "save_identity",
          expected_revision: 18,
          display_text: "Agent name saved: Research Agent",
          payload: { display_name: "Research Agent" },
        }),
      }
    );
  });
});
