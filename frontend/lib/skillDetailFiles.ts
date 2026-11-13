// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { SkillFileContent } from "../types/skill";

export interface SkillDetailFileNode {
  key: string;
  title: string;
  isLeaf: boolean;
  children?: SkillDetailFileNode[];
}

/** Preserve folder ancestry when filtering, using full paths as stable keys. */
export function buildSkillDetailTree(files: SkillFileContent[], search = "") {
  const roots: SkillDetailFileNode[] = [];
  const nodes = new Map<string, SkillDetailFileNode>();
  const query = search.trim().toLowerCase();
  for (const file of files) {
    if (query && !file.path.toLowerCase().includes(query)) continue;
    const parts = file.path.split("/").filter(Boolean);
    let children = roots;
    parts.forEach((part, index) => {
      const key = parts.slice(0, index + 1).join("/");
      let node = nodes.get(key);
      if (!node) {
        const isLeaf = index === parts.length - 1;
        node = {
          key,
          title: part,
          isLeaf,
          ...(isLeaf ? {} : { children: [] }),
        };
        nodes.set(key, node);
        children.push(node);
      }
      children = node.children ?? [];
    });
  }
  return roots;
}
