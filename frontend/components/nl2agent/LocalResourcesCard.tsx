"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Checkbox, Button, message as AntMessage } from "antd";
import { CheckCircle2, Loader2 } from "lucide-react";
import { applyLocalResources } from "@/services/nl2agentService";

export interface LocalResourceItem {
  tool_id?: number;
  skill_id?: number;
  name: string;
  description?: string;
  source?: string;
  score?: number;
  reason?: string;
  kind: "tool" | "skill";
}

export interface LocalResourcesCardProps {
  /** The draft agent_id being built by the NL2AGENT session. */
  agentId: number;
  tools: LocalResourceItem[];
  skills: LocalResourceItem[];
}

/**
 * Renders recommended local tools and skills with per-item checkboxes and a
 * single "Apply All" button that bulk-binds the selected resources to the
 * draft agent.
 *
 * Rendered from a ```nl2agent-local-resources fenced JSON block in the
 * NL2AGENT's final answer.
 */
export const LocalResourcesCard: React.FC<LocalResourcesCardProps> = ({
  agentId,
  tools,
  skills,
}) => {
  const { t } = useTranslation("common");
  const [selected, setSelected] = useState<Set<string>>(() => {
    const s = new Set<string>();
    tools.forEach((x) => x.tool_id != null && s.add(`t:${x.tool_id}`));
    skills.forEach((x) => x.skill_id != null && s.add(`s:${x.skill_id}`));
    return s;
  });
  const [applied, setApplied] = useState(false);
  const [loading, setLoading] = useState(false);

  const toggle = (key: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const selectedToolIds = useMemo(
    () => tools.filter((x) => x.tool_id != null && selected.has(`t:${x.tool_id}`)).map((x) => x.tool_id!) as number[],
    [selected, tools]
  );
  const selectedSkillIds = useMemo(
    () => skills.filter((x) => x.skill_id != null && selected.has(`s:${x.skill_id}`)).map((x) => x.skill_id!) as number[],
    [selected, skills]
  );

  const handleApplyAll = async () => {
    if (selectedToolIds.length === 0 && selectedSkillIds.length === 0) {
      AntMessage.warning(t("nl2agent.localResources.selectAtLeastOne", "Please select at least one resource."));
      return;
    }
    setLoading(true);
    try {
      const res = await applyLocalResources(agentId, {
        tool_ids: selectedToolIds,
        skill_ids: selectedSkillIds,
      });
      AntMessage.success(
        t("nl2agent.localResources.applied", {
          defaultValue: "Applied {{toolCount}} tool(s) and {{skillCount}} skill(s).",
          toolCount: res.bound_tool_count,
          skillCount: res.bound_skill_count,
        })
      );
      setApplied(true);
    } catch (e: any) {
      AntMessage.error(e?.message || "Failed to apply resources.");
    } finally {
      setLoading(false);
    }
  };

  const renderRow = (item: LocalResourceItem) => {
    const key = item.kind === "tool" ? `t:${item.tool_id}` : `s:${item.skill_id}`;
    return (
      <label
        key={key}
        className="flex items-start gap-2 py-1.5 px-2 rounded hover:bg-gray-50 cursor-pointer"
      >
        <Checkbox
          checked={selected.has(key)}
          onChange={() => toggle(key)}
          disabled={applied}
          className="mt-1"
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm">{item.name}</span>
            {item.source && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200">
                {item.source}
              </span>
            )}
            {typeof item.score === "number" && (
              <span className="text-[10px] text-gray-500">score: {item.score}</span>
            )}
          </div>
          {item.description && (
            <div className="text-xs text-gray-600 mt-0.5 line-clamp-2">{item.description}</div>
          )}
          {item.reason && (
            <div className="text-xs text-gray-400 mt-0.5 italic">{item.reason}</div>
          )}
        </div>
      </label>
    );
  };

  return (
    <div className="my-3 border border-gray-200 rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <span className="font-medium text-sm">
          {t("nl2agent.localResources.title", "Recommended Local Resources")}
        </span>
        <span className="text-xs text-gray-500">
          {tools.length + skills.length} {t("nl2agent.items", "items")}
        </span>
      </div>
      <div className="max-h-80 overflow-y-auto p-1">
        {tools.length > 0 && (
          <div className="mb-2">
            <div className="text-[11px] uppercase tracking-wide text-gray-400 px-2 py-1">
              {t("nl2agent.localResources.tools", "Tools")}
            </div>
            {tools.map(renderRow)}
          </div>
        )}
        {skills.length > 0 && (
          <div>
            <div className="text-[11px] uppercase tracking-wide text-gray-400 px-2 py-1">
              {t("nl2agent.localResources.skills", "Skills")}
            </div>
            {skills.map(renderRow)}
          </div>
        )}
        {tools.length === 0 && skills.length === 0 && (
          <div className="text-sm text-gray-400 p-3">
            {t("nl2agent.localResources.empty", "No local resources found.")}
          </div>
        )}
      </div>
      <div className="px-3 py-2 border-t border-gray-200 bg-white">
        <Button
          type="primary"
          size="small"
          onClick={handleApplyAll}
          loading={loading}
          disabled={applied || (selectedToolIds.length === 0 && selectedSkillIds.length === 0)}
        >
          {applied ? (
            <>
              <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
              {t("nl2agent.localResources.appliedShort", "Applied")}
            </>
          ) : loading ? (
            <>
              <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
              {t("nl2agent.localResources.applying", "Applying...")}
            </>
          ) : (
            t("nl2agent.localResources.applyAll", "Apply All")
          )}
        </Button>
      </div>
    </div>
  );
};
