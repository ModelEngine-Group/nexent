// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAgentSkillInstances } from "@/hooks/agent/useAgentSkillInstances";
import { fetchSkillFiles } from "@/services/agentConfigService";
import type { SkillFileContent, SkillFileNode } from "@/types/skill";

const MENTION_EXTENSIONS = new Set(["md", "sh", "py"]);
const MAX_MENTION_FILES = 60;

interface MentionFile {
  path: string;
  content: string;
}

function flattenFiles(
  nodes: readonly SkillFileNode[],
  prefix = ""
): MentionFile[] {
  const files: MentionFile[] = [];
  for (const node of nodes) {
    const path = prefix ? `${prefix}/${node.name}` : node.name;
    if (node.type === "directory") {
      files.push(...flattenFiles(node.children ?? [], path));
      continue;
    }
    const extension = node.name.split(".").at(-1)?.toLowerCase() ?? "";
    if (!MENTION_EXTENSIONS.has(extension)) continue;
    if (node.name.toLowerCase() === "skill.md") continue;
    files.push({ path, content: "" });
  }
  return files;
}

function skillRelativeFiles(
  nodes: readonly SkillFileNode[],
  skillName: string
): MentionFile[] {
  const root = nodes.find(
    (node) => node.type === "directory" && node.name === skillName
  );
  return flattenFiles(root?.children ?? nodes);
}

export function useAgentSkillFiles(agentId: number | null) {
  const { skillInstances } = useAgentSkillInstances(agentId);
  const skillNames = useMemo(
    () =>
      Array.from(
        new Set(
          skillInstances
            .map((skill) => String(skill.name || "").trim())
            .filter(Boolean)
        )
      ).sort(),
    [skillInstances]
  );

  return useQuery<SkillFileContent[]>({
    queryKey: ["agentSkillFiles", agentId, skillNames],
    enabled: Boolean(agentId) && skillNames.length > 0,
    staleTime: 60_000,
    queryFn: async () => {
      const files: SkillFileContent[] = [];
      for (const skillName of skillNames) {
        const tree = await fetchSkillFiles(skillName);
        for (const file of skillRelativeFiles(tree, skillName)) {
          files.push({
            path: `${skillName}/${file.path}`,
            content: file.content,
          });
          if (files.length >= MAX_MENTION_FILES) return files;
        }
      }
      return files;
    },
  });
}
