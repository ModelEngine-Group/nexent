import { useEffect, useState } from "react";
import { App, Button, Form, Input, Modal } from "antd";
import { useTranslation } from "react-i18next";
import {
  MCP_TOOLS_MODAL_WRAP_CLASS,
  mcpToolsModalChromeStyles,
} from "@/const/mcpTools";
import type { CommunityMcpCard } from "@/types/mcpTools";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import { usePublishedServiceDetailEdit } from "@/hooks/mcpTools/usePublishedServiceDetailEdit";
import {
  extractRegistryLinks,
  formatRegistryDate,
  getTransportLabelKey,
  toPrettyRegistryJson,
} from "@/lib/mcpTools";
import RegistryStatusBadge from "./shared/StatusBadge";
import JsonPreviewModal from "./shared/JsonPreviewModal";
import TagEditor from "./shared/TagEditor";

const sectionCard =
  "rounded-xl border border-slate-200/90 bg-white p-4 shadow-sm";

interface PublishedServiceDetailModalProps {
  open: boolean;
  service: CommunityMcpCard | null;
  onClose: () => void;
}

/**
 * Editable detail for the "my published" tab. Read-only block mirrors
 * {@link McpCommunityDetailModal} (URL, type, status, times, links, JSON);
 * name / description / version / tags stay editable and persist via the
 * parent draft + save.
 */
export default function PublishedServiceDetailModal({
  open,
  service,
  onClose,
}: PublishedServiceDetailModalProps) {
  const { t } = useTranslation("common");
  const { modal } = App.useApp();
  const rules = useMcpFormRules();
  const [form] = Form.useForm();
  const edit = usePublishedServiceDetailEdit(service, open);
  const { draft, saving, deleting, updateDraft, addDraftTag, removeDraftTag } =
    edit;
  const [showServerJsonModal, setShowServerJsonModal] = useState(false);
  const [showConfigJsonModal, setShowConfigJsonModal] = useState(false);

  const { websiteUrl, repositoryUrl } = extractRegistryLinks(
    (service?.registryJson || undefined) as Record<string, unknown> | undefined
  );
  const serverJsonPretty = toPrettyRegistryJson(
    (service?.registryJson || undefined) as Record<string, unknown> | undefined
  );
  const configJsonPretty = toPrettyRegistryJson(
    (service?.configJson || undefined) as Record<string, unknown> | undefined
  );
  const hasServerJson = Boolean(
    service?.registryJson && Object.keys(service.registryJson).length > 0
  );
  const hasConfigJson = Boolean(
    service?.configJson && Object.keys(service.configJson).length > 0
  );

  const serverTypeText = service
    ? t(getTransportLabelKey(service.transportType))
    : "";

  useEffect(() => {
    if (!open) {
      setShowServerJsonModal(false);
      setShowConfigJsonModal(false);
    }
  }, [open]);

  useEffect(() => {
    if (!open || !draft) return;
    form.setFieldsValue({
      name: draft.name,
      description: draft.description,
      version: draft.version,
    });
  }, [open, draft, form]);

  const handleSave = async () => {
    try {
      await form.validateFields();
    } catch {
      return;
    }
    const ok = await edit.save();
    if (ok) onClose();
  };

  const handleDelete = () => {
    if (!service?.communityId) return;
    modal.confirm({
      title: t("mcpTools.delete.confirmTitle"),
      content: (
        <div className="space-y-1">
          <p className="text-sm text-slate-600 break-all">{service.name}</p>
          <p className="text-xs text-slate-400">
            {t("mcpTools.delete.confirmDesc")}
          </p>
        </div>
      ),
      okText: t("mcpTools.delete.confirmOk"),
      cancelText: t("mcpTools.delete.confirmCancel"),
      okButtonProps: { danger: true },
      onOk: async () => {
        if (typeof service.communityId !== "number") return;
        const ok = await edit.remove(service.communityId);
        if (ok) onClose();
      },
    });
  };

  if (!service) return null;

  return (
    <>
      <Modal
        open={open}
        onCancel={onClose}
        footer={null}
        closable
        centered
        width={560}
        destroyOnHidden
        wrapClassName={MCP_TOOLS_MODAL_WRAP_CLASS}
        styles={mcpToolsModalChromeStyles()}
      >
        <div>
          <div className="border-b border-slate-100 bg-white px-5 py-4">
            <h2 className="text-lg font-semibold tracking-tight text-slate-900">
              {t("mcpTools.published.detailTitle")}
            </h2>
          </div>

          <Form
            form={form}
            layout="vertical"
            requiredMark={false}
            className="contents"
          >
            <div className="space-y-4 px-5 py-5">
              <div className={sectionCard}>
                <div className="grid gap-4">
                  <Form.Item
                    label={t("mcpTools.detail.name")}
                    name="name"
                    className="mb-0 text-sm text-slate-500"
                    rules={rules.name}
                  >
                    <Input
                      value={draft?.name ?? ""}
                      onChange={(event) => {
                        updateDraft({ name: event.target.value });
                        form.setFieldValue("name", event.target.value);
                      }}
                      className="mt-2 rounded-md"
                    />
                  </Form.Item>

                  <Form.Item
                    label={t("mcpTools.detail.description")}
                    name="description"
                    className="mb-0"
                    rules={rules.description}
                  >
                    <Input.TextArea
                      value={draft?.description ?? ""}
                      onChange={(event) => {
                        updateDraft({ description: event.target.value });
                        form.setFieldValue("description", event.target.value);
                      }}
                      autoSize={{ minRows: 1, maxRows: 16 }}
                      className="mt-2 rounded-md"
                    />
                  </Form.Item>
                </div>
              </div>

              <div className={sectionCard}>
                <div className="space-y-5">
                  {!service.configJson ? (
                    <div>
                      <p className="text-sm text-slate-500">
                        {t("mcpTools.detail.serverUrl")}
                      </p>
                      <p className="mt-1 break-all rounded-md border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-medium text-slate-800">
                        {service.serverUrl}
                      </p>
                    </div>
                  ) : null}

                  <div className="grid gap-3 text-sm text-slate-700">
                    <div className="flex items-center justify-between">
                      <span className="text-slate-500">
                        {t("mcpTools.detail.serverType")}
                      </span>
                      <span className="font-medium text-slate-800">
                        {serverTypeText}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-slate-500">
                        {t("mcpTools.detail.status")}
                      </span>
                      <RegistryStatusBadge status={service.status} />
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-slate-500">
                        {t("mcpTools.detail.createdAt")}
                      </span>
                      <span className="font-medium text-slate-800">
                        {formatRegistryDate(service.createdAt)}
                      </span>
                    </div>
                    {service.updatedAt ? (
                      <div className="flex items-center justify-between">
                        <span className="text-slate-500">
                          {t("mcpTools.detail.updatedAt")}
                        </span>
                        <span className="font-medium text-slate-800">
                          {formatRegistryDate(service.updatedAt)}
                        </span>
                      </div>
                    ) : null}
                    {websiteUrl ? (
                      <div className="flex items-center justify-between gap-4">
                        <span className="text-slate-500">
                          {t("mcpTools.detail.website")}
                        </span>
                        <a
                          href={websiteUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="max-w-[70%] truncate font-medium text-sky-700 hover:text-sky-800"
                        >
                          {websiteUrl}
                        </a>
                      </div>
                    ) : null}
                    {repositoryUrl ? (
                      <div className="flex items-center justify-between gap-4">
                        <span className="text-slate-500">
                          {t("mcpTools.detail.repository")}
                        </span>
                        <a
                          href={repositoryUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="max-w-[70%] truncate font-medium text-sky-700 hover:text-sky-800"
                        >
                          {repositoryUrl}
                        </a>
                      </div>
                    ) : null}
                  </div>

                  <div className="flex items-center justify-between gap-3 border-t border-slate-100 pt-4">
                    <span className="text-sm text-slate-500">
                      {t("mcpTools.detail.tools")}
                    </span>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      {hasServerJson ? (
                        <Button
                          size="small"
                          className="rounded-md"
                          autoInsertSpace={false}
                          onClick={() => setShowServerJsonModal(true)}
                        >
                          {t("mcpTools.community.viewServerJson")}
                        </Button>
                      ) : null}
                      {hasConfigJson ? (
                        <Button
                          size="small"
                          className="rounded-md"
                          autoInsertSpace={false}
                          onClick={() => setShowConfigJsonModal(true)}
                        >
                          {t("mcpTools.detail.viewConfigJson")}
                        </Button>
                      ) : null}
                    </div>
                  </div>
                </div>
              </div>

              <div className={sectionCard}>
                <Form.Item
                  className="mb-0"
                  label={t("mcpTools.detail.version")}
                  name="version"
                  rules={rules.version}
                >
                  <Input
                    value={draft?.version ?? ""}
                    onChange={(event) => {
                      updateDraft({ version: event.target.value });
                      form.setFieldValue("version", event.target.value);
                    }}
                    placeholder="1.0.0"
                    className="mt-2 rounded-md"
                  />
                </Form.Item>
                <div className="mt-4">
                  <TagEditor
                    title={t("mcpTools.detail.tags")}
                    tags={draft?.tags ?? []}
                    onAddTag={(tag) => addDraftTag((tag || "").trim())}
                    onRemoveTag={removeDraftTag}
                    removeAriaKey="mcpTools.detail.removeTagAria"
                  />
                </div>
              </div>
            </div>
          </Form>

          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-200/80 bg-white px-5 py-3.5">
            <Button
              danger
              loading={deleting}
              disabled={!service.communityId}
              onClick={handleDelete}
            >
              {t("common.delete")}
            </Button>
            <Button type="primary" loading={saving} onClick={handleSave}>
              {t("common.save")}
            </Button>
          </div>
        </div>
      </Modal>

      <JsonPreviewModal
        open={showServerJsonModal && hasServerJson}
        title={t("mcpTools.community.serverJsonTitle", { name: service.name })}
        json={serverJsonPretty}
        onCancel={() => setShowServerJsonModal(false)}
      />

      <JsonPreviewModal
        open={showConfigJsonModal && hasConfigJson}
        title={t("mcpTools.detail.configJsonTitle", { name: service.name })}
        json={configJsonPretty}
        onCancel={() => setShowConfigJsonModal(false)}
      />
    </>
  );
}
