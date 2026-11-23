"use client";

import { useQuery } from "@tanstack/react-query";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { fetchSkillsList } from "@/services/skillService";

export interface ComposerKnowledgeBase {
  id: string;
  name: string;
  description: string;
  embeddingModel?: string;
}

export interface ComposerSkill {
  id: string;
  name: string;
  description: string;
  tags: string[];
}

/**
 * Real knowledge bases for the composer quick panel, newest first.
 */
export function useComposerKnowledgeBases(enabled = true, aidp = false) {
  return useQuery<ComposerKnowledgeBase[]>({
    queryKey: ["composerKnowledgeBases", aidp ? "aidp" : "local"],
    enabled,
    queryFn: async (): Promise<ComposerKnowledgeBase[]> => {
      const bases = aidp
        ? knowledgeBaseService.mapAidpKnowledgeBasesToKnowledgeBases(
            (await knowledgeBaseService.getAidpKnowledgeBasesAll()).value || []
          )
        : (
            await knowledgeBaseService.getKnowledgeBasesInfo(
              false,
              false,
              null,
              null,
              undefined,
              { strict: true }
            )
          ).knowledgeBases || [];
      return bases
        .filter((kb) => aidp || kb.knowledge_id != null)
        .map((kb) => ({
          id: String(aidp ? kb.id : kb.knowledge_id),
          name: kb.display_name || kb.name,
          description: kb.description || "",
          embeddingModel: String(
            kb.embeddingModelId ?? kb.embeddingModel ?? ""
          ),
        }));
    },
    staleTime: 30_000,
  });
}

/**
 * Real skills for the composer quick panel.
 */
export function useComposerSkills(enabled = true) {
  return useQuery<ComposerSkill[]>({
    queryKey: ["composerSkills"],
    enabled,
    queryFn: async (): Promise<ComposerSkill[]> => {
      const skills = await fetchSkillsList();
      return skills.map((skill) => ({
        id: String(skill.skill_id),
        name: skill.name,
        description: skill.description || "",
        tags: skill.tags || [],
      }));
    },
    staleTime: 30_000,
  });
}
