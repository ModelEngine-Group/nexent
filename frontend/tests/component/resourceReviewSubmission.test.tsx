// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  decideResourceReview,
  submitResourceReview,
} from "@/services/resourceReviewService";
import { buildUnifiedRepositoryReviewDeepLink } from "@/lib/notificationNavigation";
import {
  buildResourceRepositoryHref,
  parseResourceRepositoryTarget,
} from "@/lib/resourceRepositoryRoutes";
import type { NotificationItem } from "@/types/notification";

const request = vi.hoisted(() => vi.fn());
vi.mock("@/services/api", () => ({
  fetchWithErrorHandling: request,
  API_ENDPOINTS: {
    resourceReviews: {
      submit: "/api/reviews",
      decision: (id: string) => `/api/reviews/${id}/decision`,
    },
  },
}));
vi.mock("@/lib/auth", () => ({ getAuthHeaders: () => ({}) }));

beforeEach(() => request.mockReset());

describe("independent review applications", () => {
  it("submits source identity and accepts an application without a warehouse record", async () => {
    request.mockResolvedValue({
      ok: true,
      json: async () => ({ review_id: "41", repository_id: null }),
    });
    const payload = {
      resource_type: "skill" as const,
      source_resource_id: "3",
      submit_description: "note",
    };
    expect(await submitResourceReview(payload)).toEqual({
      review_id: "41",
      repository_id: null,
    });
    expect(request.mock.calls[0][0]).toBe("/api/reviews");
    expect(JSON.parse(request.mock.calls[0][1].body)).toEqual(payload);
  });

  it("decides by exact application ID without a revision or warehouse ID", async () => {
    request.mockResolvedValue({
      ok: true,
      json: async () => ({ review_id: "9007199254740993", status: "approved" }),
    });
    const result = await decideResourceReview(
      "9007199254740993",
      "approve",
      "  opinion  "
    );
    expect(result.status).toBe("approved");
    expect(request.mock.calls[0][0]).toBe(
      "/api/reviews/9007199254740993/decision"
    );
    expect(JSON.parse(request.mock.calls[0][1].body)).toEqual({
      decision: "approve",
      reason: "opinion",
    });
  });

  it("uses review_id in external and notification destinations", () => {
    const target = { tab: "review" as const, reviewId: "9007199254740993" };
    expect(buildResourceRepositoryHref("zh", target)).toContain(
      "review_id=9007199254740993"
    );
    expect(
      parseResourceRepositoryTarget(
        new URLSearchParams("tab=review&review_id=41")
      )
    ).toEqual({ valid: true, target: { tab: "review", reviewId: "41" } });
    expect(
      parseResourceRepositoryTarget(
        new URLSearchParams("tab=review&review_id=41&repository_id=1")
      )
    ).toMatchObject({ valid: false });
    const item = {
      resource_type: "resource_review",
      event_type: "repository_review_approved",
      review_id: "9007199254740993",
      details: {},
    } as NotificationItem;
    expect(buildUnifiedRepositoryReviewDeepLink("zh", item)).toContain(
      "review_id=9007199254740993"
    );
  });

  it("does not reinterpret a legacy warehouse ID as an application ID", () => {
    const item = {
      resource_type: "agent_repository",
      event_type: "repository_review_pending",
      repository_id: "41",
      details: {},
    } as NotificationItem;
    expect(buildUnifiedRepositoryReviewDeepLink("zh", item)).not.toContain(
      "review_id="
    );
  });
});
