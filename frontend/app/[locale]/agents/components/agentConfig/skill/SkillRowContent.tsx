"use client";

import { Checkbox } from "antd";

import type { Skill } from "@/types/agentConfig";

interface SkillRowContentProps {
  readonly skill: Skill;
  readonly selected: boolean;
  readonly isReadOnly: boolean;
}

export default function SkillRowContent({
  skill,
  selected,
  isReadOnly,
}: SkillRowContentProps) {
  return (
    <>
      <Checkbox checked={selected} disabled={isReadOnly} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-mono text-xs font-medium text-gray-800">
            {skill.name}
          </span>
          {(skill.tags || []).slice(0, 2).map((tag) => (
            <span
              key={tag}
              className="shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-600"
            >
              {tag}
            </span>
          ))}
        </div>
        {skill.description ? (
          <p className="truncate text-xs text-gray-400">{skill.description}</p>
        ) : null}
      </div>
    </>
  );
}
