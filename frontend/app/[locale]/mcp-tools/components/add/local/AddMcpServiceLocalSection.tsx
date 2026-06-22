import { useState } from "react";
import { Alert, Button, Form, Input, Select } from "antd";
import { useTranslation } from "react-i18next";
import { McpDeploymentType, McpTransportType } from "@/const/mcpTools";
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
  const [deploymentType, setDeploymentType] = useState<McpDeploymentType>(
    McpDeploymentType.REMOTE_LINK
  );
  const { submit, submitting } = useMcpAddLocal({
    onSuccess: () => {
      setDraft(createInitialDraft());
      setDeploymentType(McpDeploymentType.REMOTE_LINK);
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

  const isHttpLike = deploymentType === McpDeploymentType.REMOTE_LINK;
  const isContainer = deploymentType === McpDeploymentType.CONTAINER;
  const isUnsupported =
    deploymentType === McpDeploymentType.API ||
    deploymentType === McpDeploymentType.LOCAL_IMAGE;

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
          <Form.Item className="mb-0">
            <Select
              value={deploymentType}
              onChange={(value: McpDeploymentType) => {
                setDeploymentType(value);
                const nextTransport =
                  value === McpDeploymentType.CONTAINER
                    ? McpTransportType.CONTAINER
                    : McpTransportType.URL;
                patchDraft({ transportType: nextTransport });
                form.setFieldValue("transportType", nextTransport);
              }}
              className="w-full"
              popupMatchSelectWidth={false}
              options={[
                {
                  label: t("mcpTools.deploymentType.remoteLink"),
                  value: McpDeploymentType.REMOTE_LINK,
                },
                {
                  label: t("mcpTools.deploymentType.container"),
                  value: McpDeploymentType.CONTAINER,
                },
                {
                  label: t("mcpTools.deploymentType.api"),
                  value: McpDeploymentType.API,
                },
                {
                  label: t("mcpTools.deploymentType.localImage"),
                  value: McpDeploymentType.LOCAL_IMAGE,
                },
              ]}
            />
          </Form.Item>
        </div>

        {(deploymentType === McpDeploymentType.API ||
          deploymentType === McpDeploymentType.LOCAL_IMAGE) ? (
          <Alert
            type="info"
            showIcon
            message={t("mcpTools.addModal.unsupportedTitle")}
            description={t("mcpTools.addModal.unsupportedDescription")}
          />
        ) : null}

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
        ) : isContainer ? (
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
        ) : null}

        <TagEditor
          title={t("mcpTools.addModal.tags")}
          tags={draft.tags}
          onAddTag={(tag) => addTag(tag || "")}
          onRemoveTag={removeTag}
        />
      </Form>

      <div className="sticky bottom-0 flex items-center justify-end gap-3 border-t border-slate-100 bg-white px-6 py-4">
        <Button type="primary" onClick={handleSubmit} loading={submitting} disabled={isUnsupported}>
          {t("mcpTools.addModal.saveAndAdd")}
        </Button>
      </div>
    </div>
  );
}
