import { useState } from "react";
import { Button, Form, Input, Select } from "antd";
import { useTranslation } from "react-i18next";
import { McpTransportType } from "@/const/mcpTools";
import type { LocalAddMcpDraft } from "@/types/mcpTools";
import { useMcpAddLocal } from "@/hooks/mcpTools/useMcpAddLocal";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import ContainerPortField from "../../shared/ContainerPortField";
import TagEditor from "../../shared/TagEditor";

const createInitialDraft = (): LocalAddMcpDraft => ({
  name: "",
  description: "",
  transportType: McpTransportType.URL,
  serverUrl: "",
  authorizationToken: "",
  customHeaders: "",
  containerConfigJson: "",
  containerPort: undefined,
  tags: [],
});

interface AddMcpServiceLocalSectionProps {
  active: boolean;
  onAdded: () => void;
}

export default function AddMcpServiceLocalSection({
  active,
  onAdded,
}: AddMcpServiceLocalSectionProps) {
  const { t } = useTranslation("common");
  const rules = useMcpFormRules();
  const [form] = Form.useForm();
  const [draft, setDraft] = useState<LocalAddMcpDraft>(() => createInitialDraft());
  const { submit, submitting } = useMcpAddLocal({
    onSuccess: () => {
      setDraft(createInitialDraft());
      form.resetFields();
      onAdded();
    },
  });

  const patchDraft = (patch: Partial<LocalAddMcpDraft>) => {
    setDraft((prev) => ({ ...prev, ...patch }));
  };

  // Syncs external `draft` into AntD Form state so validation sees the value.
  const bindField = <K extends keyof LocalAddMcpDraft>(key: K) => ({
    value: draft[key],
    onChange: (eventOrValue: unknown) => {
      const next =
        eventOrValue &&
        typeof eventOrValue === "object" &&
        "target" in (eventOrValue as Record<string, unknown>)
          ? (eventOrValue as { target: { value: LocalAddMcpDraft[K] } }).target
              .value
          : (eventOrValue as LocalAddMcpDraft[K]);
      patchDraft({ [key]: next } as Partial<LocalAddMcpDraft>);
      form.setFieldValue(key as string, next);
    },
  });

  const addTag = (tag: string) => {
    const next = (tag || "").trim();
    if (!next || draft.tags.includes(next)) return;
    patchDraft({ tags: [...draft.tags, next] });
  };

  const removeTag = (index: number) => {
    patchDraft({ tags: draft.tags.filter((_, i) => i !== index) });
  };

  const handleSubmit = async () => {
    try {
      await form.validateFields();
    } catch {
      return;
    }
    await submit(draft);
  };

  if (!active) return null;

  const isHttpLike = draft.transportType !== McpTransportType.CONTAINER;

  return (
    <div className="flex h-full flex-col">
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        className="flex-1 space-y-5 px-6 py-5"
      >
        <div>
          <label className="mb-1 block text-sm font-normal text-slate-500">
            {t("mcpTools.addModal.name")}
          </label>
          <Form.Item
            name="name"
            rules={rules.name}
            className="mb-0"
          >
            <Input {...bindField("name")} className="w-full rounded-md" />
          </Form.Item>
        </div>

        <div>
          <label className="mb-1 block text-sm font-normal text-slate-500">
            {t("mcpTools.addModal.description")}
          </label>
          <Form.Item
            name="description"
            rules={rules.description}
            className="mb-0"
          >
            <Input.TextArea
              {...bindField("description")}
              autoSize={{ minRows: 1, maxRows: 20 }}
              className="w-full rounded-md"
            />
          </Form.Item>
        </div>

        <div>
          <label className="mb-1 block text-sm font-normal text-slate-500">
            {t("mcpTools.addModal.serverType")}
          </label>
          <Form.Item
            name="transportType"
            initialValue={draft.transportType}
            rules={rules.transportType}
            className="mb-0"
          >
            <Select
              value={draft.transportType}
              onChange={(value: McpTransportType) => {
                patchDraft({ transportType: value });
                form.setFieldValue("transportType", value);
              }}
              className="w-full"
              popupMatchSelectWidth={false}
              options={[
                {
                  label: t("mcpTools.serverType.url"),
                  value: McpTransportType.URL,
                },
                {
                  label: t("mcpTools.serverType.container"),
                  value: McpTransportType.CONTAINER,
                },
              ]}
            />
          </Form.Item>
        </div>

        {isHttpLike ? (
          <>
            <div>
              <label className="mb-1 block text-sm font-normal text-slate-500">
                {t("mcpTools.addModal.serverUrl")}
              </label>
              <Form.Item
                name="serverUrl"
                rules={rules.httpUrl}
                className="mb-0"
              >
                <Input
                  {...bindField("serverUrl")}
                  className="w-full rounded-md"
                  placeholder={t("mcpTools.addModal.serverUrl")}
                />
              </Form.Item>
            </div>
            <div>
              <label className="mb-1 block text-sm font-normal text-slate-500">
                {t("mcpTools.addModal.bearerTokenOptional")}
              </label>
              <Form.Item
                name="authorizationToken"
                rules={rules.authToken}
                className="mb-0"
              >
                <Input
                  {...bindField("authorizationToken")}
                  className="w-full rounded-md"
                  placeholder={t("mcpTools.addModal.bearerTokenPlaceholder")}
                />
              </Form.Item>
            </div>
            <div>
              <label className="mb-1 block text-sm font-normal text-slate-500">
                {t("mcpTools.addModal.customHeaders")}
              </label>
              <Form.Item
                name="customHeaders"
                className="mb-0"
              >
                <Input.TextArea
                  {...bindField("customHeaders")}
                  rows={2}
                  className="w-full rounded-md"
                  placeholder={t("mcpTools.addModal.customHeadersPlaceholder")}
                />
              </Form.Item>
            </div>
          </>
        ) : (
          <div className="space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
            <div>
              <label className="mb-1 block text-sm font-normal text-slate-500">
                {t("mcpTools.addModal.containerConfig")}
              </label>
              <Form.Item
                name="containerConfigJson"
                rules={rules.containerConfig}
                className="mb-0"
              >
                <Input.TextArea
                  {...bindField("containerConfigJson")}
                  rows={5}
                  placeholder={t("mcpTools.addModal.containerConfigPlaceholder")}
                  className="w-full"
                />
              </Form.Item>
            </div>

            <Form.Item
              name="containerPort"
              rules={rules.containerPort}
              className="mb-0"
            >
              <div>
                <ContainerPortField
                  scope="local"
                  containerPort={draft.containerPort}
                  setContainerPort={(value) => {
                    patchDraft({ containerPort: value });
                    form.setFieldValue("containerPort", value);
                  }}
                />
              </div>
            </Form.Item>
          </div>
        )}

        <TagEditor
          title={t("mcpTools.addModal.tags")}
          tags={draft.tags}
          onAddTag={(tag) => addTag(tag || "")}
          onRemoveTag={removeTag}
        />
      </Form>

      <div className="sticky bottom-0 flex items-center justify-end gap-3 border-t border-slate-100 bg-white px-6 py-4">
        <Button type="primary" onClick={handleSubmit} loading={submitting}>
          {t("mcpTools.addModal.saveAndAdd")}
        </Button>
      </div>
    </div>
  );
}
