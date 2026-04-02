import { useEffect, useMemo, useState } from "react";
import { Button, Empty, Input, Modal, Popconfirm, Spin, Tag } from "antd";
import type { CommunityMcpCard } from "@/types/mcpTools";
import {
  deleteCommunityMcpTool,
  listMyCommunityMcpTools,
  updateCommunityMcpTool,
} from "@/services/mcpToolsService";
import { formatRegistryVersion } from "@/lib/mcpTools";
import McpDescriptionField from "./McpDescriptionField";

type Props = {
  open: boolean;
  onClose: () => void;
  t: (key: string, params?: Record<string, unknown>) => string;
};

type Draft = {
  communityId: number;
  name: string;
  description: string;
  version: string;
  tags: string[];
  tagInputValue: string;
};

export default function MyCommunityMcpModal({ open, onClose, t }: Props) {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<CommunityMcpCard[]>([]);
  const [search, setSearch] = useState("");
  const [editDraft, setEditDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const loadMine = async () => {
    setLoading(true);
    try {
      const result = await listMyCommunityMcpTools();
      setItems(result.data.items || []);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    void loadMine();
  }, [open]);

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

  const openEdit = (item: CommunityMcpCard) => {
    if (!item.communityId) return;
    setEditDraft({
      communityId: item.communityId,
      name: item.name || "",
      description: item.description || "",
      version: item.version || "",
      tags: item.tags || [],
      tagInputValue: "",
    });
  };

  const addDraftTag = () => {
    if (!editDraft) return;
    const nextTag = editDraft.tagInputValue.trim();
    if (!nextTag) return;
    if (editDraft.tags.includes(nextTag)) {
      setEditDraft({ ...editDraft, tagInputValue: "" });
      return;
    }
    setEditDraft({
      ...editDraft,
      tags: [...editDraft.tags, nextTag],
      tagInputValue: "",
    });
  };

  const removeDraftTag = (index: number) => {
    if (!editDraft) return;
    setEditDraft({
      ...editDraft,
      tags: editDraft.tags.filter((_, idx) => idx !== index),
    });
  };

  const saveEdit = async () => {
    if (!editDraft) return;
    setSaving(true);
    try {
      await updateCommunityMcpTool({
        community_id: editDraft.communityId,
        name: editDraft.name.trim(),
        description: editDraft.description.trim(),
        version: editDraft.version.trim(),
        tags: editDraft.tags,
      });
      setEditDraft(null);
      await loadMine();
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (communityId: number) => {
    setDeletingId(communityId);
    try {
      await deleteCommunityMcpTool(communityId);
      await loadMine();
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <>
      <Modal open={open} onCancel={onClose} footer={null} width={1000} centered title={t("mcpTools.community.mine.title")}>
        <div className="space-y-4">
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("mcpTools.community.searchPlaceholder")}
            className="rounded-xl"
          />

          {loading ? (
            <div className="py-10 text-center">
              <Spin />
            </div>
          ) : filteredItems.length === 0 ? (
            <Empty description={t("mcpTools.community.mine.empty")} />
          ) : (
            <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
              {filteredItems.map((item) => (
                <div key={`${item.communityId}-${item.name}`} className="rounded-2xl border border-slate-200 bg-white p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="break-all text-base font-semibold text-slate-900">{item.name}</h3>
                      <p className="mt-1 text-xs text-slate-500">{formatRegistryVersion(item.version || "")}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button size="small" className="rounded-full" onClick={() => openEdit(item)}>
                        {t("mcpTools.community.mine.edit")}
                      </Button>
                      <Popconfirm
                        title={t("mcpTools.delete.confirmTitle")}
                        description={t("mcpTools.delete.confirmDesc")}
                        okText={t("mcpTools.delete.confirmOk")}
                        cancelText={t("mcpTools.delete.confirmCancel")}
                        onConfirm={() => item.communityId && handleDelete(item.communityId)}
                      >
                        <Button
                          size="small"
                          danger
                          className="rounded-full"
                          loading={deletingId === item.communityId}
                          disabled={!item.communityId}
                        >
                          {t("mcpTools.community.mine.delete")}
                        </Button>
                      </Popconfirm>
                    </div>
                  </div>

                  <p className="mt-3 text-sm text-slate-600 break-all">{item.description || "-"}</p>

                  <div className="mt-3 grid grid-cols-1 gap-2 text-xs text-slate-500 md:grid-cols-2">
                    <div className="break-all">{t("mcpTools.detail.serverType")}: {item.transportType}</div>
                    <div className="break-all">{t("mcpTools.detail.serverUrl")}: {item.serverUrl || "-"}</div>
                  </div>

                  {(item.tags || []).length > 0 ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {(item.tags || []).map((tag) => (
                        <span key={`${item.communityId}-${tag}`} className="rounded-full bg-sky-100 px-2.5 py-1 text-xs font-medium text-sky-700">
                          {tag}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>
      </Modal>

      <Modal
        open={Boolean(editDraft)}
        width={900}
        onCancel={() => setEditDraft(null)}
        onOk={() => {
          void saveEdit();
        }}
        confirmLoading={saving}
        title={t("mcpTools.community.mine.edit")}
        okText={t("common.save")}
        cancelText={t("common.cancel")}
      >
        {editDraft ? (
          <div className="space-y-3">
            <label className="block text-xs text-slate-500">
              {t("mcpTools.detail.name")}
              <Input
                value={editDraft.name}
                onChange={(event) => setEditDraft({ ...editDraft, name: event.target.value })}
                className="mt-1 rounded-xl"
              />
            </label>
            <div className="block text-xs text-slate-500">
              <McpDescriptionField
                label={t("mcpTools.detail.description")}
                value={editDraft.description}
                onChange={(value) => setEditDraft({ ...editDraft, description: value })}
                t={(key, params) => String(t(key, params as any))}
                minRows={10}
                maxRows={24}
                toggleMinChars={160}
                toggleMinLines={5}
                wrapperClassName="text-xs text-slate-500"
              />
            </div>
            <label className="block text-xs text-slate-500">
              {t("mcpTools.detail.version")}
              <Input
                value={editDraft.version}
                onChange={(event) => setEditDraft({ ...editDraft, version: event.target.value })}
                className="mt-1 rounded-xl"
              />
            </label>
            <label className="block text-xs text-slate-500">
              {t("mcpTools.detail.tags")}
              <div className="mt-2 flex flex-wrap gap-2">
                {editDraft.tags.map((tag, index) => (
                  <span key={`${tag}-${index}`} className="relative inline-flex">
                    <Tag className="rounded-full px-3 py-1 m-0 leading-none">{tag}</Tag>
                    <button
                      type="button"
                      onClick={() => removeDraftTag(index)}
                      className="absolute top-0 right-0 -translate-y-1/2 translate-x-1/2 flex h-4 w-4 items-center justify-center rounded-full bg-slate-200 text-[10px] text-slate-500 transition hover:bg-slate-300 hover:text-slate-700"
                      aria-label={t("mcpTools.detail.removeTagAria", { tag })}
                    >
                      x
                    </button>
                  </span>
                ))}
                <Input
                  size="small"
                  value={editDraft.tagInputValue}
                  onChange={(event) => setEditDraft({ ...editDraft, tagInputValue: event.target.value })}
                  onPressEnter={addDraftTag}
                  onBlur={addDraftTag}
                  placeholder={t("mcpTools.addModal.tagInputPlaceholder")}
                  className="w-40 rounded-full"
                />
              </div>
            </label>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
