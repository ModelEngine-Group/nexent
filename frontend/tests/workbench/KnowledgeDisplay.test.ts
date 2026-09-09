import { expect, it, vi } from "vitest";
import { restoreKnowledgeDisplay } from "@/features/workbench/knowledgeDisplay";
import knowledgeBaseService from "@/services/knowledgeBaseService";
vi.mock("@/services/knowledgeBaseService", () => ({
  default: {
    getKnowledgeBasesInfo: vi.fn(),
    getAidpKnowledgeBasesAll: vi.fn(),
    mapAidpKnowledgeBasesToKnowledgeBases: () => [],
  },
}));
it("restores names by business ID rather than list position after conversation creation", async () => {
  vi.mocked(knowledgeBaseService.getKnowledgeBasesInfo).mockResolvedValue({
    knowledgeBases: [
      { knowledge_id: 2, name: "Second" },
      { knowledge_id: 1, name: "First" },
    ],
  } as never);
  const result = await restoreKnowledgeDisplay({
    schema_version: 1,
    local: { mode: "override", knowledge_ids: ["1", "2", "3"] },
    aidp: { mode: "disabled", kds_ids: [] },
  });
  expect(result?.local.display_names).toEqual(["First", "Second", "#3"]);
  expect(knowledgeBaseService.getAidpKnowledgeBasesAll).not.toHaveBeenCalled();
});
