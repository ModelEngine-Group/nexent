"use client";

import { useCallback, useMemo, useState } from "react";
import { App } from "antd";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import log from "@/lib/logger";
import {
  deleteCommunityMcpTool,
  listMyCommunityMcpTools,
  updateCommunityMcpTool,
} from "@/services/mcpToolsService";
import type { CommunityMcpCard } from "@/types/mcpTools";
import { MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";

export interface MyCommunityEditDraft {
  communityId: number;
  name: string;
  description: string;
  version: string;
  tags: string[];
  tagInput: string;
}

const draftFromItem = (item: CommunityMcpCard): MyCommunityEditDraft | null => {
  if (!item.communityId) return null;
  return {
    communityId: item.communityId,
    name: item.name || "",
    description: item.description || "",
    version: item.version || "",
    tags: item.tags || [],
    tagInput: "",
  };
};

/**
 * Manages the "My community MCP" drawer: loading the list, in-modal edit draft
 * and delete flow.
 */
export function useMyCommunityMcp(enabled: boolean) {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();

  const [search, setSearch] = useState("");
  const [editDraft, setEditDraft] = useState<MyCommunityEditDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const query = useQuery({
    queryKey: [...MCP_TOOLS_QUERY_KEYS.myCommunity],
    enabled,
    queryFn: async () => {
      const result = await listMyCommunityMcpTools();
      return result.data.items;
    },
    staleTime: 30_000,
  });

  const items: CommunityMcpCard[] = useMemo(
    () => query.data ?? [],
    [query.data]
  );

  const filteredItems = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return items;
    return items.filter((item) => {
      const tags = (item.tags || []).join(",").toLowerCase();
      return (
        (item.name || "").toLowerCase().includes(keyword) ||
        (item.description || "").toLowerCase().includes(keyword) ||
        tags.includes(keyword)
      );
    });
  }, [items, search]);

  const startEditing = useCallback((item: CommunityMcpCard) => {
    setEditDraft(draftFromItem(item));
  }, []);

  const cancelEditing = useCallback(() => {
    setEditDraft(null);
  }, []);

  const updateDraft = useCallback((patch: Partial<MyCommunityEditDraft>) => {
    setEditDraft((prev) => (prev ? { ...prev, ...patch } : prev));
  }, []);

  const addDraftTag = useCallback(() => {
    setEditDraft((prev) => {
      if (!prev) return prev;
      const nextTag = prev.tagInput.trim();
      if (!nextTag) return { ...prev, tagInput: "" };
      if (prev.tags.includes(nextTag)) return { ...prev, tagInput: "" };
      return { ...prev, tags: [...prev.tags, nextTag], tagInput: "" };
    });
  }, []);

  const removeDraftTag = useCallback((index: number) => {
    setEditDraft((prev) =>
      prev
        ? { ...prev, tags: prev.tags.filter((_, idx) => idx !== index) }
        : prev
    );
  }, []);

  const saveEdit = useCallback(async () => {
    if (!editDraft) return false;
    setSaving(true);
    try {
      await updateCommunityMcpTool({
        community_id: editDraft.communityId,
        name: editDraft.name.trim(),
        description: editDraft.description.trim(),
        version: editDraft.version.trim(),
        tags: editDraft.tags,
      });
      message.success(t("mcpTools.community.mine.saveSuccess"));
      setEditDraft(null);
      queryClient.invalidateQueries({
        queryKey: MCP_TOOLS_QUERY_KEYS.myCommunity,
      });
      return true;
    } catch (error) {
      log.error("[useMyCommunityMcp] Save failed", { error });
      message.error(t("mcpTools.community.mine.saveFailed"));
      return false;
    } finally {
      setSaving(false);
    }
  }, [editDraft, message, queryClient, t]);

  const remove = useCallback(
    async (communityId: number) => {
      setDeletingId(communityId);
      try {
        await deleteCommunityMcpTool(communityId);
        message.success(t("mcpTools.community.mine.deleteSuccess"));
        queryClient.invalidateQueries({
          queryKey: MCP_TOOLS_QUERY_KEYS.myCommunity,
        });
      } catch (error) {
        log.error("[useMyCommunityMcp] Delete failed", { error });
        message.error(t("mcpTools.community.mine.deleteFailed"));
      } finally {
        setDeletingId(null);
      }
    },
    [message, queryClient, t]
  );

  return {
    loading: query.isLoading,
    items,
    filteredItems,
    search,
    setSearch,
    editDraft,
    startEditing,
    cancelEditing,
    updateDraft,
    addDraftTag,
    removeDraftTag,
    saveEdit,
    saving,
    remove,
    deletingId,
  };
}
