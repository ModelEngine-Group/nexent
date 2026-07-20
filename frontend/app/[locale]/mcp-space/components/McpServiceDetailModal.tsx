import { useEffect, useMemo, useState } from "react";
import { Alert, App, Button, Form, Input, Modal } from "antd";
import { ApiOutlined, CloudOutlined, ContainerOutlined, LinkOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import {
  McpDeploymentType,
  McpServiceStatus,
  McpTransportType,
  MCP_TOOLS_MODAL_WRAP_CLASS,
  mcpToolsModalChromeStyles,
} from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";
import { resolveDeploymentType, toPrettyRegistryJson } from "@/lib/mcpTools";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import { useMcpServiceDetail } from "@/hooks/mcpTools/useMcpServiceDetail";
import McpContainerLogsModal from "@/components/mcp/McpContainerLogsModal";
import McpToolListModal from "@/components/mcp/McpToolListModal";
import ContainerPortField from "./shared/ContainerPortField";
import TagEditor from "./shared/TagEditor";
import JsonPreviewModal from "./shared/JsonPreviewModal";
import PublishConfirmModal from "./PublishConfirmModal";

interface McpServiceDetailModalProps {
  selectedService: McpServiceItem | null;
  onClose: () => void;
  onToggled?: (mcpId: number, next: McpServiceStatus) => void;
}

const DEPLOYMENT_OPTIONS = [
  {
    value: McpDeploymentType.REMOTE_LINK,
    labelKey: "mcpTools.deploymentType.remoteLink",
    Icon: LinkOutlined,
  },
  {
    value: McpDeploymentType.CONTAINER,
    labelKey: "mcpTools.deploymentType.container",
    Icon: ContainerOutlined,
  },
  {
    value: McpDeploymentType.API,
    labelKey: "mcpTools.deploymentType.api",
    Icon: ApiOutlined,
  },
  {
    value: McpDeploymentType.LOCAL_IMAGE,
    labelKey: "mcpTools.deploymentType.localImage",
    Icon: CloudOutlined,
  },
] as const;

export default function McpServiceDetailModal({
  selectedService,
  onClose,
}: McpServiceDetailModalProps) {
  const { modal } = App.useApp();
  const { t } = useTranslation("common");
  const rules = useMcpFormRules();
  const [form] = Form.useForm();
  const [logsOpen, setLogsOpen] = useState(false);
  const [showServerJson, setShowServerJson] = useState(false);
  const [showConfigJson, setShowConfigJson] = useState(false);
  const [publishConfirmOpen, setPublishConfirmOpen] = useState(false);
  const [deploymentType, setDeploymentType] = useState<McpDeploymentType>(
    McpDeploymentType.REMOTE_LINK
  );
  const [draftTags, setDraftTags] = useState<string[]>([]);
  const [containerPort, setContainerPort] = useState<number | undefined>();

  const detail = useMcpServiceDetail({ selectedService, onClose });
  const { draft } = detail;

  const originalDeploymentType = useMemo(
    () =>
      draft
        ? resolveDeploymentType({
            transportType: draft.transportType,
            deploymentType: draft.deploymentType,
            configJson: draft.configJson,
            serverUrl: draft.serverUrl,
          })
        : McpDeploymentType.REMOTE_LINK,
    [draft]
  );

  useEffect(() => {
    if (!draft) return;
    const nextDeploymentType = resolveDeploymentType({
      transportType: draft.transportType,
      deploymentType: draft.deploymentType,
      configJson: draft.configJson,
      serverUrl: draft.serverUrl,
    });
    setDeploymentType(nextDeploymentType);
    setDraftTags(draft.tags ?? []);
    setContainerPort(draft.containerPort);
    form.setFieldsValue({
      name: draft.name,
      description: draft.description,
      version: draft.version,
      serverUrl: draft.serverUrl,
      authorizationToken: draft.authorizationToken ?? "",
      customHeaders: draft.customHeaders ? JSON.stringify(draft.customHeaders, null, 2) : "",
      openApiJson: toPrettyRegistryJson(draft.configJson),
      containerConfigJson: toPrettyRegistryJson(draft.configJson),
      containerPort: draft.containerPort,
    });
  }, [draft, form]);

  if (!selectedService || !draft) {
    return null;
  }

  const isRemoteLink = deploymentType === McpDeploymentType.REMOTE_LINK;
  const isContainer = deploymentType === McpDeploymentType.CONTAINER;
  const isApi = deploymentType === McpDeploymentType.API;
  const isUnsupported =
    deploymentType === McpDeploymentType.LOCAL_IMAGE ||
    deploymentType !== originalDeploymentType;
  const hasRegistryJson = Boolean(draft.registryJson);
  const hasConfigJson = Boolean(draft.configJson);

  const addTag = (tag: string) => {
    const next = tag.trim();
    if (!next || draftTags.includes(next)) return;
    setDraftTags((prev) => [...prev, next]);
  };

  const removeTag = (index: number) => {
    setDraftTags((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSave = async () => {
    if (isUnsupported) return;
    try {
      await form.validateFields();
    } catch {
      return;
    }

    const values = form.getFieldsValue();
    let parsedCustomHeaders: Record<string, string> | undefined;
    if (values.customHeaders?.trim()) {
      try {
        parsedCustomHeaders = JSON.parse(values.customHeaders.trim());
      } catch {
        modal.error({
          content: t("mcpConfig.message.invalidCustomHeadersJson"),
        });
        return;
      }
    }

    let parsedConfigJson = draft.configJson;
    if (isApi) {
      try {
        parsedConfigJson = JSON.parse(String(values.openApiJson || "").trim());
      } catch {
        modal.error({
          content: t("mcpConfig.openApiToMcp.message.invalidJson"),
        });
        return;
      }
    }
    if (isContainer) {
      try {
        parsedConfigJson = JSON.parse(String(values.containerConfigJson || "").trim());
      } catch {
        modal.error({
          content: t("mcpTools.add.error.containerJsonInvalid"),
        });
        return;
      }
    }

    const nextDraft = {
      ...draft,
      name: values.name ?? "",
      description: values.description ?? "",
      version: values.version ?? "",
      serverUrl: values.serverUrl ?? "",
      authorizationToken: values.authorizationToken ?? "",
      customHeaders: parsedCustomHeaders,
      configJson: parsedConfigJson,
      tags: draftTags,
    };
    detail.setDraft(nextDraft);
    await detail.save(nextDraft);
  };

  return (
    <>
      <Modal
        open
        footer={null}
        closable
        centered
        width={720}
        style={{ top: 20 }}
        onCancel={onClose}
        wrapClassName={`${MCP_TOOLS_MODAL_WRAP_CLASS}`}
        styles={mcpToolsModalChromeStyles()}
      >
        <div className="bg-white">
          <div className="border-b border-slate-100 px-6 py-5">
            <h2 className="text-2xl font-semibold text-slate-900">
              {t("mcpTools.detail.editTitle")}
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              {t("mcpTools.detail.editSubtitle")}
            </p>
          </div>

          <Form
            form={form}
            layout="vertical"
            requiredMark={false}
            className="space-y-5 px-6 py-5"
          >
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">
                {t("mcpTools.detail.addMethod")}
              </label>
              <div className="grid grid-cols-4 gap-3">
                {DEPLOYMENT_OPTIONS.map(({ value, labelKey, Icon }) => {
                  const selected = deploymentType === value;
                  return (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setDeploymentType(value)}
                      className={`flex h-20 flex-col items-center justify-center gap-2 rounded-xl border text-sm transition ${
                        selected
                          ? "border-blue-500 bg-blue-50 text-blue-600 shadow-sm"
                          : "border-slate-200 bg-white text-slate-600 hover:border-blue-200 hover:bg-blue-50/40"
                      }`}
                    >
                      <Icon className="text-xl" />
                      <span>{t(labelKey)}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            {isUnsupported ? (
              <Alert
                type="info"
                showIcon
                message={t("mcpTools.addModal.unsupportedTitle")}
                description={
                  deploymentType !== originalDeploymentType
                    ? t("mcpTools.detail.deploymentChangeUnsupported")
                    : t("mcpTools.addModal.unsupportedDescription")
                }
              />
            ) : null}

            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">
                {t("mcpTools.detail.serviceName")}
              </label>
              <Form.Item name="name" rules={rules.name} className="mb-0">
                <Input className="w-full rounded-md" />
              </Form.Item>
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">
                {t("mcpTools.detail.serviceDescription")}
              </label>
              <Form.Item
                name="description"
                rules={rules.description}
                className="mb-0"
              >
                <Input.TextArea
                  autoSize={{ minRows: 4, maxRows: 10 }}
                  className="w-full rounded-md"
                />
              </Form.Item>
            </div>

            {isRemoteLink ? (
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">
                  {t("mcpTools.detail.serviceConfigTitle")}
                </label>
                <div className="space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
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
                        className="w-full rounded-md"
                        placeholder={t("mcpTools.addModal.bearerTokenPlaceholder")}
                      />
                    </Form.Item>
                  </div>

                  <div>
                    <label className="mb-1 block text-sm font-normal text-slate-500">
                      {t("mcpTools.addModal.customHeaders")}
                    </label>
                    <Form.Item name="customHeaders" className="mb-0">
                      <Input.TextArea
                        rows={2}
                        className="w-full rounded-md"
                        placeholder={t("mcpTools.addModal.customHeadersPlaceholder")}
                      />
                    </Form.Item>
                  </div>
                </div>
              </div>
            ) : null}

            {isApi ? (
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">
                  {t("mcpTools.detail.serviceConfigTitle")}
                </label>
                <div className="space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
                  <div>
                    <label className="mb-1 block text-sm font-normal text-slate-500">
                      {t("mcpConfig.openapiService.form.serverUrl")}
                    </label>
                    <Form.Item
                      name="serverUrl"
                      rules={rules.httpUrl}
                      className="mb-0"
                    >
                      <Input
                        className="w-full rounded-md"
                        placeholder={t("mcpConfig.openapiService.form.serverUrlPlaceholder")}
                      />
                    </Form.Item>
                  </div>

                  <div>
                    <label className="mb-1 block text-sm font-normal text-slate-500">
                      {t("mcpConfig.addServer.customHeaders")}
                    </label>
                    <Form.Item name="customHeaders" className="mb-0">
                      <Input.TextArea
                        rows={2}
                        className="w-full rounded-md"
                        placeholder={t("mcpConfig.addServer.customHeadersPlaceholder")}
                      />
                    </Form.Item>
                  </div>

                  <div>
                    <label className="mb-1 block text-sm font-normal text-slate-500">
                      {t("mcpConfig.openapiService.form.openapiJson")}
                    </label>
                    <Form.Item name="openApiJson" className="mb-0">
                      <Input.TextArea
                        rows={6}
                        className="w-full rounded-md"
                        placeholder={t("mcpConfig.openApiToMcp.jsonPlaceholder")}
                      />
                    </Form.Item>
                  </div>
                </div>
              </div>
            ) : null}

            {isContainer ? (
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">
                  {t("mcpTools.detail.serviceConfigTitle")}
                </label>
                <div className="space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
                  <div>
                    <label className="mb-1 block text-sm font-normal text-slate-500">
                      {t("mcpTools.addModal.containerConfig")}
                    </label>
                    <Form.Item name="containerConfigJson" className="mb-0">
                      <Input.TextArea
                        rows={5}
                        className="w-full rounded-md bg-white text-slate-600"
                        placeholder={t("mcpTools.addModal.containerConfigPlaceholder")}
                      />
                    </Form.Item>
                  </div>

                  <Form.Item name="containerPort" className="mb-0">
                    <ContainerPortField
                      scope="detail"
                      enabled={false}
                      containerPort={containerPort}
                      setContainerPort={(value) => {
                        setContainerPort(value);
                        form.setFieldValue("containerPort", value);
                      }}
                    />
                  </Form.Item>
                </div>
              </div>
            ) : null}

            <div className="flex flex-col gap-4">
              <TagEditor
                title={t("mcpTools.detail.tags")}
                titleClassName="mb-1 block text-sm font-medium text-slate-700"
                tags={draftTags}
                onAddTag={(tag) => addTag(tag || "")}
                onRemoveTag={removeTag}
                removeAriaKey="mcpTools.detail.removeTagAria"
                placeholderKey="mcpTools.detail.tagInputPlaceholder"
              />
            </div>
          </Form>

          <div className="flex items-center justify-between border-t border-slate-100 bg-white px-6 py-4">
            <div className="flex gap-2">
              {draft.containerId ? (
                <Button onClick={() => setLogsOpen(true)}>
                  {t("mcpTools.detail.viewContainerLogs")}
                </Button>
              ) : null}
              {hasRegistryJson ? (
                <Button onClick={() => setShowServerJson(true)}>
                  {t("mcpTools.registry.viewServerJson")}
                </Button>
              ) : null}
              {hasConfigJson ? (
                <Button onClick={() => setShowConfigJson(true)}>
                  {t("mcpTools.detail.viewConfigJson")}
                </Button>
              ) : null}
              <Button loading={detail.loadingTools} onClick={detail.loadTools}>
                {t("mcpTools.detail.viewTools")}
              </Button>
            </div>

            <div className="flex items-center gap-3">
              <Button onClick={onClose}>{t("common.cancel")}</Button>
              <Button
                type="primary"
                loading={detail.saving}
                disabled={isUnsupported}
                onClick={handleSave}
              >
                {t("mcpTools.detail.save")}
              </Button>
            </div>
          </div>
        </div>
      </Modal>

      <McpToolListModal
        open={detail.toolsState.visible}
        onCancel={detail.closeToolsModal}
        loading={detail.loadingTools}
        tools={detail.toolsState.tools}
        serverName={draft.name || String(t("mcpTools.service.defaultName"))}
      />

      <JsonPreviewModal
        open={showServerJson && hasRegistryJson}
        title={t("mcpTools.registry.serverJsonTitle", { name: draft.name })}
        json={toPrettyRegistryJson(draft.registryJson)}
        onCancel={() => setShowServerJson(false)}
      />

      <JsonPreviewModal
        open={showConfigJson && hasConfigJson}
        title={t("mcpTools.detail.configJsonTitle", { name: draft.name })}
        json={toPrettyRegistryJson(draft.configJson)}
        onCancel={() => setShowConfigJson(false)}
      />

      {draft.containerId ? (
        <McpContainerLogsModal
          open={logsOpen}
          onCancel={() => setLogsOpen(false)}
          containerId={draft.containerId}
        />
      ) : null}

      <PublishConfirmModal
        open={publishConfirmOpen}
        source={selectedService}
        publishing={detail.publishing}
        onCancel={() => setPublishConfirmOpen(false)}
        onConfirm={async (override) => {
          const ok = await detail.publish(override);
          if (ok) setPublishConfirmOpen(false);
        }}
      />
    </>
  );
}
