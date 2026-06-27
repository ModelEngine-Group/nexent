import { describe, expect, it } from "vitest";
import {
  mapAgentVersionDetail,
  mapRepositoryListingDetail,
} from "./agentRepositoryDetail";
import type { AgentVersionDetail } from "@/services/agentVersionService";
import type { AgentRepositoryListingDetail } from "@/types/agentRepository";

describe("mapRepositoryListingDetail", () => {
  it("maps repository listing fields including status", () => {
    const detail: AgentRepositoryListingDetail = {
      agent_repository_id: 1,
      name: "agent_one",
      display_name: "Agent One",
      description: "desc",
      status: "shared",
      version_label: "v1",
      downloads: 5,
      model_name: "gpt",
      duty_prompt: "help users",
      tools: ["search", "calc"],
    };

    const result = mapRepositoryListingDetail(detail);

    expect(result.status).toBe("shared");
    expect(result.display_name).toBe("Agent One");
    expect(result.tools).toEqual(["search", "calc"]);
  });
});

describe("mapAgentVersionDetail", () => {
  it("maps version detail without marketplace status", () => {
    const detail = {
      agent_id: 10,
      name: "draft_agent",
      display_name: "Draft Agent",
      description: "draft desc",
      model_name: "gpt",
      duty_prompt: "assist",
      tools: [
        { origin_name: "web_search" },
        { name: "calculator" },
        { tool_id: 3 },
      ],
      version: {
        version_name: "Draft",
        create_time: "2026-01-01T00:00:00Z",
      },
    } as AgentVersionDetail;

    const result = mapAgentVersionDetail(detail);

    expect(result.status).toBeUndefined();
    expect(result.version_label).toBe("Draft");
    expect(result.created_at).toBe("2026-01-01T00:00:00Z");
    expect(result.tools).toEqual(["web_search", "calculator"]);
  });
});
