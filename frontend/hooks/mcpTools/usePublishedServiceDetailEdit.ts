"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
  const draftRef = useRef<PublishedServiceEditDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [tagSaving, setTagSaving] = useState(false);

  useEffect(() => {
    if (!open || !service?.communityId) {
      setDraft(null);
      draftRef.current = null;
      return;
    }
    const newDraft = draftFromItem(service);
    setDraft(newDraft);
    draftRef.current = newDraft;
  }, [open, service]);

  const updateDraft = useCallback((patch: Partial<PublishedServiceEditDraft>) => {
    setDraft((prev) => {
      const updated = prev ? { ...prev, ...patch } : prev;
      draftRef.current = updated;
      return updated;
    });
  }, []);

  const updateTagsToServer = useCallback(async (newTags: string[]) => {
    const currentDraft = draftRef.current;
    if (!currentDraft) return;
    setTagSaving(true);
    try {
      await updateCommunityMcpTool({
        community_id: currentDraft.communityId,
        name: currentDraft.name.trim(),
        description: currentDraft.description.trim(),
        version: currentDraft.version.trim(),
        tags: newTags,
      });
      // Update local state
      setDraft((prev) => {
        const updated = prev ? { ...prev, tags: newTags } : prev;
        draftRef.current = updated;
        return updated;
      });
      queryClient.invalidateQueries({
        queryKey: MCP_TOOLS_QUERY_KEYS.myCommunity,
      });
    } catch (error) {
      log.error("[usePublishedServiceDetailEdit] Update tags failed", { error });
      message.error(t("mcpTools.service.saveFailed"));
      // Revert local state on error
      setDraft((prev) => {
        const reverted = prev ? { ...prev, tags: currentDraft.tags } : prev;
        draftRef.current = reverted;
        return reverted;
      });
    } finally {
      setTagSaving(false);
    }
  }, [message, queryClient, t]);

  const addDraftTag = useCallback((tag: string) => {
    const next = tag.trim();
    if (!next) return;
    const currentDraft = draftRef.current;
    if (!currentDraft) return;
    if (currentDraft.tags.includes(next)) return;
    updateTagsToServer([...currentDraft.tags, next]);
  }, [updateTagsToServer]);

  const removeDraftTag = useCallback((index: number) => {
    const currentDraft = draftRef.current;
    if (!currentDraft) return;
    const newTags = currentDraft.tags.filter((_, idx) => idx !== index);
    updateTagsToServer(newTags);
  }, [updateTagsToServer]);

  const save = useCallback(async () => {
    const currentDraft = draftRef.current;
    if (!currentDraft) return false;
    setSaving(true);
    try {
      await updateCommunityMcpTool({
        community_id: currentDraft.communityId,
        name: currentDraft.name.trim(),
        description: currentDraft.description.trim(),
        version: currentDraft.version.trim(),
        tags: currentDraft.tags,
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
  }, [message, queryClient, t]);

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
    tagSaving,
    updateDraft,
    addDraftTag,
    removeDraftTag,
    save,
    remove,
  };
}
