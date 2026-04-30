"use client";

import { useCallback, useEffect, useState } from "react";
import { App } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import log from "@/lib/logger";
import {
  deleteCommunityMcpTool,
  updateCommunityMcpTool,
} from "@/services/mcpToolsService";
import type { CommunityMcpCard } from "@/types/mcpTools";
import { MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";

export interface PublishedServiceEditDraft {
  communityId: number;
  name: string;
  description: string;
  version: string;
  tags: string[];
}

const draftFromItem = (
  item: CommunityMcpCard
): PublishedServiceEditDraft | null => {
  if (!item.communityId) return null;
  return {
    communityId: item.communityId,
    name: item.name || "",
    description: item.description || "",
    version: item.version || "",
    tags: item.tags || [],
  };
};

/**
 * Draft + save/delete for the published-service detail modal only.
 * List data stays in {@link useMyCommunityMcp}; this hook invalidates that query on success.
 */
export function usePublishedServiceDetailEdit(
  service: CommunityMcpCard | null,
  open: boolean
) {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();

  const [draft, setDraft] = useState<PublishedServiceEditDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!open || !service?.communityId) {
      setDraft(null);
      return;
    }
    setDraft(draftFromItem(service));
  }, [open, service]);

  const updateDraft = useCallback((patch: Partial<PublishedServiceEditDraft>) => {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
  }, []);

  const addDraftTag = useCallback((tag: string) => {
    const next = tag.trim();
    if (!next) return;
    setDraft((prev) => {
      if (!prev || prev.tags.includes(next)) return prev;
      return { ...prev, tags: [...prev.tags, next] };
    });
  }, []);

  const removeDraftTag = useCallback((index: number) => {
    setDraft((prev) =>
      prev
        ? { ...prev, tags: prev.tags.filter((_, idx) => idx !== index) }
        : prev
    );
  }, []);

  const save = useCallback(async () => {
    if (!draft) return false;
    setSaving(true);
    try {
      await updateCommunityMcpTool({
        community_id: draft.communityId,
        name: draft.name.trim(),
        description: draft.description.trim(),
        version: draft.version.trim(),
        tags: draft.tags,
      });
      message.success(t("mcpTools.service.saveSuccess"));
      queryClient.invalidateQueries({
        queryKey: MCP_TOOLS_QUERY_KEYS.myCommunity,
      });
      return true;
    } catch (error) {
      log.error("[usePublishedServiceDetailEdit] Save failed", { error });
      message.error(t("mcpTools.service.saveFailed"));
      return false;
    } finally {
      setSaving(false);
    }
  }, [draft, message, queryClient, t]);

  const remove = useCallback(
    async (communityId: number): Promise<boolean> => {
      setDeleting(true);
      try {
        await deleteCommunityMcpTool(communityId);
        message.success(t("mcpTools.community.mine.deleteSuccess"));
        queryClient.invalidateQueries({
          queryKey: MCP_TOOLS_QUERY_KEYS.myCommunity,
        });
        return true;
      } catch (error) {
        log.error("[usePublishedServiceDetailEdit] Delete failed", { error });
        message.error(t("mcpTools.community.mine.deleteFailed"));
        return false;
      } finally {
        setDeleting(false);
      }
    },
    [message, queryClient, t]
  );

  return {
    draft,
    saving,
    deleting,
    updateDraft,
    addDraftTag,
    removeDraftTag,
    save,
    remove,
  };
}
