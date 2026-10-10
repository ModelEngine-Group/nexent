"use client";

import { useQuery } from "@tanstack/react-query";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { fetchSkillsList } from "@/services/skillService";

export interface ComposerKnowledgeBase {
  id: string;
  name: string;
  description: string;
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
export function useComposerKnowledgeBases(enabled = true) {
  return useQuery<ComposerKnowledgeBase[]>({
    queryKey: ["composerKnowledgeBases"],
    enabled,
    queryFn: async (): Promise<ComposerKnowledgeBase[]> => {
      const result = await knowledgeBaseService.getKnowledgeBasesInfo(
        false,
        false
      );
      return (result.knowledgeBases || []).map((kb) => ({
        id: String(kb.id),
        name: kb.display_name || kb.name,
        description: kb.description || "",
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
