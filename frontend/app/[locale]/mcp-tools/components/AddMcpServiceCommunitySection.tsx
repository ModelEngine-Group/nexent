import { useEffect, useState } from "react";
import { Form, Input, Modal, Select } from "antd";
import { useTranslation } from "react-i18next";
import { MCP_TRANSPORT_TYPE } from "@/const/mcpTools";
import type { CommunityMcpCard, McpTransportType } from "@/types/mcpTools";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import { useMcpCommunityBrowser } from "@/hooks/mcpTools/useMcpCommunityBrowser";
import { useMcpCommunityQuickAdd } from "@/hooks/mcpTools/useMcpCommunityQuickAdd";
import McpCommunityToolbar from "./McpCommunityToolbar";
import McpCommunityCardList from "./McpCommunityCardList";
import McpCommunityDetailModal from "./McpCommunityDetailModal";
import ContainerPortField from "./ContainerPortField";
import TagEditor from "./shared/TagEditor";

interface AddMcpServiceCommunitySectionProps {
  active: boolean;
  onAdded: () => void;
}

export default function AddMcpServiceCommunitySection({
  active,
  onAdded,
}: AddMcpServiceCommunitySectionProps) {
  const [selected, setSelected] = useState<CommunityMcpCard | null>(null);
  const browser = useMcpCommunityBrowser(active);
  const quickAdd = useMcpCommunityQuickAdd({ onSuccess: onAdded });

  if (!active) return null;

  return (
    <>
      <div className="px-6 py-5 space-y-5">
        <McpCommunityToolbar
          search={browser.filters.search}
          transport={browser.filters.transport}
          tag={browser.filters.tag}
          tagStats={browser.tagStats}
          page={browser.page}
          resultCount={browser.services.length}
          onSearchChange={(value) => browser.updateFilter("search", value)}
          onTransportChange={(value) =>
            browser.updateFilter("transport", value)
          }
          onTagChange={(value) => browser.updateFilter("tag", value)}
        />

        <McpCommunityCardList
          loading={browser.loading}
          services={browser.services}
          hasPrevPage={browser.hasPrevPage}
          hasNextPage={browser.hasNextPage}
          onPrevPage={browser.prevPage}
          onNextPage={browser.nextPage}
          onSelect={setSelected}
          onQuickAdd={quickAdd.open}
        />
      </div>

      {selected ? (
        <McpCommunityDetailModal
          service={selected}
          onClose={() => setSelected(null)}
          onQuickAdd={quickAdd.open}
        />
      ) : null}

      <CommunityQuickAddModal controller={quickAdd} />
    </>
  );
}

interface CommunityQuickAddModalProps {
  controller: ReturnType<typeof useMcpCommunityQuickAdd>;
}

function CommunityQuickAddModal({ controller }: CommunityQuickAddModalProps) {
  const { t } = useTranslation("common");
  const rules = useMcpFormRules();
  const [form] = Form.useForm();
  const [tagInput, setTagInput] = useState("");
  const { visible, source, draft, submitting } = controller;

  useEffect(() => {
    if (!visible || !draft) return;
    form.setFieldsValue({
      name: draft.name,
      description: draft.description,
      transportType: draft.transportType,
      serverUrl: draft.serverUrl,
      authorizationToken: draft.authorizationToken,
      containerConfigJson: draft.containerConfigJson,
      containerPort: draft.containerPort,
    });
  }, [visible, draft, form]);

  useEffect(() => {
    if (!visible) setTagInput("");
  }, [visible]);

  if (!draft) {
    return (
      <Modal
        open={visible}
        onCancel={controller.close}
        footer={null}
        width={900}
      />
    );
  }

  const addTag = () => {
    const next = tagInput.trim();
    if (!next) {
      setTagInput("");
      return;
    }
    if (draft.tags.includes(next)) {
      setTagInput("");
      return;
    }
    controller.updateDraft({ tags: [...draft.tags, next] });
    setTagInput("");
  };

  const removeTag = (index: number) => {
    controller.updateDraft({ tags: draft.tags.filter((_, i) => i !== index) });
  };

  const handleOk = async () => {
    try {
      await form.validateFields();
    } catch {
      return;
    }
    await controller.confirm();
  };

  return (
    <Modal
      open={visible}
      title={t("mcpTools.community.quickAddConfirmTitle", {
        name: source?.name || "",
      })}
      onCancel={controller.close}
      onOk={handleOk}
      okText={t("mcpTools.community.quickAddConfirm")}
      cancelText={t("common.cancel")}
      confirmLoading={submitting}
      width={900}
    >
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        className="space-y-4 pt-2"
      >
        <Form.Item
          label={t("mcpTools.addModal.name")}
          name="name"
          className="mb-0 text-sm text-slate-500"
          rules={rules.name}
        >
          <Input
            value={draft.name}
            onChange={(event) => {
              controller.updateDraft({ name: event.target.value });
              form.setFieldValue("name", event.target.value);
            }}
            className="mt-2 w-full rounded-2xl"
          />
        </Form.Item>

        <Form.Item
          label={t("mcpTools.addModal.description")}
          name="description"
          className="mb-0 text-sm text-slate-500"
          rules={rules.description}
        >
          <Input.TextArea
            value={draft.description}
            onChange={(event) => {
              controller.updateDraft({ description: event.target.value });
              form.setFieldValue("description", event.target.value);
            }}
            autoSize={{ minRows: 1, maxRows: 24 }}
            className="mt-2 w-full rounded-2xl"
          />
        </Form.Item>

        <Form.Item
          label={t("mcpTools.addModal.serverType")}
          name="transportType"
          className="mb-0 text-sm text-slate-500"
          rules={rules.transportType}
        >
          <Select
            value={draft.transportType}
            onChange={(value: McpTransportType) => {
              controller.updateDraft({ transportType: value });
              form.setFieldValue("transportType", value);
            }}
            className="mt-2 w-full"
            options={[
              {
                label: t("mcpTools.serverType.http"),
                value: MCP_TRANSPORT_TYPE.HTTP,
              },
              {
                label: t("mcpTools.serverType.sse"),
                value: MCP_TRANSPORT_TYPE.SSE,
              },
              {
                label: t("mcpTools.serverType.container"),
                value: MCP_TRANSPORT_TYPE.CONTAINER,
              },
            ]}
          />
        </Form.Item>

        {draft.transportType === MCP_TRANSPORT_TYPE.HTTP ||
        draft.transportType === MCP_TRANSPORT_TYPE.SSE ? (
          <div className="space-y-4">
            <Form.Item
              label={t("mcpTools.addModal.serverUrl")}
              name="serverUrl"
              className="mb-0 text-sm text-slate-500"
              rules={rules.httpUrl}
            >
              <Input
                value={draft.serverUrl}
                onChange={(event) => {
                  controller.updateDraft({ serverUrl: event.target.value });
                  form.setFieldValue("serverUrl", event.target.value);
                }}
                className="mt-2 w-full rounded-2xl"
              />
            </Form.Item>
            <Form.Item
              label={t("mcpTools.addModal.bearerTokenOptional")}
              name="authorizationToken"
              className="mb-0 text-sm text-slate-500"
              rules={rules.authToken}
            >
              <Input
                value={draft.authorizationToken}
                onChange={(event) => {
                  controller.updateDraft({
                    authorizationToken: event.target.value,
                  });
                  form.setFieldValue("authorizationToken", event.target.value);
                }}
                className="mt-2 w-full rounded-2xl"
                placeholder={t("mcpTools.addModal.bearerTokenPlaceholder")}
              />
            </Form.Item>
          </div>
        ) : (
          <div className="space-y-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <Form.Item
              label={t("mcpTools.addModal.containerConfig")}
              name="containerConfigJson"
              className="mb-0 text-sm text-slate-500"
              rules={rules.containerConfig}
            >
              <Input.TextArea
                value={draft.containerConfigJson}
                onChange={(event) => {
                  controller.updateDraft({
                    containerConfigJson: event.target.value,
                  });
                  form.setFieldValue("containerConfigJson", event.target.value);
                }}
                rows={6}
                className="mt-2"
                placeholder={t("mcpTools.addModal.containerConfigPlaceholder")}
              />
            </Form.Item>

            <Form.Item
              name="containerPort"
              className="mb-0"
              rules={rules.containerPort}
            >
              <div>
                <ContainerPortField
                  scope="community"
                  containerPort={draft.containerPort}
                  setContainerPort={(value) => {
                    controller.updateDraft({ containerPort: value });
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
          tagInput={tagInput}
          onTagInputChange={setTagInput}
          onAddTag={addTag}
          onRemoveTag={removeTag}
        />
      </Form>
    </Modal>
  );
}
