import { Input, InputNumber, Modal, Select, Tag } from "antd";
import { MCP_TRANSPORT_TYPE } from "@/const/mcpTools";
import McpCommunityToolbar from "./McpCommunityToolbar";
import McpCommunityCardList from "./McpCommunityCardList";
import McpCommunityDetailModal from "./McpCommunityDetailModal";
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
  t,
}: Props) {
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
        onOk={handleConfirmQuickAddFromCommunity}
        okText={t("mcpTools.community.quickAddConfirm")}
        cancelText={t("common.cancel")}
        confirmLoading={quickAddSubmitting}
        width={900}
      >
        <div className="space-y-4 pt-2">
          <label className="block text-sm text-slate-500">
            {t("mcpTools.addModal.name")}
            <Input
              value={quickAddDraft.name}
              onChange={(event) => updateQuickAddDraft({ name: event.target.value })}
              className="mt-2 w-full rounded-2xl"
            />
          </label>

          <label className="block text-sm text-slate-500">
            {t("mcpTools.addModal.description")}
            <Input
              value={quickAddDraft.description}
              onChange={(event) => updateQuickAddDraft({ description: event.target.value })}
              className="mt-2 w-full rounded-2xl"
            />
          </label>

          <label className="block text-sm text-slate-500">
            {t("mcpTools.addModal.serverType")}
            <Select
              value={quickAddDraft.transportType}
              onChange={(value) => updateQuickAddDraft({ transportType: value as McpTransportType })}
              className="mt-2 w-full"
              options={[
                { label: t("mcpTools.serverType.http"), value: MCP_TRANSPORT_TYPE.HTTP },
                { label: t("mcpTools.serverType.sse"), value: MCP_TRANSPORT_TYPE.SSE },
                { label: t("mcpTools.serverType.stdio"), value: MCP_TRANSPORT_TYPE.STDIO },
              ]}
            />
          </label>

          {quickAddDraft.transportType === MCP_TRANSPORT_TYPE.HTTP || quickAddDraft.transportType === MCP_TRANSPORT_TYPE.SSE ? (
            <div className="space-y-4">
              <label className="block text-sm text-slate-500">
                {t("mcpTools.addModal.serverUrl")}
                <Input
                  value={quickAddDraft.serverUrl}
                  onChange={(event) => updateQuickAddDraft({ serverUrl: event.target.value })}
                  className="mt-2 w-full rounded-2xl"
                />
              </label>
              <label className="block text-sm text-slate-500">
                {t("mcpTools.addModal.bearerTokenOptional")}
                <Input
                  value={quickAddDraft.authorizationToken}
                  onChange={(event) => updateQuickAddDraft({ authorizationToken: event.target.value })}
                  className="mt-2 w-full rounded-2xl"
                  placeholder={t("mcpTools.addModal.bearerTokenPlaceholder")}
                />
              </label>
            </div>
          ) : (
            <div className="space-y-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <label className="block text-sm text-slate-500">
                {t("mcpTools.addModal.containerConfig")}
                <Input.TextArea
                  value={quickAddDraft.containerConfigJson}
                  onChange={(event) => updateQuickAddDraft({ containerConfigJson: event.target.value })}
                  rows={6}
                  className="mt-2"
                  placeholder={t("mcpTools.addModal.containerConfigPlaceholder")}
                />
              </label>

              <label className="block text-sm text-slate-500">
                {t("mcpTools.addModal.containerPort")}
                <InputNumber
                  value={quickAddDraft.containerPort}
                  onChange={(value) => updateQuickAddDraft({ containerPort: value === null ? undefined : value })}
                  min={1}
                  max={65535}
                  controls={false}
                  className="mt-2 w-full"
                  placeholder={t("mcpTools.addModal.containerPortPlaceholder")}
                />
              </label>
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
        </div>
      </Modal>
    </>
  );
}
