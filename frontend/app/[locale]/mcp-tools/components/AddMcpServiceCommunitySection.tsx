import { useEffect } from "react";
import { Button, Form, Input, Modal, Select, Tag } from "antd";
import { MCP_TRANSPORT_TYPE } from "@/const/mcpTools";
import McpCommunityToolbar from "./McpCommunityToolbar";
import McpCommunityCardList from "./McpCommunityCardList";
import McpCommunityDetailModal from "./McpCommunityDetailModal";
import ContainerPortField from "./ContainerPortField";
import McpDescriptionField from "./McpDescriptionField";
import type { CommunityMcpCard, McpTransportType } from "@/types/mcpTools";

interface Props {
  communitySearchValue: string;
  communityTransportTypeFilter: "all" | "http" | "sse" | "stdio";
  communityTagFilter: string;
  communityTagStats: Array<{ tag: string; count: number }>;
  selectedCommunityService: CommunityMcpCard | null;
  filteredCommunityServices: CommunityMcpCard[];
  communityLoading: boolean;
  communityPage: number;
  hasPrevCommunityPage: boolean;
  hasNextCommunityPage: boolean;
  quickAddConfirmVisible: boolean;
  quickAddSourceService: CommunityMcpCard | null;
  quickAddDraft: {
    name: string;
    description: string;
    transportType: McpTransportType;
    serverUrl: string;
    authorizationToken: string;
    containerConfigJson: string;
    containerPort: number | undefined;
    tags: string[];
    tagInputValue: string;
  };
  setCommunitySearchValue: (value: string) => void;
  setCommunityTransportTypeFilter: (value: "all" | "http" | "sse" | "stdio") => void;
  setCommunityTagFilter: (value: string) => void;
  setSelectedCommunityService: (service: CommunityMcpCard | null) => void;
  updateQuickAddDraft: (next: {
    name?: string;
    description?: string;
    transportType?: McpTransportType;
    serverUrl?: string;
    authorizationToken?: string;
    containerConfigJson?: string;
    containerPort?: number | undefined;
    tagInputValue?: string;
  }) => void;
  addQuickAddTag: () => void;
  removeQuickAddTag: (index: number) => void;
  handleCommunityPrevPage: () => void;
  handleCommunityNextPage: () => void;
  handleQuickAddFromCommunity: (service: CommunityMcpCard) => void;
  handleCloseQuickAddConfirm: () => void;
  handleConfirmQuickAddFromCommunity: () => void;
  quickAddSubmitting: boolean;
  handleSuggestContainerPort: () => void;
  containerPortCheckLoading: boolean;
  containerPortSuggesting: boolean;
  containerPortAvailable: boolean;
  t: (key: string, params?: Record<string, unknown>) => string;
}

export default function AddMcpServiceCommunitySection({
  communitySearchValue,
  communityTransportTypeFilter,
  communityTagFilter,
  communityTagStats,
  selectedCommunityService,
  filteredCommunityServices,
  communityLoading,
  communityPage,
  hasPrevCommunityPage,
  hasNextCommunityPage,
  quickAddConfirmVisible,
  quickAddSourceService,
  quickAddDraft,
  setCommunitySearchValue,
  setCommunityTransportTypeFilter,
  setCommunityTagFilter,
  setSelectedCommunityService,
  updateQuickAddDraft,
  addQuickAddTag,
  removeQuickAddTag,
  handleCommunityPrevPage,
  handleCommunityNextPage,
  handleQuickAddFromCommunity,
  handleCloseQuickAddConfirm,
  handleConfirmQuickAddFromCommunity,
  quickAddSubmitting,
  handleSuggestContainerPort,
  containerPortCheckLoading,
  containerPortSuggesting,
  containerPortAvailable,
  t,
}: Props) {
  const [form] = Form.useForm();

  const isHttpUrl = (value: string): boolean => {
    try {
      const parsed = new URL(value);
      return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch {
      return false;
    }
  };

  useEffect(() => {
    if (!quickAddConfirmVisible) return;
    form.setFieldsValue({
      name: quickAddDraft.name,
      description: quickAddDraft.description,
      transportType: quickAddDraft.transportType,
      serverUrl: quickAddDraft.serverUrl,
      authorizationToken: quickAddDraft.authorizationToken,
      containerConfigJson: quickAddDraft.containerConfigJson,
      containerPort: quickAddDraft.containerPort,
    });
  }, [form, quickAddConfirmVisible, quickAddDraft]);

  return (
    <>
      <div className="px-6 py-5 space-y-5">
        <McpCommunityToolbar
          communitySearchValue={communitySearchValue}
          communityTransportTypeFilter={communityTransportTypeFilter}
          communityTagFilter={communityTagFilter}
          communityTagStats={communityTagStats}
          communityPage={communityPage}
          resultCount={filteredCommunityServices.length}
          onCommunitySearchChange={setCommunitySearchValue}
          onCommunityTransportTypeFilterChange={setCommunityTransportTypeFilter}
          onCommunityTagFilterChange={setCommunityTagFilter}
          t={t}
        />

        <McpCommunityCardList
          communityLoading={communityLoading}
          services={filteredCommunityServices}
          hasPrevCommunityPage={hasPrevCommunityPage}
          hasNextCommunityPage={hasNextCommunityPage}
          onPrevCommunityPage={handleCommunityPrevPage}
          onNextCommunityPage={handleCommunityNextPage}
          onSelectCommunityService={setSelectedCommunityService}
          onQuickAddFromCommunity={handleQuickAddFromCommunity}
          t={t}
        />
      </div>

      {selectedCommunityService ? (
        <McpCommunityDetailModal
          service={selectedCommunityService}
          t={t}
          onClose={() => setSelectedCommunityService(null)}
          onQuickAddFromCommunity={handleQuickAddFromCommunity}
        />
      ) : null}

      <Modal
        open={quickAddConfirmVisible}
        title={t("mcpTools.community.quickAddConfirmTitle", { name: quickAddSourceService?.name || "" })}
        onCancel={handleCloseQuickAddConfirm}
        onOk={() => form.submit()}
        okText={t("mcpTools.community.quickAddConfirm")}
        cancelText={t("common.cancel")}
        confirmLoading={quickAddSubmitting}
        width={900}
      >
        <Form form={form} layout="vertical" requiredMark={false} className="space-y-4 pt-2" onFinish={handleConfirmQuickAddFromCommunity}>
          <Form.Item
            label={t("mcpTools.addModal.name")}
            name="name"
            className="mb-0 text-sm text-slate-500"
            rules={[
              { required: true, whitespace: true, message: t("mcpTools.add.validate.nameRequired") },
              { type: "string", max: 100, message: t("mcpTools.add.validate.nameMaxLength") },
            ]}
          >
            <Input
              value={quickAddDraft.name}
              onChange={(event) => {
                updateQuickAddDraft({ name: event.target.value });
                form.setFieldValue("name", event.target.value);
              }}
              className="mt-2 w-full rounded-2xl"
            />
          </Form.Item>

          <Form.Item
            label={t("mcpTools.addModal.description")}
            name="description"
            className="mb-0 text-sm text-slate-500"
            rules={[{ type: "string", max: 5000, message: t("mcpTools.add.validate.descriptionMaxLength") }]}
          >
            <McpDescriptionField
              label={t("mcpTools.addModal.description")}
              value={quickAddDraft.description}
              onChange={(value) => {
                updateQuickAddDraft({ description: value });
                form.setFieldValue("description", value);
              }}
              t={(key, params) => String(t(key, params as any))}
              minRows={1}
              maxRows={24}
              toggleMinChars={160}
              toggleMinLines={1}
            />
          </Form.Item>

          <Form.Item
            label={t("mcpTools.addModal.serverType")}
            name="transportType"
            className="mb-0 text-sm text-slate-500"
            rules={[{ required: true, message: t("mcpTools.add.validate.transportTypeRequired") }]}
          >
            <Select
              value={quickAddDraft.transportType}
              onChange={(value) => {
                updateQuickAddDraft({ transportType: value as McpTransportType });
                form.setFieldValue("transportType", value);
              }}
              className="mt-2 w-full"
              options={[
                { label: t("mcpTools.serverType.http"), value: MCP_TRANSPORT_TYPE.HTTP },
                { label: t("mcpTools.serverType.sse"), value: MCP_TRANSPORT_TYPE.SSE },
                { label: t("mcpTools.serverType.stdio"), value: MCP_TRANSPORT_TYPE.STDIO },
              ]}
            />
          </Form.Item>

          {quickAddDraft.transportType === MCP_TRANSPORT_TYPE.HTTP || quickAddDraft.transportType === MCP_TRANSPORT_TYPE.SSE ? (
            <div className="space-y-4">
              <Form.Item
                label={t("mcpTools.addModal.serverUrl")}
                name="serverUrl"
                className="mb-0 text-sm text-slate-500"
                rules={[
                  {
                    validator: async (_rule, value) => {
                      const text = String(value || "").trim();
                      if (!text) {
                        throw new Error(t("mcpTools.add.validate.httpUrlRequired"));
                      }
                      if (text.length > 500) {
                        throw new Error(t("mcpTools.add.validate.httpUrlMaxLength"));
                      }
                      if (!isHttpUrl(text)) {
                        throw new Error(t("mcpTools.add.validate.httpUrlFormat"));
                      }
                    },
                  },
                ]}
              >
                <Input
                  value={quickAddDraft.serverUrl}
                  onChange={(event) => {
                    updateQuickAddDraft({ serverUrl: event.target.value });
                    form.setFieldValue("serverUrl", event.target.value);
                  }}
                  className="mt-2 w-full rounded-2xl"
                />
              </Form.Item>
              <Form.Item
                label={t("mcpTools.addModal.bearerTokenOptional")}
                name="authorizationToken"
                className="mb-0 text-sm text-slate-500"
                rules={[{ type: "string", max: 500, message: t("mcpTools.add.validate.authorizationTokenMaxLength") }]}
              >
                <Input
                  value={quickAddDraft.authorizationToken}
                  onChange={(event) => {
                    updateQuickAddDraft({ authorizationToken: event.target.value });
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
                rules={[
                  {
                    validator: async (_rule, value) => {
                      const text = String(value || "").trim();
                      if (!text) {
                        throw new Error(t("mcpTools.add.validate.containerConfigRequired"));
                      }
                      try {
                        JSON.parse(text);
                      } catch {
                        throw new Error(t("mcpTools.add.error.containerJsonInvalid"));
                      }
                    },
                  },
                ]}
              >
                <Input.TextArea
                  value={quickAddDraft.containerConfigJson}
                  onChange={(event) => {
                    updateQuickAddDraft({ containerConfigJson: event.target.value });
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
                rules={[
                  {
                    validator: async (_rule, value) => {
                      if (value === undefined || value === null || value === "") {
                        throw new Error(t("mcpTools.add.validate.containerRequired"));
                      }
                      const port = Number(value);
                      if (!Number.isInteger(port) || port < 1 || port > 65535) {
                        throw new Error(t("mcpTools.add.validate.containerPortRange"));
                      }
                    },
                  },
                ]}
              >
                <div>
                  <ContainerPortField
                    containerPort={quickAddDraft.containerPort}
                    containerPortCheckLoading={containerPortCheckLoading}
                    containerPortSuggesting={containerPortSuggesting}
                    containerPortAvailable={containerPortAvailable}
                    setContainerPort={(value) => {
                      updateQuickAddDraft({ containerPort: value });
                      form.setFieldValue("containerPort", value);
                    }}
                    handleSuggestContainerPort={handleSuggestContainerPort}
                    t={t}
                  />
                </div>
              </Form.Item>
            </div>
          )}

          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{t("mcpTools.addModal.tags")}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {quickAddDraft.tags.map((tag, index) => (
                <span key={`${tag}-${index}`} className="relative inline-flex">
                  <Tag className="rounded-full px-3 py-1 m-0 leading-none">{tag}</Tag>
                  <button
                    type="button"
                    onClick={() => removeQuickAddTag(index)}
                    className="absolute top-0 right-0 -translate-y-1/2 translate-x-1/2 flex h-4 w-4 items-center justify-center rounded-full bg-slate-200 text-[10px] text-slate-500 transition hover:bg-slate-300 hover:text-slate-700"
                    aria-label={t("mcpTools.addModal.removeTagAria", { tag })}
                  >
                    x
                  </button>
                </span>
              ))}
              <Input
                size="small"
                value={quickAddDraft.tagInputValue}
                onChange={(event) => updateQuickAddDraft({ tagInputValue: event.target.value })}
                onPressEnter={addQuickAddTag}
                onBlur={addQuickAddTag}
                placeholder={t("mcpTools.addModal.tagInputPlaceholder")}
                className="w-40 rounded-full"
              />
            </div>
          </div>
        </Form>
      </Modal>
    </>
  );
}
