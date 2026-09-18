import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchWithErrorHandling } = vi.hoisted(() => ({
  fetchWithErrorHandling: vi.fn(),
}));

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return { ...actual, fetchWithErrorHandling };
});

import { ApiError } from "@/services/api";
import { agentShareService } from "@/services/agentShareService";

describe("Agent share management service", () => {
  beforeEach(() => {
    fetchWithErrorHandling.mockReset();
  });

  it("treats a missing active share as an unenabled share instead of an error", async () => {
    fetchWithErrorHandling.mockRejectedValue(
      new ApiError(404, "agent_share_not_found")
    );

    await expect(agentShareService.get(41)).resolves.toBeNull();
  });
});
