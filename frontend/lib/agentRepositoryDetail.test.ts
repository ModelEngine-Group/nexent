import assert from "node:assert/strict";
import { describe, it } from "node:test";
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

    assert.equal(result.status, "shared");
    assert.equal(result.display_name, "Agent One");
    assert.deepEqual(result.tools, ["search", "calc"]);
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

    assert.equal(result.status, undefined);
    assert.equal(result.version_label, "Draft");
    assert.equal(result.created_at, "2026-01-01T00:00:00Z");
    assert.deepEqual(result.tools, ["web_search", "calculator"]);
  });
});
