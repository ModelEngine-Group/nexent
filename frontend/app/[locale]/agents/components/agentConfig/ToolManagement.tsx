"use client";

import { useState, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Tooltip } from "antd";
import { useToolList } from "@/hooks/agent/useToolList";
import { useAgentStore } from "@/stores/agentStore";
import { usePrefetchKnowledgeBases } from "@/hooks/useKnowledgeBaseSelector";
import { useConfig } from "@/hooks/useConfig";
import { ChevronRight, Settings, X, AlertTriangle } from "lucide-react";
import type { Tool, ToolParam } from "@/types/agentConfig";
import { TOOL_SOURCE_TYPES } from "@/const/agentConfig";
import { isManagedKnowledgeTool } from "@/lib/managedKnowledgeTools";
import ToolConfigModal from "./tool/ToolConfigModal";
import { useMergedToolParams } from "./tool/useMergedToolParams";
import {
  TOOLS_REQUIRING_EMBEDDING,
  TOOLS_REQUIRING_IMAGE_UNDERSTANDING,
  TOOLS_REQUIRING_AUDIO_UNDERSTANDING,
  TOOLS_REQUIRING_VIDEO_UNDERSTANDING,
  getToolKbType,
  getToolLabels,
  mergeCanonicalTool,
} from "./tool/utils";

// --- Local tool helpers (not in utils) ---

function isToolDisabledDueToVlm(
  name: string,
  img: boolean,
  vid: boolean,
  audio: boolean
): boolean {
  if (TOOLS_REQUIRING_IMAGE_UNDERSTANDING.includes(name)) return !img;
  if (TOOLS_REQUIRING_AUDIO_UNDERSTANDING.includes(name)) return !audio;
  if (TOOLS_REQUIRING_VIDEO_UNDERSTANDING.includes(name)) return !vid;
  return false;
}

function isToolDisabledDueToEmbedding(name: string, emb: boolean): boolean {
  if (!TOOLS_REQUIRING_EMBEDDING.includes(name)) return false;
  return !emb;
}

type SourceKey = "local" | "mcp" | "langchain";
const SOURCE_META: Record<
  SourceKey,
  { sourceValue: string; label: string; dot: string; accentClass: string }
> = {
  local: {
    sourceValue: TOOL_SOURCE_TYPES.LOCAL,
    label: "toolPool.group.local",
    dot: "bg-emerald-500",
    accentClass: "bg-emerald-500/10 text-emerald-600",
  },
  mcp: {
    sourceValue: TOOL_SOURCE_TYPES.MCP,
    label: "toolPool.group.mcp",
    dot: "bg-sky-500",
    accentClass: "bg-sky-500/10 text-sky-600",
  },
  langchain: {
    sourceValue: TOOL_SOURCE_TYPES.LANGCHAIN,
    label: "toolPool.group.langchain",
    dot: "bg-violet-500",
    accentClass: "bg-violet-500/10 text-violet-600",
  },
};

interface ToolManagementProps {
  currentAgentId?: number;
}

/** Display selected tools as grouped, collapsible cards (demo layout). */
export default function ToolManagement({
  currentAgentId,
}: ToolManagementProps) {
  const { t } = useTranslation("common");
  const { prefetchKnowledgeBases } = usePrefetchKnowledgeBases();
  const {
    isImageUnderstandingAvailable,
    isVideoUnderstandingAvailable,
    isAudioUnderstandingAvailable,
    isEmbeddingAvailable,
  } = useConfig();

  const selectedTools = useAgentStore(
    (state) => state.editedAgent?.tools ?? []
  );
  const updateTools = useAgentStore((state) => state.updateTools);

  const [modalOpen, setModalOpen] = useState(false);
  const [configTool, setConfigTool] = useState<Tool | null>(null);
  const [configParams, setConfigParams] = useState<ToolParam[]>([]);
  const [collapsedCats, setCollapsedCats] = useState<Record<string, boolean>>(
    {}
  );

  // Canonical tool list (with `inputs`) — used to backfill any missing
  // fields on the stored tool object so the tool test panel always
  // operates in parsed mode and shows the manual-input toggle.
  const { availableTools } = useToolList({
    enabled: true,
  });

  // Tool availability is refreshed independently from the agent draft. Do not
  // persist a cleanup during initialization because it is indistinguishable
  // from a user tool edit and can race with agent switching.

  // Keep system-managed tools in the draft for persistence, but omit them from
  // the user-facing selected-tools list.
  const visibleSelectedTools = useMemo(() => {
    return selectedTools.filter((tool) => {
      if (isManagedKnowledgeTool(tool)) return false;
      const canonicalTool = availableTools.find(
        (availableTool: Tool) => String(availableTool.id) === String(tool.id)
      );
      return (canonicalTool ?? tool).is_user_selectable !== false;
    });
  }, [availableTools, selectedTools]);

  // --- Group by source → category ---
  const grouped = groupToolsBySource(visibleSelectedTools);

  const mergeParams = useMergedToolParams(currentAgentId);

  const openConfig = useCallback(
    async (tool: Tool) => {
      const kbType = getToolKbType(tool.name);
      if (kbType) prefetchKnowledgeBases(kbType);
      const current = useAgentStore.getState().editedAgent?.tools ?? [];
      const configured = current.find(
        (t) => parseInt(t.id) === parseInt(tool.id)
      );
      const configuredTool = configured
        ? { ...tool, ...configured, initParams: configured.initParams }
        : tool;
      const toolToUse = mergeCanonicalTool(configuredTool, availableTools);
      const merged = await mergeParams(toolToUse);
      if (!merged) return;
      setConfigTool(toolToUse);
      setConfigParams(merged);
      setModalOpen(true);
    },
    [mergeParams, prefetchKnowledgeBases, availableTools]
  );

  const removeTool = useCallback(
    (toolId: string) => {
      const current = useAgentStore.getState().editedAgent?.tools ?? [];
      updateTools(current.filter((t) => t.id !== toolId));
    },
    [updateTools]
  );

  const toggleCat = (cat: string) =>
    setCollapsedCats((p) => ({ ...p, [cat]: !p[cat] }));

  if (grouped.length === 0) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-dashed border-gray-200 py-10 text-sm text-gray-400">
        {t("toolPool.noToolsSelected")}
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto pr-1">
      <div className="mb-3 flex items-center gap-1.5">
        <span className="flex items-center gap-1.5 text-sm font-medium text-gray-700">
          {t("toolPool.selectedToolsLabel")}
          <span className="text-xs text-gray-400">
            ({visibleSelectedTools.length})
          </span>
        </span>
      </div>

      <div className="space-y-4">
        {grouped.map((src) => (
          <div key={src.key}>
            <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-gray-500">
              <span
                className={`size-1.5 rounded-full ${SOURCE_META[src.key].dot}`}
              />
              {t(SOURCE_META[src.key].label)}（{src.totalCount}）
            </div>

            <div className="space-y-3">
              {src.categories.map((cat) => {
                const catKey = `${src.key}-${cat.category}`;
                const isCollapsed = collapsedCats[catKey] ?? false;
                const accent = SOURCE_META[src.key].accentClass;

                return (
                  <div
                    key={catKey}
                    className="overflow-hidden rounded-lg border border-gray-200 bg-white"
                  >
                    <button
                      onClick={() => toggleCat(catKey)}
                      className={`flex w-full items-center gap-1.5 px-3 py-1.5 text-left transition-colors hover:bg-gray-50 ${
                        !isCollapsed ? "border-b border-gray-100" : ""
                      }`}
                    >
                      <ChevronRight
                        className={`size-3.5 shrink-0 text-gray-400 transition-transform ${!isCollapsed ? "rotate-90" : ""}`}
                      />
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${accent}`}
                      >
                        {t(cat.category)}
                      </span>
                      <span className="text-[10px] text-gray-400">
                        {cat.tools.length}
                      </span>
                    </button>

                    {!isCollapsed && (
                      <div className="divide-y divide-gray-100">
                        {cat.tools.map((tool) => {
                          const labels = getToolLabels(tool);
                          const toolUnavailableReasons =
                            tool.unavailable_reasons || [];
                          const isModelUnavailable =
                            toolUnavailableReasons.includes(
                              "mcp_model_unavailable"
                            );
                          const disabled =
                            isToolDisabledDueToVlm(
                              tool.name,
                              isImageUnderstandingAvailable,
                              isVideoUnderstandingAvailable,
                              isAudioUnderstandingAvailable
                            ) ||
                            isToolDisabledDueToEmbedding(
                              tool.name,
                              isEmbeddingAvailable
                            ) ||
                            isModelUnavailable;

                          return (
                            <div
                              key={tool.id}
                              className="group flex items-center gap-2 px-3 py-2"
                            >
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2">
                                  <span
                                    className={`truncate font-mono text-xs font-medium ${isModelUnavailable ? "text-gray-400" : "text-gray-800"}`}
                                  >
                                    {tool.name}
                                  </span>
                                  {labels.slice(0, 2).map((l) => (
                                    <span
                                      key={l}
                                      className="shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-600"
                                    >
                                      {l}
                                    </span>
                                  ))}
                                  {labels.length > 2 && (
                                    <Tooltip title={labels.slice(2).join(", ")}>
                                      <span className="shrink-0 cursor-help rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">
                                        +{labels.length - 2}
                                      </span>
                                    </Tooltip>
                                  )}
                                  {isModelUnavailable && (
                                    <Tooltip
                                      title={t(
                                        "toolPool.mcpModelUnavailableTooltip"
                                      )}
                                    >
                                      <AlertTriangle
                                        size={14}
                                        className="shrink-0 text-orange-400"
                                      />
                                    </Tooltip>
                                  )}
                                  {disabled && !isModelUnavailable && (
                                    <AlertTriangle
                                      size={14}
                                      className="shrink-0 text-orange-400"
                                    />
                                  )}
                                </div>
                              </div>

                              <button
                                onClick={() => openConfig(tool)}
                                className="flex size-7 shrink-0 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
                                title={t("toolPool.configure")}
                              >
                                <Settings className="size-4" />
                              </button>

                              <button
                                onClick={() => removeTool(tool.id)}
                                className="flex size-7 shrink-0 items-center justify-center rounded-md text-transparent transition-colors hover:bg-red-50 hover:text-red-500 group-hover:text-gray-400"
                                title={t("toolPool.remove")}
                              >
                                <X className="size-4" />
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {modalOpen && (
        <ToolConfigModal
          isOpen={modalOpen}
          onCancel={() => {
            setModalOpen(false);
            setConfigTool(null);
            setConfigParams([]);
          }}
          tool={configTool!}
          initialParams={configParams}
          selectedTool={configTool}
          currentAgentId={currentAgentId}
        />
      )}
    </div>
  );
}

// ─── Pure helper ─────────────────────────────────────────────────────────────

interface CatGroup {
  category: string;
  tools: Tool[];
}
interface SourceGroup {
  key: SourceKey;
  categories: CatGroup[];
  totalCount: number;
}

function groupToolsBySource(tools: Tool[]): SourceGroup[] {
  const result: SourceGroup[] = [];
  for (const [key, meta] of Object.entries(SOURCE_META) as [
    SourceKey,
    (typeof SOURCE_META)[SourceKey],
  ][]) {
    const srcTools = tools.filter((tool) => tool.source === meta.sourceValue);
    if (srcTools.length === 0) continue;
    const catMap = new Map<string, Tool[]>();
    for (const tool of srcTools) {
      const cat =
        key === "mcp"
          ? tool.usage?.trim() || "toolPool.category.other"
          : tool.category?.trim() || "toolPool.category.other";
      if (!catMap.has(cat)) catMap.set(cat, []);
      catMap.get(cat)!.push(tool);
    }
    const categories = Array.from(catMap.entries())
      .map(([cat, ts]) => ({ category: cat, tools: ts }))
      .sort((a, b) => {
        if (a.category === "toolPool.category.other") return 1;
        if (b.category === "toolPool.category.other") return -1;
        return a.category.localeCompare(b.category);
      });
    result.push({ key, categories, totalCount: srcTools.length });
  }
  return result;
}
