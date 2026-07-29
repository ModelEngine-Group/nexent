"use client";

import React from "react";
import { useTranslation } from "react-i18next";

export interface RecipeNodeData {
  type: "agent" | "skill" | "mcp";
  name: string;
  label: string;
  source?: "official" | "community";
}

export interface RecipeVisualizerData {
  agent: RecipeNodeData;
  skills: RecipeNodeData[];
  mcps: RecipeNodeData[];
}

interface RecipeVisualizerProps {
  data: RecipeVisualizerData;
}

const NODE_STYLES = {
  agent: {
    bg: "bg-[#EEEDFE] dark:bg-purple-900/30",
    border: "border-[#534AB7] dark:border-purple-600",
    iconBg: "bg-[#534AB7]",
  },
  skill: {
    bg: "bg-[#E1F5EE] dark:bg-teal-900/30",
    border: "border-[#1D9E75] dark:border-teal-600",
    iconBg: "bg-[#1D9E75]",
  },
  mcp: {
    bg: "bg-[#FAEEDA] dark:bg-amber-900/30",
    border: "border-[#BA7517] dark:border-amber-600",
    iconBg: "bg-[#BA7517]",
  },
};

const NODE_ICONS: Record<string, string> = {
  agent: "A",
  skill: "S",
  mcp: "M",
};

/**
 * RecipeVisualizer - Visualizes the composition of a recipe
 * Shows Agent + Skills + MCPs as connected nodes
 */
export function RecipeVisualizer({ data }: RecipeVisualizerProps) {
  const { t, i18n } = useTranslation("common");
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";

  const renderNode = (node: RecipeNodeData, key: string) => {
    const styles = NODE_STYLES[node.type];
    return (
      <div
        key={key}
        className={`flex items-center gap-2 px-4 py-2 rounded-lg border ${styles.bg} ${styles.border}`}
      >
        <div
          className={`w-5 h-5 rounded-full ${styles.iconBg} flex items-center justify-center text-[10px] font-medium text-white`}
        >
          {NODE_ICONS[node.type]}
        </div>
        <div>
          <div className="text-xs font-medium text-slate-800 dark:text-slate-100">
            {node.name}
          </div>
          <div className="text-[10px] text-slate-400 dark:text-slate-500">
            {node.label}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4">
      {/* Nodes */}
      <div className="flex flex-wrap justify-center gap-3 sm:gap-6 py-3">
        {/* Agent node */}
        {renderNode(data.agent, "agent-main")}

        {/* Skill nodes */}
        {data.skills.map((skill, i) => renderNode(skill, `skill-${i}`))}

        {/* MCP nodes */}
        {data.mcps.map((mcp, i) => renderNode(mcp, `mcp-${i}`))}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 text-xs text-slate-400 dark:text-slate-500 mt-2 justify-center">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm bg-[#534AB7]" />
          {isZh ? "Agent" : "Agent"}
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm bg-[#1D9E75]" />
          Skill
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm bg-[#BA7517]" />
          MCP
        </span>
      </div>
    </div>
  );
}

export default RecipeVisualizer;
