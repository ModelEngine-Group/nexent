import { useEffect, useMemo, useState } from "react";
import { Modal, Input, Select, Button, Segmented, Tag, Upload, InputNumber, Switch, DatePicker } from "antd";
import type { UploadFile } from "antd/es/upload/interface";
import dayjs from "dayjs";
import { useTranslation } from "react-i18next";

type McpTab = "本地" | "公共市场";
type McpServerType = "HTTP" | "SSE" | "容器";

const MCP_TAB = { LOCAL: "本地", MARKET: "公共市场" } as const;
const MCP_SERVER_TYPE = { HTTP: "HTTP", SSE: "SSE", CONTAINER: "容器" } as const;
const MARKET_SERVER_STATUS = { ACTIVE: "active", DEPRECATED: "deprecated" } as const;

type MarketMcpCard = {
  name: string;
  title: string;
  version: string;
  description: string;
  publishedAt: string;
  status: string;
  websiteUrl: string;
  remotes: Array<{ type: string; url: string }>;
  serverJson: Record<string, unknown>;
  serverType: McpServerType;
  serverUrl: string;
};

interface AddMcpServiceModalProps {
  open: boolean;
  addModalTab: McpTab;
  marketSearchValue: string;
  selectedMarketService: MarketMcpCard | null;
  filteredMarketServices: MarketMcpCard[];
  marketLoading: boolean;
  marketPage: number;
  hasPrevMarketPage: boolean;
  hasNextMarketPage: boolean;
  marketVersion: string;
  marketUpdatedSince: string;
  marketIncludeDeleted: boolean;
  newServiceName: string;
  newServiceDesc: string;
  newServerType: McpServerType;
  newServiceUrl: string;
  newServiceAuthorizationToken: string;
  containerUploadFileList: UploadFile[];
  containerConfigJson: string;
  containerPort: number | undefined;
  containerServiceName: string;
  newTagDrafts: string[];
  newTagInputValue: string;
  addingService: boolean;
  onClose: () => void;
  onAddModalTabChange: (value: McpTab) => void;
  onMarketSearchChange: (value: string) => void;
  onRefreshMarket: () => void;
  onPrevMarketPage: () => void;
  onNextMarketPage: () => void;
  onMarketVersionChange: (value: string) => void;
  onMarketUpdatedSinceChange: (value: string) => void;
  onMarketIncludeDeletedChange: (value: boolean) => void;
  onSelectMarketService: (service: MarketMcpCard | null) => void;
  onQuickAddFromMarket: (service: MarketMcpCard) => void;
  onNewServiceNameChange: (value: string) => void;
  onNewServiceDescChange: (value: string) => void;
  onNewServerTypeChange: (value: McpServerType) => void;
  onNewServiceUrlChange: (value: string) => void;
  onNewServiceAuthorizationTokenChange: (value: string) => void;
  onContainerUploadFileListChange: (fileList: UploadFile[]) => void;
  onContainerConfigJsonChange: (value: string) => void;
  onContainerPortChange: (value: number | undefined) => void;
  onContainerServiceNameChange: (value: string) => void;
  onAddNewTag: () => void;
  onRemoveNewTag: (index: number) => void;
  onNewTagInputChange: (value: string) => void;
  onSaveAndAdd: () => void;
}

export default function AddMcpServiceModal({
  open,
  addModalTab,
  marketSearchValue,
  selectedMarketService,
  filteredMarketServices,
  marketLoading,
  marketPage,
  hasPrevMarketPage,
  hasNextMarketPage,
  marketVersion,
  marketUpdatedSince,
  marketIncludeDeleted,
  newServiceName,
  newServiceDesc,
  newServerType,
  newServiceUrl,
  newServiceAuthorizationToken,
  containerUploadFileList,
  containerConfigJson,
  containerPort,
  containerServiceName,
  newTagDrafts,
  newTagInputValue,
  addingService,
  onClose,
  onAddModalTabChange,
  onMarketSearchChange,
  onRefreshMarket,
  onPrevMarketPage,
  onNextMarketPage,
  onMarketVersionChange,
  onMarketUpdatedSinceChange,
  onMarketIncludeDeletedChange,
  onSelectMarketService,
  onQuickAddFromMarket,
  onNewServiceNameChange,
  onNewServiceDescChange,
  onNewServerTypeChange,
  onNewServiceUrlChange,
  onNewServiceAuthorizationTokenChange,
  onContainerUploadFileListChange,
  onContainerConfigJsonChange,
  onContainerPortChange,
  onContainerServiceNameChange,
  onAddNewTag,
  onRemoveNewTag,
  onNewTagInputChange,
  onSaveAndAdd,
}: AddMcpServiceModalProps) {
  const { t } = useTranslation("common");
  const [showServerJsonModal, setShowServerJsonModal] = useState(false);
  const [marketVersionMode, setMarketVersionMode] = useState<"all" | "latest" | "custom">("latest");
  const [customVersion, setCustomVersion] = useState("");

  const VERSION_PATTERN = /^\d+\.\d+\.\d+$/;

  const formatMarketDate = (value: string) => {
    if (!value) {
      return "-";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()}`;
  };

  const formatMarketVersion = (value: string) => {
    const version = (value || "").trim();
    if (!version) {
      return "-";
    }
    if (/^v/i.test(version)) {
      return version;
    }
    return `v${version}`;
  };

  const getStatusClassName = (status: string) => {
    if (status === MARKET_SERVER_STATUS.ACTIVE) {
      return "bg-emerald-100 text-emerald-700";
    }
    if (status === MARKET_SERVER_STATUS.DEPRECATED) {
      return "bg-amber-100 text-amber-700";
    }
    return "bg-slate-100 text-slate-600";
  };

  const getStatusText = (status: string) => {
    if (status === MARKET_SERVER_STATUS.ACTIVE) {
      return t("mcpTools.market.status.active");
    }
    if (status === MARKET_SERVER_STATUS.DEPRECATED) {
      return t("mcpTools.market.status.deprecated");
    }
    return t("mcpTools.market.status.unknown");
  };

  const serverJsonPretty = useMemo(() => {
    if (!selectedMarketService) {
      return "{}";
    }
    try {
      return JSON.stringify(selectedMarketService.serverJson || {}, null, 2);
    } catch {
      return "{}";
    }
  }, [selectedMarketService]);

  const updatedSinceDateValue = useMemo(() => {
    if (!marketUpdatedSince) {
      return null;
    }
    const parsed = dayjs(marketUpdatedSince);
    return parsed.isValid() ? parsed : null;
  }, [marketUpdatedSince]);

  const customVersionError = customVersion.trim().length > 0 && !VERSION_PATTERN.test(customVersion.trim());

  useEffect(() => {
    if (!selectedMarketService) {
      setShowServerJsonModal(false);
    }
  }, [selectedMarketService]);

  useEffect(() => {
    const value = (marketVersion || "").trim();
    if (!value) {
      setMarketVersionMode("all");
      setCustomVersion("");
      return;
    }
    if (value.toLowerCase() === "latest") {
      setMarketVersionMode("latest");
      setCustomVersion("");
      return;
    }
    setMarketVersionMode("custom");
    setCustomVersion(value);
  }, [marketVersion]);

  const handleVersionModeChange = (mode: "all" | "latest" | "custom") => {
    setMarketVersionMode(mode);
    if (mode === "all") {
      setCustomVersion("");
      onMarketVersionChange("");
      return;
    }
    if (mode === "latest") {
      setCustomVersion("");
      onMarketVersionChange("latest");
      return;
    }
    // Custom mode starts empty and waits for valid semantic numeric version input.
    setCustomVersion("");
    onMarketVersionChange("");
  };

  const handleCustomVersionChange = (value: string) => {
    setCustomVersion(value);
    const trimmed = value.trim();
    if (!trimmed) {
      onMarketVersionChange("");
      return;
    }
    if (VERSION_PATTERN.test(trimmed)) {
      onMarketVersionChange(trimmed);
    }
  };

  if (!open) {
    return null;
  }

  return (
    <Modal
      open
      footer={null}
      closable
      maskClosable={false}
      centered
      width={addModalTab === MCP_TAB.MARKET ? 1200 : 900}
      onCancel={onClose}
      styles={{
        mask: { background: "rgba(15,23,42,0.6)", backdropFilter: "blur(2px)" },
        body: { padding: 0 },
      }}
    >
      <div>
        <div className="border-b border-slate-100 px-6 py-5">
          <div>
            <h2 className="text-2xl font-semibold text-slate-900">{t("mcpTools.addModal.title")}</h2>
          </div>
        </div>

        <div className="px-6 pt-4">
          <Segmented
            value={addModalTab}
            onChange={(value) => onAddModalTabChange(value as McpTab)}
            options={[
              { label: t("mcpTools.addModal.tabLocal"), value: MCP_TAB.LOCAL },
              { label: t("mcpTools.addModal.tabMarket"), value: MCP_TAB.MARKET },
            ]}
            className="h-9 rounded-full border border-slate-200 bg-slate-100 p-[2px] text-sm [&_.ant-segmented-group]:h-full [&_.ant-segmented-item]:rounded-full [&_.ant-segmented-item-label]:px-4 [&_.ant-segmented-item-label]:leading-[30px] [&_.ant-segmented-thumb]:rounded-full [&_.ant-segmented-thumb]:bg-white [&_.ant-segmented-thumb]:shadow-sm [&_.ant-segmented-thumb]:top-[2px] [&_.ant-segmented-thumb]:bottom-[2px]"
          />
        </div>

        {addModalTab === MCP_TAB.LOCAL ? (
          <>
            <div className="px-6 py-5 space-y-4">
              <label className="block text-sm text-slate-500">
                {t("mcpTools.addModal.name")}
                <Input
                  value={newServiceName}
                  onChange={(event) => onNewServiceNameChange(event.target.value)}
                  className="mt-2 w-full rounded-2xl"
                />
              </label>

              <label className="block text-sm text-slate-500">
                {t("mcpTools.addModal.description")}
                <Input
                  value={newServiceDesc}
                  onChange={(event) => onNewServiceDescChange(event.target.value)}
                  className="mt-2 w-full rounded-2xl"
                />
              </label>

              <label className="block text-sm text-slate-500">
                {t("mcpTools.addModal.serverType")}
                <Select
                  value={newServerType}
                  onChange={(value) => onNewServerTypeChange(value as McpServerType)}
                  className="mt-2 w-full"
                  options={[
                    { label: t("mcpTools.serverType.http"), value: MCP_SERVER_TYPE.HTTP },
                    { label: t("mcpTools.serverType.sse"), value: MCP_SERVER_TYPE.SSE },
                    { label: t("mcpTools.serverType.container"), value: MCP_SERVER_TYPE.CONTAINER },
                  ]}
                />
              </label>

              {newServerType === MCP_SERVER_TYPE.HTTP || newServerType === MCP_SERVER_TYPE.SSE ? (
                <div className="space-y-4">
                  <label className="block text-sm text-slate-500">
                    {t("mcpTools.addModal.serverUrl")}
                    <Input
                      value={newServiceUrl}
                      onChange={(event) => onNewServiceUrlChange(event.target.value)}
                      className="mt-2 w-full rounded-2xl"
                      placeholder="https://example.com/mcp"
                    />
                  </label>
                  <label className="block text-sm text-slate-500">
                    {t("mcpTools.addModal.bearerTokenOptional")}
                    <Input
                      value={newServiceAuthorizationToken}
                      onChange={(event) => onNewServiceAuthorizationTokenChange(event.target.value)}
                      className="mt-2 w-full rounded-2xl"
                      placeholder={t("mcpTools.addModal.bearerTokenPlaceholder")}
                    />
                  </label>
                </div>
              ) : (
                <div className="space-y-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div>
                    <p className="text-sm text-slate-700">{t("mcpTools.addModal.uploadImageTitle")}</p>
                    <p className="mt-1 text-xs text-slate-500">{t("mcpTools.addModal.uploadImageDesc")}</p>
                    <div className="mt-2">
                      <Upload
                        fileList={containerUploadFileList}
                        onChange={({ fileList }) => onContainerUploadFileListChange(fileList)}
                        beforeUpload={() => false}
                        accept=".tar"
                        maxCount={1}
                      >
                        <Button className="rounded-full" type="default">{t("mcpTools.addModal.selectImage")}</Button>
                      </Upload>
                    </div>
                  </div>

                  <label className="block text-sm text-slate-500">
                    {t("mcpTools.addModal.containerConfig")}
                    <Input.TextArea
                      value={containerConfigJson}
                      onChange={(event) => onContainerConfigJsonChange(event.target.value)}
                      rows={5}
                      placeholder={t("mcpTools.addModal.containerConfigPlaceholder")}
                      className="mt-2"
                    />
                  </label>

                  <div className="grid grid-cols-2 gap-4">
                    <label className="block text-sm text-slate-500">
                      {t("mcpTools.addModal.containerPort")}
                      <InputNumber
                        value={containerPort}
                        onChange={(value) => onContainerPortChange(value === null ? undefined : value)}
                        min={1}
                        max={65535}
                        controls={false}
                        className="mt-2 w-full"
                        placeholder={t("mcpTools.addModal.containerPortPlaceholder")}
                      />
                    </label>
                    <label className="block text-sm text-slate-500">
                      {t("mcpTools.addModal.containerServiceName")}
                      <Input
                        value={containerServiceName}
                        onChange={(event) => onContainerServiceNameChange(event.target.value)}
                        className="mt-2 w-full rounded-2xl"
                        placeholder={t("mcpTools.addModal.containerServiceNamePlaceholder")}
                      />
                    </label>
                  </div>
                </div>
              )}

              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{t("mcpTools.addModal.tags")}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {newTagDrafts.map((tag, index) => (
                    <span key={`${tag}-${index}`} className="relative inline-flex">
                      <Tag className="rounded-full px-3 py-1 m-0 leading-none">{tag}</Tag>
                      <button
                        type="button"
                        onClick={() => onRemoveNewTag(index)}
                        className="absolute top-0 right-0 -translate-y-1/2 translate-x-1/2 flex h-4 w-4 items-center justify-center rounded-full bg-slate-200 text-[10px] text-slate-500 transition hover:bg-slate-300 hover:text-slate-700"
                        aria-label={t("mcpTools.addModal.removeTagAria", { tag })}
                      >
                        x
                      </button>
                    </span>
                  ))}
                  <Input
                    size="small"
                    value={newTagInputValue}
                    onChange={(event) => onNewTagInputChange(event.target.value)}
                    onPressEnter={onAddNewTag}
                    onBlur={onAddNewTag}
                    placeholder={t("mcpTools.addModal.tagInputPlaceholder")}
                    className="w-40 rounded-full"
                  />
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 border-t border-slate-100 px-6 py-4">
              <Button type="primary" className="rounded-full" onClick={onSaveAndAdd} loading={addingService}>
                {t("mcpTools.addModal.saveAndAdd")}
              </Button>
            </div>
          </>
        ) : (
          <div className="px-6 py-5 space-y-5">
            <div className="flex items-center gap-3">
              <Input
                value={marketSearchValue}
                onChange={(event) => onMarketSearchChange(event.target.value)}
                placeholder={t("mcpTools.market.searchPlaceholder")}
                size="large"
                className="w-full rounded-2xl"
              />
              <Button className="rounded-full" onClick={onRefreshMarket} loading={marketLoading}>
                {t("common.refresh")}
              </Button>
              <div className="whitespace-nowrap rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                {t("mcpTools.market.pageResult", { page: marketPage, count: filteredMarketServices.length })}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <label className="text-xs text-slate-500">
                {t("mcpTools.market.versionFilter")}
                <Select
                  value={marketVersionMode}
                  onChange={(value) => handleVersionModeChange(value as "all" | "latest" | "custom")}
                  className="mt-1 w-full"
                  options={[
                    { label: t("mcpTools.market.versionAll"), value: "all" },
                    { label: t("mcpTools.market.versionLatest"), value: "latest" },
                    { label: t("mcpTools.market.versionCustom"), value: "custom" },
                  ]}
                />
              </label>
              <label className="text-xs text-slate-500">
                {t("mcpTools.market.updatedSince")}
                <DatePicker
                  value={updatedSinceDateValue}
                  onChange={(value) => onMarketUpdatedSinceChange(value ? value.toISOString() : "")}
                  showTime
                  allowClear
                  className="mt-1 w-full"
                  placeholder={t("mcpTools.market.updatedSincePlaceholder")}
                />
              </label>
              <div className="flex items-end justify-between rounded-2xl border border-slate-200 bg-white px-3 py-2">
                <div>
                  <p className="text-xs text-slate-500">{t("mcpTools.market.includeDeleted")}</p>
                  <p className="text-xs text-slate-400">{t("mcpTools.market.includeDeletedDesc")}</p>
                </div>
                <Switch checked={marketIncludeDeleted} onChange={onMarketIncludeDeletedChange} />
              </div>
            </div>

            {marketVersionMode === "custom" ? (
              <label className="block text-xs text-slate-500">
                {t("mcpTools.market.customVersion")}
                <Input
                  value={customVersion}
                  onChange={(event) => handleCustomVersionChange(event.target.value)}
                  placeholder={t("mcpTools.market.customVersionPlaceholder")}
                  status={customVersionError ? "error" : ""}
                  className="mt-1 rounded-xl"
                />
                {customVersionError ? (
                  <span className="mt-1 inline-block text-xs text-rose-500">{t("mcpTools.market.customVersionError")}</span>
                ) : null}
              </label>
            ) : null}

            {marketLoading ? (
              <div className="rounded-3xl border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-slate-500">
                {t("mcpTools.market.loading")}
              </div>
            ) : filteredMarketServices.length === 0 ? (
              <div className="rounded-3xl border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-slate-500">
                {t("mcpTools.market.empty")}
              </div>
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5 max-h-[55vh] overflow-y-auto pr-1">
                  {filteredMarketServices.map((service, index) => (
                    <div
                      key={`${service.name}::${service.version || "-"}::${service.publishedAt || "-"}::${index}`}
                      onClick={() => onSelectMarketService(service)}
                      className="group rounded-3xl border border-slate-200/80 bg-white p-5 shadow-sm transition hover:-translate-y-1 hover:shadow-lg"
                    >
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="min-w-0 break-all text-base font-semibold text-slate-900">{service.name}</h3>
                      <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold ${getStatusClassName(service.status)}`}>
                        {getStatusText(service.status)}
                      </span>
                    </div>

                    <div className="mt-2 flex items-center gap-2">
                      <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-600">
                        {formatMarketVersion(service.version)}
                      </span>
                      <span className="text-xs text-slate-400">{formatMarketDate(service.publishedAt)}</span>
                    </div>

                    <p className="mt-3 line-clamp-2 min-h-[40px] text-sm text-slate-600">{service.description}</p>

                      <div className="mt-4 flex items-center justify-end gap-2">
                        <Button
                          size="small"
                          type="primary"
                          className="rounded-full"
                          onClick={(event) => {
                            event.stopPropagation();
                            onQuickAddFromMarket(service);
                          }}
                        >
                          {t("mcpTools.market.quickAdd")}
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-3">
                  <Button
                    className="rounded-full"
                    onClick={onPrevMarketPage}
                    disabled={!hasPrevMarketPage || marketLoading}
                  >
                    {t("mcpTools.market.prevPage")}
                  </Button>
                  <Button
                    className="rounded-full"
                    onClick={onNextMarketPage}
                    disabled={!hasNextMarketPage || marketLoading}
                  >
                    {t("mcpTools.market.nextPage")}
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {selectedMarketService ? (
          <Modal
            open
            footer={null}
            closable
            maskClosable={false}
            centered
            width={900}
            onCancel={() => onSelectMarketService(null)}
            styles={{
              mask: { background: "rgba(15,23,42,0.4)" },
              body: { padding: 0 },
            }}
          >
            <div>
              <div className="border-b border-slate-100 px-6 py-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="break-all text-2xl font-semibold text-slate-900">{selectedMarketService.name}</h3>
                    <p className="mt-1 text-sm text-slate-500">{formatMarketVersion(selectedMarketService.version)}</p>
                  </div>
                  <span className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${getStatusClassName(selectedMarketService.status)}`}>
                    {getStatusText(selectedMarketService.status)}
                  </span>
                </div>
              </div>

              <div className="px-6 py-5 space-y-4">
                <p className="text-sm text-slate-700">{selectedMarketService.description}</p>

                <p className="text-xs text-slate-500">{formatMarketDate(selectedMarketService.publishedAt)}</p>

                <div className="grid grid-cols-1 gap-3 rounded-2xl border border-slate-100 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                  <div className="flex flex-wrap gap-2">
                    <span className="text-slate-500">{t("mcpTools.market.title")}</span>
                    <span className="font-medium text-slate-900">{selectedMarketService.title || "-"}</span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <span className="text-slate-500">{t("mcpTools.market.website")}</span>
                    {selectedMarketService.websiteUrl ? (
                      <a
                        href={selectedMarketService.websiteUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="break-all font-medium text-sky-700 hover:text-sky-600"
                      >
                        {selectedMarketService.websiteUrl}
                      </a>
                    ) : (
                      <span className="font-medium text-slate-900">-</span>
                    )}
                  </div>
                </div>

                <div className="space-y-2">
                  <p className="text-sm font-semibold text-slate-900">{t("mcpTools.market.remotes")}</p>
                  {selectedMarketService.remotes.length === 0 ? (
                    <p className="text-sm text-slate-500">{t("mcpTools.market.noRemotes")}</p>
                  ) : (
                    <div className="space-y-2">
                      {selectedMarketService.remotes.map((remote, index) => (
                        <div key={`${selectedMarketService.name}-${remote.url}-${index}`} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm">
                          <p className="font-medium text-slate-900">{remote.type || t("mcpTools.market.remoteFallback")}</p>
                          <p className="break-all text-slate-600">{remote.url}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="flex items-center justify-end gap-3 border-t border-slate-100 px-6 py-4">
                <Button className="rounded-full" onClick={() => setShowServerJsonModal(true)}>
                  {t("mcpTools.market.viewServerJson")}
                </Button>
                <Button type="primary" className="rounded-full" onClick={() => onQuickAddFromMarket(selectedMarketService)}>
                  {t("mcpTools.market.quickAdd")}
                </Button>
              </div>
            </div>
          </Modal>
        ) : null}

        {selectedMarketService && showServerJsonModal ? (
          <Modal
            open
            footer={null}
            closable
            centered
            width={960}
            onCancel={() => setShowServerJsonModal(false)}
            title={t("mcpTools.market.serverJsonTitle", { name: selectedMarketService.name })}
          >
            <pre className="max-h-[65vh] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">
              {serverJsonPretty}
            </pre>
          </Modal>
        ) : null}
      </div>
    </Modal>
  );
}
