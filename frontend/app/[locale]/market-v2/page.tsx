"use client";

import React, { useState, useCallback, useMemo } from "react";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Input, App, Spin, Empty } from "antd";
import { Search, Package } from "lucide-react";
import {
  SolutionMarketCard,
  SolutionCardData,
} from "@/components/market/SolutionMarketCard";
import { SolutionConfigDrawer } from "@/components/market/SolutionConfigDrawer";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import type { Agent } from "@/types/agentConfig";
import { useRouter } from "next/navigation";

/**
 * Built-in solution catalog. Currently focused on AI 资讯速递 (ai_news_hot)
 * — a zero-config solution that queries aihot.virxact.com public API.
 */
const BUILTIN_SOLUTIONS: SolutionCardData[] = [
  {
    id: 1,
    display_name: "AI 资讯速递",
    name: "ai_news_hot",
    description:
      "实时查询每天精选的 AI 模型/产品/行业/论文动态，自动整理成中文简报。免配置免登录，一句话获取今日 AI 圈动态。",
    author: "Nexent",
    source: "official",
    solution_type: "single",
    category: {
      name: "content",
      display_name: "Content",
      display_name_zh: "资讯速递",
    },
    tags: [
      { id: "1", display_name: "AI资讯" },
      { id: "2", display_name: "免配置" },
      { id: "3", display_name: "实时" },
    ],
    download_count: 321,
    agent_count: 1,
    skill_count: 1,
    mcp_count: 0,
    tool_keywords: [
      "ai_news_hot",
      "资讯",
      "news",
      "aihot",
      "hot",
      "日报",
      "daily",
      "AI",
    ],
  },
];

function agentMatchesKeywords(agent: Agent, keywords?: string[]): boolean {
  if (!keywords || keywords.length === 0) return false;
  const haystack = [
    agent.name || "",
    agent.display_name || "",
    agent.description || "",
  ]
    .join(" ")
    .toLowerCase();
  return keywords.some((kw) => haystack.includes(kw.toLowerCase()));
}

function resolveSolutions(
  solutions: SolutionCardData[],
  agents: Agent[]
): SolutionCardData[] {
  const availableAgents = agents;
  const firstAgent = availableAgents[0];

  return solutions.map((sol) => {
    if (sol.tool_keywords && sol.tool_keywords.length > 0) {
      const matched = availableAgents.find((agent) =>
        agentMatchesKeywords(agent, sol.tool_keywords)
      );
      if (matched) {
        const agentExtra = matched as Agent & {
          is_available?: boolean;
          unavailable_reasons?: string[];
        };
        return {
          ...sol,
          agent_id: Number(matched.id) || undefined,
          resolved: true,
          is_available: agentExtra.is_available !== false,
          unavailable_reasons: agentExtra.unavailable_reasons || [],
        };
      }
    }
    if (firstAgent) {
      const firstAgentExtra = firstAgent as Agent & {
        is_available?: boolean;
        unavailable_reasons?: string[];
      };
      return {
        ...sol,
        agent_id: Number(firstAgent.id) || undefined,
        resolved: true,
        is_available: firstAgentExtra.is_available !== false,
        unavailable_reasons: firstAgentExtra.unavailable_reasons || [],
      };
    }
    return { ...sol, resolved: false };
  });
}

export default function UnifiedMarketPage() {
  const { i18n } = useTranslation("common");
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";
  const { message } = App.useApp();
  const router = useRouter();
  const [searchKeyword, setSearchKeyword] = useState("");
  const [configSolution, setConfigSolution] = useState<SolutionCardData | null>(
    null
  );

  const { agents: publishedAgents, isLoading: isLoadingSolutions } =
    usePublishedAgentList();

  const solutions: SolutionCardData[] = useMemo(
    () => resolveSolutions(BUILTIN_SOLUTIONS, publishedAgents || []),
    [publishedAgents]
  );

  const filteredSolutions = searchKeyword.trim()
    ? solutions.filter((s) => {
        const kw = searchKeyword.toLowerCase();
        return (
          (s.name || "").toLowerCase().includes(kw) ||
          (s.display_name || "").toLowerCase().includes(kw) ||
          (s.description || "").toLowerCase().includes(kw)
        );
      })
    : solutions;

  const handleStartChat = useCallback(
    (solution: SolutionCardData) => {
      if (solution.agent_id) {
        sessionStorage.setItem(
          "nexent_last_used_agent_id",
          String(solution.agent_id)
        );
        router.push("/newchat");
      } else {
        message.warning(
          isZh
            ? "该方案无法直接启动对话"
            : "This solution cannot launch chat directly"
        );
      }
    },
    [router, isZh, message]
  );

  const handleConfig = useCallback(
    (solution: SolutionCardData) => {
      if (solution.agent_id) {
        setConfigSolution(solution);
      } else {
        message.warning(
          isZh ? "该方案无法配置" : "This solution cannot be configured"
        );
      }
    },
    [isZh, message]
  );

  const handleViewDetails = useCallback((solution: SolutionCardData) => {
    if (solution.agent_id) {
      setConfigSolution(solution);
    }
  }, []);

  const renderLoading = () => (
    <div className="flex items-center justify-center py-20">
      <Spin size="large" />
    </div>
  );

  const renderEmpty = () => (
    <Empty description={isZh ? "暂无方案" : "No solutions"} className="py-20" />
  );

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 20 }}
      className="max-w-7xl mx-auto p-4 sm:p-6"
    >
      {/* Page Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Package className="h-5 w-5 text-slate-600 dark:text-slate-300" />
          <div>
            <h1 className="text-base font-semibold text-slate-900 dark:text-slate-100">
              {isZh ? "方案市场" : "Solution Market"}
            </h1>
            <p className="text-xs text-slate-400 dark:text-slate-500">
              {isZh ? "精选方案，一键开聊" : "Curated solutions, chat-ready"}
            </p>
          </div>
        </div>
        <Input
          prefix={<Search className="h-4 w-4 text-slate-400" />}
          placeholder={isZh ? "搜索方案名称或描述..." : "Search solutions..."}
          value={searchKeyword}
          onChange={(e) => setSearchKeyword(e.target.value)}
          className="max-w-xs"
          allowClear
        />
      </div>

      {/* Solutions loading / empty states */}
      {isLoadingSolutions && renderLoading()}
      {!isLoadingSolutions && filteredSolutions.length === 0 && renderEmpty()}

      {/* Card Grid */}
      {!isLoadingSolutions && filteredSolutions.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filteredSolutions.map((solution, idx) => (
            <SolutionMarketCard
              key={solution.id}
              solution={solution}
              onChat={handleStartChat}
              onConfig={handleConfig}
              onViewDetails={handleViewDetails}
              index={idx}
            />
          ))}
        </div>
      )}

      {/* Unified config drawer */}
      <SolutionConfigDrawer
        open={!!configSolution}
        solution={configSolution}
        onClose={() => setConfigSolution(null)}
        onChat={handleStartChat}
      />
    </motion.div>
  );
}
