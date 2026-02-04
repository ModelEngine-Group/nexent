"use client";

import React, { useState, useMemo, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useRouter } from "next/navigation";
import { App } from "antd";
import {
  Trash2,
  Download,
  Network,
  MessageSquare,
  CheckCircle,
  XCircle,
  Edit,
  Sparkles,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { Avatar } from "antd";
import AgentCallRelationshipModal from "@/components/ui/AgentCallRelationshipModal";
import AgentDetailModal from "./AgentDetailModal";
import {
  deleteAgent,
  exportAgent,
  searchAgentInfo,
  clearAgentNewMark,
} from "@/services/agentConfigService";
import { generateAvatarFromName } from "@/lib/avatar";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { USER_ROLES } from "@/const/auth";
import { Agent } from "@/types/agentConfig";
import log from "@/lib/logger";

interface AgentCardProps {
  agent: Agent;
  onRefresh: () => void;
}

export default function AgentCard({ agent, onRefresh }: AgentCardProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { user } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();
  const { confirm } = useConfirmModal();
  const router = useRouter();

  const [isDeleting, setIsDeleting] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [showRelationship, setShowRelationship] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const [agentDetails, setAgentDetails] = useState<any>(null);
  const [isLoadingDetails, setIsLoadingDetails] = useState(false);


  // Generate avatar URL from agent name
  const avatarUrl = generateAvatarFromName(agent.display_name || agent.name);

  // Check if agent is new (marked as new in database)
  const [isNewAgent, setIsNewAgent] = useState(() => agent.is_new || false);

  // Keep local isNewAgent state in sync when prop changes (e.g., after refresh)
  useEffect(() => {
    setIsNewAgent(agent.is_new || false);
  }, [agent.is_new]);

  // Handle delete agent
  const handleDelete = () => {
    confirm({
      title: t("space.deleteConfirm.title", "Delete Agent"),
      content: t(
        "space.deleteConfirm.content",
        `Are you sure you want to delete agent "${agent.display_name}"? This action cannot be undone.`
      ),
      onOk: async () => {
        setIsDeleting(true);
        try {
          const result = await deleteAgent(parseInt(agent.id));
          if (result.success) {
            message.success(
              t("space.deleteSuccess", "Agent deleted successfully")
            );
            onRefresh();
          } else {
            message.error(result.message || "Failed to delete agent");
          }
        } catch (error) {
          log.error("Failed to delete agent:", error);
          message.error("Failed to delete agent");
        } finally {
          setIsDeleting(false);
        }
      },
    });
  };

  // Handle export agent
  const handleExport = async () => {
    setIsExporting(true);
    try {
      const result = await exportAgent(parseInt(agent.id));
      if (result.success && result.data) {
        // Create a download link
        const dataStr = JSON.stringify(result.data, null, 2);
        const dataBlob = new Blob([dataStr], { type: "application/json" });
        const url = URL.createObjectURL(dataBlob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `agent_${agent.name}_${Date.now()}.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);

        message.success(
          t("space.exportSuccess", "Agent exported successfully")
        );
      } else {
        message.error(result.message || "Failed to export agent");
      }
    } catch (error) {
      log.error("Failed to export agent:", error);
      message.error("Failed to export agent");
    } finally {
      setIsExporting(false);
    }
  };

  // Handle view relationship
  const handleViewRelationship = () => {
    setShowRelationship(true);
  };

  const handleChat = () => {
    if (agent.id) {
      sessionStorage.setItem("selectedAgentId", agent.id);
      router.push("/chat");
    }
  };

  // Handle edit - navigate to agents view
  const handleEdit = () => {
    router.push("/agents");
  };

  const queryClient = useQueryClient();

  // Handle view detail
  const handleViewDetail = async () => {
    // Mark agent as viewed (clear NEW marker in database)
    if (isNewAgent) {
      try {
        const result = await clearAgentNewMark(agent.id);
        if (result?.success) {
          setIsNewAgent(false); 
          queryClient.invalidateQueries({ queryKey: ["agents"] });
        } else {
          log.warn("Failed to clear NEW mark for agent", agent.id, result);
        }
      } catch (error) {
        log.error("Error clearing NEW mark:", error);
      }
    }

    setShowDetail(true);
    setIsLoadingDetails(true);
    try {
      const result = await searchAgentInfo(parseInt(agent.id));
      if (result.success) {
        setAgentDetails(result.data);
      } else {
        message.error(result.message || "Failed to load agent details");
      }
    } catch (error) {
      log.error("Failed to load agent details:", error);
      message.error("Failed to load agent details");
    } finally {
      setIsLoadingDetails(false);
    }
  };

  return (
    <>
      <div
        className={`w-full h-full rounded-lg border transition-all duration-300 p-4 flex flex-col group cursor-pointer ${
          isNewAgent
            ? "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 hover:shadow-lg hover:border-blue-300 dark:hover:border-blue-700"
            : "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 hover:shadow-lg hover:border-blue-300 dark:hover:border-blue-700"
        }`}
        onClick={handleViewDetail}
      >
        {/* Avatar and Status badge */}
        <div className="flex items-start gap-3 mb-3">
          <Avatar src={avatarUrl} size={40} className="w-10 h-10">
            <span className="text-lg font-bold text-blue-600 dark:text-blue-400">
              {agent.display_name?.charAt(0)?.toUpperCase() || "A"}
            </span>
          </Avatar>

          {/* Status badge and NEW marker */}
          <div className="flex-1 flex justify-end items-center gap-2">
            {/* NEW marker */}
            {isNewAgent && (
              <div className="inline-flex items-center gap-1 px-2 py-0.5 bg-amber-50 dark:bg-amber-900/10 text-amber-700 dark:text-amber-300 rounded-full text-xs font-medium border border-amber-200">
                <Sparkles className="h-3 w-3 flex-shrink-0" />
                <span className="tracking-wide">{t("space.new", "NEW")}</span>
              </div>
            )}

            {/* Status badge */}
            {agent.is_available ? (
              <div className="flex items-center gap-1 px-2 py-0.5 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-full text-xs">
                <CheckCircle className="h-3 w-3" />
                <span>{t("space.status.available", "Available")}</span>
              </div>
            ) : (
              <div className="flex items-center gap-1 px-2 py-0.5 bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 rounded-full text-xs">
                <XCircle className="h-3 w-3" />
                <span>{t("space.status.unavailable", "Unavailable")}</span>
              </div>
            )}
          </div>
        </div>

        {/* Agent info - flexible height */}
        <div className="flex-1 flex flex-col min-h-0 mb-3">
          <h3 className="text-base font-semibold text-slate-900 dark:text-white mb-2 line-clamp-2">
            {agent.display_name || agent.name}
          </h3>
          {agent.author ? (
            <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">
              {t("market.by", {
                defaultValue: "By {{author}}",
                author: agent.author,
              })}
            </p>
          ) : (
            <div className="h-4 mb-2" aria-hidden />
          )}
          <div className="flex-1 overflow-hidden">
            <p className="text-sm text-slate-600 dark:text-slate-300 line-clamp-4">
              {agent.description || t("space.noDescription", "No description")}
            </p>
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-200 dark:border-slate-700">


            <button
              onClick={(e) => {
                e.stopPropagation();
                handleEdit();
              }}
              className="p-2 rounded-md hover:bg-blue-50 dark:hover:bg-blue-900/20 text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
              title={t("space.actions.edit", "Edit")}
            >
              <Edit className="h-4 w-4" />
            </button>


            <button
              onClick={(e) => {
                e.stopPropagation();
                handleDelete();
              }}
              disabled={isDeleting}
              className="p-2 rounded-md hover:bg-red-50 dark:hover:bg-red-900/20 text-slate-400 hover:text-red-600 dark:hover:text-red-400 transition-colors disabled:opacity-50"
              title={t("space.actions.delete", "Delete")}
            >
              <Trash2 className="h-4 w-4" />
            </button>

          <button
            onClick={(e) => {
              e.stopPropagation();
              handleExport();
            }}
            disabled={isExporting}
            className="p-2 rounded-md hover:bg-blue-50 dark:hover:bg-blue-900/20 text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 transition-colors disabled:opacity-50"
            title={t("space.actions.export", "Export")}
          >
            <Download className="h-4 w-4" />
          </button>

          <button
            onClick={(e) => {
              e.stopPropagation();
              handleViewRelationship();
            }}
            className="p-2 rounded-md hover:bg-purple-50 dark:hover:bg-purple-900/20 text-slate-400 hover:text-purple-600 dark:hover:text-purple-400 transition-colors"
            title={t("space.actions.relationship", "View Relationships")}
          >
            <Network className="h-4 w-4" />
          </button>

          <button
            onClick={(e) => {
              e.stopPropagation();
              handleChat();
            }}
            disabled={!agent.is_available}
            className={`p-2 rounded-md transition-colors ${
              agent.is_available
                ? "hover:bg-green-50 dark:hover:bg-green-900/20 text-slate-400 hover:text-green-600 dark:hover:text-green-400"
                : "text-slate-300 dark:text-slate-600 cursor-not-allowed"
            }`}
            title={
              agent.is_available
                ? t("space.actions.chat", "Chat")
                : t("space.status.unavailable", "Unavailable")
            }
          >
            <MessageSquare className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Relationship Modal */}
      <AgentCallRelationshipModal
        visible={showRelationship}
        onClose={() => setShowRelationship(false)}
        agentId={parseInt(agent.id)}
        agentName={agent.display_name || agent.name}
      />

      {/* Detail Modal */}
      <AgentDetailModal
        visible={showDetail}
        onClose={() => setShowDetail(false)}
        agentDetails={agentDetails}
        loading={isLoadingDetails}
      />
    </>
  );
}
