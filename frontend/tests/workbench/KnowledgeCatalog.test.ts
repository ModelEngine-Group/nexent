import { afterEach, expect, it, vi } from "vitest";
import knowledgeBaseService from "@/services/knowledgeBaseService";

vi.mock("@/lib/auth", () => ({
  getAuthHeaders: () => ({ Authorization: "Bearer fixture" }),
  fetchWithAuth: (...args: Parameters<typeof fetch>) =>
    globalThis.fetch(...args),
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() },
}));
afterEach(() => vi.unstubAllGlobals());

it("a failed health probe cannot become a successful empty Workbench catalog", async () => {
  vi.spyOn(knowledgeBaseService, "checkHealth").mockResolvedValue(false);
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  await expect(
    knowledgeBaseService.getKnowledgeBasesInfo(
      false,
      false,
      null,
      null,
      undefined,
      { strict: true }
    )
  ).rejects.toThrow("unavailable");
  expect(fetch).not.toHaveBeenCalled();
});
it("an unauthorized catalog response cannot clear Workbench selections", async () => {
  vi.spyOn(knowledgeBaseService, "checkHealth").mockResolvedValue(true);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response("{}", { status: 403 }))
  );
  await expect(
    knowledgeBaseService.getKnowledgeBasesInfo(
      false,
      false,
      null,
      null,
      undefined,
      { strict: true }
    )
  ).rejects.toThrow("unavailable");
});
it("UT-FE-WB-037 retains batched display tags without per-card assignment requests", async () => {
  vi.spyOn(knowledgeBaseService, "checkHealth").mockResolvedValue(true);
  const fetch = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        indices: ["index-a"],
        indices_info: [
          {
            name: "index-a",
            knowledge_id: 1,
            tags: ["Finance", "Search"],
            stats: {},
          },
        ],
      })
    )
  );
  vi.stubGlobal("fetch", fetch);
  const result = await knowledgeBaseService.getKnowledgeBasesInfo(
    false,
    false,
    null,
    null,
    undefined,
    { strict: true }
  );
  expect(result.knowledgeBases[0].tags).toEqual(["Finance", "Search"]);
  expect(fetch).toHaveBeenCalledTimes(1);
});
