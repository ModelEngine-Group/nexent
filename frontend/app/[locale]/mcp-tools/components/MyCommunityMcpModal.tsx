import { useEffect } from "react";
import { Button, Empty, Form, Input, Modal, Popconfirm, Spin, Tag } from "antd";
import { useTranslation } from "react-i18next";
import type { CommunityMcpCard } from "@/types/mcpTools";
import { formatRegistryVersion } from "@/lib/mcpTools";
import { useMyCommunityMcp } from "@/hooks/mcpTools/useMyCommunityMcp";

interface MyCommunityMcpModalProps {
  open: boolean;
  onClose: () => void;
}

export default function MyCommunityMcpModal({
  open,
  onClose,
}: MyCommunityMcpModalProps) {
  const { t } = useTranslation("common");
  const [editForm] = Form.useForm();
  const {
    loading,
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
  } = useMyCommunityMcp(open);

  useEffect(() => {
    if (!editDraft) {
      editForm.resetFields();
      return;
    }
    editForm.setFieldsValue({
      name: editDraft.name,
      description: editDraft.description,
      version: editDraft.version,
    });
  }, [editDraft, editForm]);

  const handleSave = async () => {
    try {
      await editForm.validateFields();
    } catch {
      return;
    }
    await saveEdit();
  };

  return (
    <>
      <Modal
        open={open}
        onCancel={onClose}
        footer={null}
        width={1000}
        centered
        title={t("mcpTools.community.mine.title")}
      >
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
                <MyCommunityItem
                  key={`${item.communityId}-${item.name}`}
                  item={item}
                  deleting={deletingId === item.communityId}
                  onEdit={() => startEditing(item)}
                  onDelete={() => item.communityId && remove(item.communityId)}
                />
              ))}
            </div>
          )}
        </div>
      </Modal>

      <Modal
        open={Boolean(editDraft)}
        width={900}
        onCancel={cancelEditing}
        onOk={handleSave}
        confirmLoading={saving}
        title={t("mcpTools.community.mine.edit")}
        okText={t("common.save")}
        cancelText={t("common.cancel")}
      >
        {editDraft ? (
          <Form
            form={editForm}
            layout="vertical"
            requiredMark={false}
            className="space-y-3"
          >
            <Form.Item
              label={t("mcpTools.detail.name")}
              name="name"
              className="mb-0 text-xs text-slate-500"
              rules={[
                {
                  required: true,
                  whitespace: true,
                  message: t("mcpTools.add.validate.nameRequired"),
                },
                {
                  type: "string",
                  max: 100,
                  message: t("mcpTools.add.validate.nameMaxLength"),
                },
              ]}
            >
              <Input
                value={editDraft.name}
                onChange={(event) => updateDraft({ name: event.target.value })}
                className="mt-1 rounded-xl"
              />
            </Form.Item>

            <Form.Item
              name="description"
              className="mb-0 text-xs text-slate-500"
              rules={[
                {
                  type: "string",
                  max: 5000,
                  message: t("mcpTools.add.validate.descriptionMaxLength"),
                },
              ]}
            >
              <Input.TextArea
                value={editDraft.description}
                onChange={(event) => {
                  updateDraft({ description: event.target.value });
                  editForm.setFieldValue("description", event.target.value);
                }}
                autoSize={{ minRows: 1, maxRows: 24 }}
                className="mt-1 rounded-xl"
                placeholder={t("mcpTools.detail.description")}
              />
            </Form.Item>

            <Form.Item
              label={t("mcpTools.detail.version")}
              name="version"
              className="mb-0 text-xs text-slate-500"
              rules={[
                {
                  validator: async (_rule, value) => {
                    const text = String(value || "").trim();
                    if (!text) return;
                    if (text.length > 100)
                      throw new Error(
                        t("mcpTools.community.mine.versionMaxLength")
                      );
                    if (!/^\d+(?:\.\d+){0,2}$/.test(text))
                      throw new Error(
                        t("mcpTools.community.mine.versionFormat")
                      );
                  },
                },
              ]}
            >
              <Input
                value={editDraft.version}
                onChange={(event) =>
                  updateDraft({ version: event.target.value })
                }
                className="mt-1 rounded-xl"
              />
            </Form.Item>

            <div className="block text-xs text-slate-500">
              {t("mcpTools.detail.tags")}
              <div className="mt-2 flex flex-wrap gap-2">
                {editDraft.tags.map((tag, index) => (
                  <span
                    key={`${tag}-${index}`}
                    className="relative inline-flex"
                  >
                    <Tag className="rounded-full px-3 py-1 m-0 leading-none">
                      {tag}
                    </Tag>
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
                  value={editDraft.tagInput}
                  onChange={(event) =>
                    updateDraft({ tagInput: event.target.value })
                  }
                  onPressEnter={addDraftTag}
                  onBlur={addDraftTag}
                  placeholder={t("mcpTools.addModal.tagInputPlaceholder")}
                  className="w-40 rounded-full"
                />
              </div>
            </div>
          </Form>
        ) : null}
      </Modal>
    </>
  );
}

interface MyCommunityItemProps {
  item: CommunityMcpCard;
  deleting: boolean;
  onEdit: () => void;
  onDelete: () => void;
}

function MyCommunityItem({
  item,
  deleting,
  onEdit,
  onDelete,
}: MyCommunityItemProps) {
  const { t } = useTranslation("common");

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="break-all text-base font-semibold text-slate-900">
            {item.name}
          </h3>
          <p className="mt-1 text-xs text-slate-500">
            {formatRegistryVersion(item.version || "")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button size="small" className="rounded-full" onClick={onEdit}>
            {t("mcpTools.community.mine.edit")}
          </Button>
          <Popconfirm
            title={t("mcpTools.delete.confirmTitle")}
            description={t("mcpTools.delete.confirmDesc")}
            okText={t("mcpTools.delete.confirmOk")}
            cancelText={t("mcpTools.delete.confirmCancel")}
            onConfirm={onDelete}
          >
            <Button
              size="small"
              danger
              className="rounded-full"
              loading={deleting}
              disabled={!item.communityId}
            >
              {t("mcpTools.community.mine.delete")}
            </Button>
          </Popconfirm>
        </div>
      </div>

      <p className="mt-3 text-sm text-slate-600 break-all">
        {item.description || "-"}
      </p>

      <div className="mt-3 grid grid-cols-1 gap-2 text-xs text-slate-500 md:grid-cols-2">
        <div className="break-all">
          {t("mcpTools.detail.serverType")}: {item.transportType}
        </div>
        <div className="break-all">
          {t("mcpTools.detail.serverUrl")}: {item.serverUrl || "-"}
        </div>
      </div>

      {(item.tags || []).length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {(item.tags || []).map((tag) => (
            <span
              key={`${item.communityId}-${tag}`}
              className="rounded-full bg-sky-100 px-2.5 py-1 text-xs font-medium text-sky-700"
            >
              {tag}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
