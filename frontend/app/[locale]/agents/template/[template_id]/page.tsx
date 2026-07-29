"use client";

import React, { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { App, Spin } from "antd";
import { useRouter, useParams } from "next/navigation";
import { TemplateHeader, TemplateHeaderData } from "./components/TemplateHeader";
import { RecipeVisualizer, RecipeVisualizerData } from "./components/RecipeVisualizer";
import { RecipeForm, RecipeVariable } from "./components/RecipeForm";
import { fetchMarketAgentDetail, instantiateMarketAgent, launchMarketAgent } from "@/services/marketService";
import { useToolList } from "@/hooks/agent/useToolList";
import log from "@/lib/logger";

/**
 * TemplateDetailPage - Template detail with Recipe visualization, form, and reviews.
 *
 * Loads a real market template (GET /market/agents/{id}) and instantiates a new
 * agent from it (POST /market/agents/{id}/instantiate) with the user's Recipe
 * variable values. On success, navigates to newchat with the new agent selected.
 */
export default function TemplateDetailPage() {
  const { t, i18n } = useTranslation("common");
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";
  const { message, modal } = App.useApp();
  const router = useRouter();

  // template_id in the route is the agent_repository_id (market template id).
  // Use Next's useParams for a stable client value (avoids SSR window issues).
  const params = useParams();
  const templateId = Number(params?.template_id) || null;
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<any>(null);
  const [isCreating, setIsCreating] = useState(false);
  // Tenant's scanned tools — used to show each bundled tool's availability.
  const { availableTools } = useToolList();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!templateId) {
        if (!cancelled) setLoading(false);
        return;
      }
      setLoading(true);
      try {
        const data = await fetchMarketAgentDetail(templateId);
        if (!cancelled) setDetail(data);
      } catch (error) {
        log.error("Failed to load template detail:", error);
        if (!cancelled)
          message.error(
            isZh ? "加载方案详情失败" : "Failed to load template detail"
          );
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [templateId]);

  // Recipe is returned by the backend detail endpoint (market_service attaches it)
  const recipe = (detail?.recipe || {}) as {
    variables?: RecipeVariable[];
    layers?: Array<{
      layer_type: string;
      entity_type?: string;
      entity_name: string;
      source?: string;
    }>;
  };

  const variables: RecipeVariable[] = useMemo(
    () => recipe.variables || [],
    [recipe.variables]
  );

  const recipeVisualizerData: RecipeVisualizerData | null = useMemo(() => {
    if (!detail) return null;
    const layers = recipe.layers || [];
    const agentNode = layers
      .filter((l) => l.layer_type === "agent")
      .map((l) => ({
        type: "agent" as const,
        name: l.entity_name,
        label: `agent · ${l.source || "official"}`,
        source: (l.source as any) || "official",
      }))[0] || {
        type: "agent" as const,
        name: detail.name,
        label: "main agent",
        source: "official" as const,
      };
    const skillNodes = layers
      .filter((l) => l.layer_type === "skill")
      .map((l) => ({
        type: "skill" as const,
        name: l.entity_name,
        label: `skill · ${l.source || "official"}`,
        source: (l.source as any) || "official",
      }));
    const mcpNodes = layers
      .filter((l) => l.layer_type === "mcp")
      .map((l) => ({
        type: "mcp" as const,
        name: l.entity_name,
        label: `mcp · ${l.source || "official"}`,
        source: (l.source as any) || "official",
      }));
    return { agent: agentNode, skills: skillNodes, mcps: mcpNodes };
  }, [detail, recipe.layers]);

  const headerData: TemplateHeaderData | null = useMemo(() => {
    if (!detail) return null;
    return {
      id: detail.id,
      name: detail.name,
      display_name: detail.display_name,
      description: detail.description,
      version: "V1",
      author: detail.author || "nexent-official",
      source: (detail.source as "official" | "community") || "official",
      download_count: detail.download_count || 0,
      updated_at: detail.updated_at || "",
      icon: "📰",
    };
  }, [detail]);


  const buildDefaultValues = () => {
    const vals: Record<string, any> = {};
    variables.forEach((v) => {
      vals[v.key] = v.default ?? "";
    });
    return vals;
  };

  const doInstantiate = async (
    values: Record<string, any>,
    forceImport: boolean
  ) => {
    if (!templateId) return;
    setIsCreating(true);
    try {
      const result = await instantiateMarketAgent(templateId, values, forceImport);
      if (result.agent_id) {
        sessionStorage.setItem(
          "nexent_last_used_agent_id",
          String(result.agent_id)
        );
        message.success(
          isZh ? "Agent 创建成功，正在跳转对话…" : "Agent created, opening chat…"
        );
        router.push("/newchat");
        return;
      }
      // agent_id null → precheck blocked
      const missing = result.precheck?.missing || [];
      if (missing.length > 0 && !forceImport) {
        modal.confirm({
          title: isZh ? "依赖缺失，是否强制创建？" : "Missing dependencies — force create?",
          content:
            (isZh
              ? `以下依赖未就绪：${missing
                  .map((m: any) => m.name || m.key)
                  .join(", ")}。强制创建后 Agent 可能无法正常运行，是否继续？`
              : `Missing: ${missing
                  .map((m: any) => m.name || m.key)
                  .join(", ")}. Force-create may produce a non-functional agent. Continue?`),
          okText: isZh ? "强制创建" : "Force create",
          cancelText: isZh ? "取消" : "Cancel",
          onOk: () => doInstantiate(values, true),
        });
        return;
      }
      message.error(
        result.message || (isZh ? "创建失败" : "Instantiation failed")
      );
    } catch (error: any) {
      log.error("Instantiate failed:", error);
      message.error(
        isZh
          ? `创建失败：${error?.message || "未知错误"}`
          : `Instantiation failed: ${error?.message || "unknown"}`
      );
    } finally {
      setIsCreating(false);
    }
  };

  const handleFormSubmit = (values: Record<string, any>) => {
    doInstantiate(values, false);
  };

  // "直接开聊" — launch (get-or-create) the solution with default Recipe
  // values, WorkBuddy-style. Reuses an existing same-named agent if present.
  const doLaunch = async () => {
    if (!templateId) return;
    setIsCreating(true);
    try {
      const res = await launchMarketAgent(templateId);
      if (res.agent_id) {
        sessionStorage.setItem(
          "nexent_last_used_agent_id",
          String(res.agent_id)
        );
        message.success(
          isZh ? "已进入对话" : "Entering chat"
        );
        router.push("/newchat");
      } else {
        message.error(res.message || (isZh ? "启动失败" : "Launch failed"));
      }
    } catch (error: any) {
      log.error("Launch failed:", error);
      message.error(
        isZh
          ? `启动失败：${error?.message || "未知错误"}`
          : `Launch failed: ${error?.message || "unknown"}`
      );
    } finally {
      setIsCreating(false);
    }
  };

  const handleCreate = () => {
    doLaunch();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spin size="large" />
      </div>
    );
  }

  if (!detail || !headerData || !recipeVisualizerData) {
    return (
      <div className="max-w-4xl mx-auto p-6 text-center text-slate-500">
        {isZh ? "方案未找到" : "Template not found"}
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 20 }}
      className="max-w-4xl mx-auto p-4 sm:p-6 space-y-6"
    >
      {isCreating && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-white/60 dark:bg-black/40 backdrop-blur-sm">
          <Spin size="large" />
        </div>
      )}

      {/* Template Header */}
      <TemplateHeader template={headerData} onCreate={handleCreate} />

      {/* Introduction */}
      <section>
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100 mb-2">
          {isZh ? "介绍" : "Introduction"}
        </h2>
        <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed">
          {detail.business_description || detail.description}
        </p>
      </section>

      {/* Recipe Visualizer */}
      <section>
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100 mb-1">
          {isZh ? "Recipe 组成" : "Recipe composition"}
        </h2>
        <p className="text-xs text-slate-400 dark:text-slate-500 mb-2">
          {isZh
            ? "模板中的 Agent + Skills + MCPs 组合"
            : "Agent + Skills + MCPs combined in this template"}
        </p>
        <RecipeVisualizer data={recipeVisualizerData} />
      </section>

      {/* 内置工具 — 工具维度：列出方案内置工具 + 租户级可用状态 */}
      {Array.isArray(detail.tools) && detail.tools.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              {isZh ? "内置工具" : "Bundled tools"}
            </h2>
            <button
              type="button"
              onClick={() => router.push("/agents")}
              className="text-xs text-[#534AB7] hover:underline dark:text-purple-300"
            >
              {isZh ? "去工具管理 →" : "Tool management →"}
            </button>
          </div>
          <p className="text-xs text-slate-400 dark:text-slate-500 mb-2">
            {isZh
              ? "工具参数（如搜索 Key）在工具管理页按租户级配置，所有方案共用。未启用的工具需先在工具管理开启。"
              : "Tool params (e.g. search keys) are configured per-tenant in Tool Management, shared across solutions. Tools not enabled here must be turned on there first."}
          </p>
          <div className="flex flex-col gap-1.5">
            {detail.tools.map((tool: any, idx: number) => {
              const name = tool?.name || tool?.class_name || "tool";
              const enabled = availableTools.some(
                (t: any) => t.name === name && t.is_available !== false
              );
              return (
                <div
                  key={name || idx}
                  className="flex items-center justify-between rounded-md border border-slate-200 dark:border-slate-700 px-3 py-1.5"
                >
                  <span className="text-xs font-mono text-slate-700 dark:text-slate-200">
                    {name}
                  </span>
                  <span
                    className={`text-[11px] px-2 py-0.5 rounded-full ${
                      enabled
                        ? "bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400"
                        : "bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400"
                    }`}
                  >
                    {enabled
                      ? isZh ? "可用 ✓" : "Available ✓"
                      : isZh ? "未启用" : "Not enabled"}
                  </span>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Recipe Form */}
      <section>
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100 mb-1">
          {isZh ? "配置方案变量" : "Configure solution variables"}
        </h2>
        <p className="text-xs text-slate-400 dark:text-slate-500 mb-2">
          {isZh
            ? `按需调整模型 / MCP 地址等变量，然后点击"一键创建"生成你的 Agent`
            : 'Adjust model / MCP URL etc. as needed, then click "Create" to build your agent'}
        </p>
        <RecipeForm
          variables={variables}
          onSubmit={handleFormSubmit}
          submitLabel={isZh ? "一键创建" : "Create"}
        />
      </section>

    </motion.div>
  );
}
