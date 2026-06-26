import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  getMineCardMenuActions,
  isCancelableRepositoryStatus,
  isCurrentVersionListed,
  pickReviewDisplayRepositoryInfo,
} from "./agentRepositoryMine";
import type {
  MyAgentRepositoryInfoItem,
  MyEditableAgentItem,
} from "../types/agentRepository";

function makeAgent(
  overrides: Partial<MyEditableAgentItem> = {}
): MyEditableAgentItem {
  return {
    agent_id: 1,
    repository_info: [],
    ...overrides,
  };
}

function makeRepoInfo(
  overrides: Partial<MyAgentRepositoryInfoItem>
): MyAgentRepositoryInfoItem {
  return {
    agent_repository_id: 1,
    status: "pending_review",
    version_no: 1,
    version_label: "v1",
    create_time: "2026-06-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("agentRepositoryMine menu helpers", () => {
  it("returns apply only for published agent without matching repository version", () => {
    const agent = makeAgent({
      current_version_no: 2,
      repository_info: [],
    });

    assert.deepEqual(getMineCardMenuActions(agent), ["apply"]);
    assert.equal(isCurrentVersionListed(agent), false);
  });

  it("returns review only when repository has pending_review without shared", () => {
    const agent = makeAgent({
      current_version_no: 1,
      repository_info: [
        makeRepoInfo({
          agent_repository_id: 10,
          status: "pending_review",
          version_no: 1,
        }),
      ],
    });

    assert.deepEqual(getMineCardMenuActions(agent), ["review"]);
  });

  it("returns reviewUpdate when both pending_review and shared exist", () => {
    const agent = makeAgent({
      current_version_no: 3,
      repository_info: [
        makeRepoInfo({
          agent_repository_id: 11,
          status: "shared",
          version_no: 2,
          create_time: "2026-05-01T00:00:00.000Z",
        }),
        makeRepoInfo({
          agent_repository_id: 12,
          status: "pending_review",
          version_no: 3,
          create_time: "2026-06-20T00:00:00.000Z",
        }),
      ],
    });

    assert.deepEqual(getMineCardMenuActions(agent), ["reviewUpdate"]);
  });

  it("returns apply and reviewUpdate when current version is not listed yet", () => {
    const agent = makeAgent({
      current_version_no: 3,
      repository_info: [
        makeRepoInfo({
          agent_repository_id: 11,
          status: "shared",
          version_no: 2,
        }),
        makeRepoInfo({
          agent_repository_id: 12,
          status: "pending_review",
          version_no: 4,
        }),
      ],
    });

    assert.deepEqual(getMineCardMenuActions(agent), ["apply", "reviewUpdate"]);
  });

  it("pickReviewDisplayRepositoryInfo prefers latest pending_review", () => {
    const items = [
      makeRepoInfo({
        agent_repository_id: 20,
        status: "shared",
        version_no: 1,
        create_time: "2026-06-10T00:00:00.000Z",
      }),
      makeRepoInfo({
        agent_repository_id: 21,
        status: "pending_review",
        version_no: 2,
        create_time: "2026-06-18T00:00:00.000Z",
      }),
      makeRepoInfo({
        agent_repository_id: 22,
        status: "pending_review",
        version_no: 3,
        create_time: "2026-06-20T00:00:00.000Z",
      }),
    ];

    const picked = pickReviewDisplayRepositoryInfo(items);
    assert.equal(picked?.agent_repository_id, 22);
  });

  it("pickReviewDisplayRepositoryInfo falls back to latest shared", () => {
    const items = [
      makeRepoInfo({
        agent_repository_id: 30,
        status: "shared",
        version_no: 1,
        create_time: "2026-05-01T00:00:00.000Z",
      }),
      makeRepoInfo({
        agent_repository_id: 31,
        status: "shared",
        version_no: 2,
        create_time: "2026-06-01T00:00:00.000Z",
      }),
    ];

    const picked = pickReviewDisplayRepositoryInfo(items);
    assert.equal(picked?.agent_repository_id, 31);
  });

  it("returns review when only rejected exists", () => {
    const agent = makeAgent({
      current_version_no: 1,
      repository_info: [
        makeRepoInfo({
          agent_repository_id: 40,
          status: "rejected",
          version_no: 1,
        }),
      ],
    });

    assert.deepEqual(getMineCardMenuActions(agent), ["review"]);
  });

  it("pickReviewDisplayRepositoryInfo falls back to latest rejected", () => {
    const items = [
      makeRepoInfo({
        agent_repository_id: 50,
        status: "rejected",
        version_no: 1,
        create_time: "2026-05-01T00:00:00.000Z",
      }),
      makeRepoInfo({
        agent_repository_id: 51,
        status: "rejected",
        version_no: 2,
        create_time: "2026-06-01T00:00:00.000Z",
      }),
    ];

    const picked = pickReviewDisplayRepositoryInfo(items);
    assert.equal(picked?.agent_repository_id, 51);
  });

  it("returns reviewUpdate and prefers pending when pending shared and rejected coexist", () => {
    const agent = makeAgent({
      current_version_no: 3,
      repository_info: [
        makeRepoInfo({
          agent_repository_id: 60,
          status: "shared",
          version_no: 2,
          create_time: "2026-05-01T00:00:00.000Z",
        }),
        makeRepoInfo({
          agent_repository_id: 61,
          status: "rejected",
          version_no: 1,
          create_time: "2026-04-01T00:00:00.000Z",
        }),
        makeRepoInfo({
          agent_repository_id: 62,
          status: "pending_review",
          version_no: 3,
          create_time: "2026-06-20T00:00:00.000Z",
        }),
      ],
    });

    assert.deepEqual(getMineCardMenuActions(agent), ["reviewUpdate"]);
    const picked = pickReviewDisplayRepositoryInfo(agent.repository_info);
    assert.equal(picked?.agent_repository_id, 62);
  });

  it("returns reviewUpdate and prefers rejected over shared when no pending", () => {
    const agent = makeAgent({
      current_version_no: 2,
      repository_info: [
        makeRepoInfo({
          agent_repository_id: 70,
          status: "rejected",
          version_no: 2,
          version_label: "V2",
          create_time: "2026-06-23T11:27:47.698555Z",
        }),
        makeRepoInfo({
          agent_repository_id: 71,
          status: "shared",
          version_no: 1,
          version_label: "V1",
          create_time: "2026-06-23T11:18:47.034823Z",
        }),
      ],
    });

    assert.deepEqual(getMineCardMenuActions(agent), ["reviewUpdate"]);
    const picked = pickReviewDisplayRepositoryInfo(agent.repository_info);
    assert.equal(picked?.agent_repository_id, 70);
  });

  it("matches user scenario with rejected V2 and shared V1", () => {
    const agent = makeAgent({
      agent_id: 35,
      current_version_no: 2,
      repository_info: [
        makeRepoInfo({
          agent_repository_id: 7,
          status: "rejected",
          version_no: 2,
          version_label: "V2",
          create_time: "2026-06-23T11:27:47.698555Z",
        }),
        makeRepoInfo({
          agent_repository_id: 6,
          status: "shared",
          version_no: 1,
          version_label: "V1",
          create_time: "2026-06-23T11:18:47.034823Z",
        }),
      ],
    });

    assert.deepEqual(getMineCardMenuActions(agent), ["reviewUpdate"]);
    const picked = pickReviewDisplayRepositoryInfo(agent.repository_info);
    assert.equal(picked?.agent_repository_id, 7);
    assert.equal(picked?.status, "rejected");
  });

  it("returns no actions for draft agent with empty repository info", () => {
    const agent = makeAgent({ current_version_no: 0, repository_info: [] });
    assert.deepEqual(getMineCardMenuActions(agent), []);
  });

  it("isCancelableRepositoryStatus allows pending_review and rejected only", () => {
    assert.equal(isCancelableRepositoryStatus("pending_review"), true);
    assert.equal(isCancelableRepositoryStatus("rejected"), true);
    assert.equal(isCancelableRepositoryStatus("shared"), false);
  });
});
