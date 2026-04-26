import { useEffect, useState } from "react";
import { Form, Input, Modal } from "antd";
import { useTranslation } from "react-i18next";
import type { McpServiceItem } from "@/types/mcpTools";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import TagEditor from "./shared/TagEditor";

export interface PublishOverride {
  name: string;
  description: string;
  version: string;
  tags: string[];
}

interface PublishConfirmModalProps {
  open: boolean;
  source: McpServiceItem | null;
  publishing: boolean;
  onCancel: () => void;
  onConfirm: (override: PublishOverride) => Promise<boolean | void> | void;
}

/**
 * Confirmation step for "publish to community". Owns its own draft so the
 * source service is never mutated; only the published copy reflects edits.
 */
export default function PublishConfirmModal({
  open,
  source,
  publishing,
  onCancel,
  onConfirm,
}: PublishConfirmModalProps) {
  const { t } = useTranslation("common");
  const rules = useMcpFormRules();
  const [form] = Form.useForm();
  const [draft, setDraft] = useState<PublishOverride>({
    name: "",
    description: "",
    version: "",
    tags: [],
  });

  useEffect(() => {
    if (!open || !source) return;
    const next: PublishOverride = {
      name: source.name,
      description: source.description,
      version: source.version || "",
      tags: source.tags || [],
    };
    setDraft(next);
    form.setFieldsValue(next);
  }, [open, source, form]);

  const patch = (partial: Partial<PublishOverride>) => {
    setDraft((prev) => ({ ...prev, ...partial }));
  };

  const handleOk = async () => {
    try {
      await form.validateFields();
    } catch {
      return;
    }
    await onConfirm({
      name: draft.name.trim(),
      description: draft.description,
      version: draft.version.trim(),
      tags: draft.tags,
    });
  };

  return (
    <Modal
      open={open}
      title={t("mcpTools.publish.confirmTitle")}
      onCancel={onCancel}
      onOk={handleOk}
      okText={t("mcpTools.community.publish")}
      cancelText={t("common.cancel")}
      confirmLoading={publishing}
      width={720}
      centered
      destroyOnHidden
    >
      <p className="mb-3 text-xs text-slate-500">
        {t("mcpTools.publish.confirmHint")}
      </p>
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        className="space-y-3"
      >
        <Form.Item
          label={t("mcpTools.detail.name")}
          name="name"
          rules={rules.name}
        >
          <Input
            value={draft.name}
            onChange={(event) => {
              patch({ name: event.target.value });
              form.setFieldValue("name", event.target.value);
            }}
            className="rounded-md"
          />
        </Form.Item>

        <Form.Item
          label={t("mcpTools.detail.description")}
          name="description"
          rules={rules.description}
        >
          <Input.TextArea
            value={draft.description}
            onChange={(event) => {
              patch({ description: event.target.value });
              form.setFieldValue("description", event.target.value);
            }}
            autoSize={{ minRows: 2, maxRows: 12 }}
            className="rounded-md"
          />
        </Form.Item>

        <Form.Item
          label={t("mcpTools.detail.version")}
          name="version"
          rules={rules.version}
        >
          <Input
            value={draft.version}
            onChange={(event) => {
              patch({ version: event.target.value });
              form.setFieldValue("version", event.target.value);
            }}
            placeholder="1.0.0"
            className="rounded-md"
          />
        </Form.Item>

        <TagEditor
          title={t("mcpTools.detail.tags")}
          tags={draft.tags}
          onAddTag={(tag) => {
            const next = (tag || "").trim();
            if (!next || draft.tags.includes(next)) return;
            patch({ tags: [...draft.tags, next] });
          }}
          onRemoveTag={(index) =>
            patch({ tags: draft.tags.filter((_, i) => i !== index) })
          }
          removeAriaKey="mcpTools.detail.removeTagAria"
        />
      </Form>
    </Modal>
  );
}
