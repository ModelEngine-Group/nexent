import { useEffect, useMemo, useState } from "react";
import { DatePicker, Input, Select, Switch } from "antd";
import { LinkOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { VERSION_PATTERN } from "@/lib/mcpTools";

interface Props {
  registrySearchValue: string;
  registryPage: number;
  resultCount: number;
  registryVersion: string;
  registryUpdatedSince: string;
  registryIncludeDeleted: boolean;
  onRegistrySearchChange: (value: string) => void;
  onRegistryVersionChange: (value: string) => void;
  onRegistryUpdatedSinceChange: (value: string) => void;
  onRegistryIncludeDeletedChange: (value: boolean) => void;
  t: (key: string, params?: Record<string, unknown>) => string;
}

export default function McpRegistryToolbar({
  registrySearchValue,
  registryPage,
  resultCount,
  registryVersion,
  registryUpdatedSince,
  registryIncludeDeleted,
  onRegistrySearchChange,
  onRegistryVersionChange,
  onRegistryUpdatedSinceChange,
  onRegistryIncludeDeletedChange,
  t,
}: Props) {
  const [registryVersionMode, setRegistryVersionMode] = useState<"all" | "latest" | "custom">("latest");
  const [customVersion, setCustomVersion] = useState("");

  const updatedSinceDateValue = useMemo(() => {
    if (!registryUpdatedSince) return null;
    const parsed = dayjs(registryUpdatedSince);
    return parsed.isValid() ? parsed : null;
  }, [registryUpdatedSince]);

  const customVersionError = customVersion.trim().length > 0 && !VERSION_PATTERN.test(customVersion.trim());

  useEffect(() => {
    const value = (registryVersion || "").trim();
    if (!value) {
      setRegistryVersionMode("all");
      setCustomVersion("");
      return;
    }
    if (value.toLowerCase() === "latest") {
      setRegistryVersionMode("latest");
      setCustomVersion("");
      return;
    }
    setRegistryVersionMode("custom");
    setCustomVersion(value);
  }, [registryVersion]);

  const handleVersionModeChange = (mode: "all" | "latest" | "custom") => {
    setRegistryVersionMode(mode);
    if (mode === "all") {
      setCustomVersion("");
      onRegistryVersionChange("");
      return;
    }
    if (mode === "latest") {
      setCustomVersion("");
      onRegistryVersionChange("latest");
      return;
    }
    setCustomVersion("");
    onRegistryVersionChange("");
  };

  const handleCustomVersionChange = (value: string) => {
    setCustomVersion(value);
    const trimmed = value.trim();
    if (!trimmed) {
      onRegistryVersionChange("");
      return;
    }
    if (VERSION_PATTERN.test(trimmed)) {
      onRegistryVersionChange(trimmed);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <Input
          value={registrySearchValue}
          onChange={(event) => onRegistrySearchChange(event.target.value)}
          placeholder={t("mcpTools.registry.searchPlaceholder")}
          size="large"
          className="w-full rounded-2xl"
        />
        <div className="whitespace-nowrap rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
          {t("mcpTools.registry.pageResult", { page: registryPage, count: resultCount })}
        </div>
        <a
          href="https://www.modelscope.cn/mcp"
          target="_blank"
          rel="noreferrer"
          className="inline-flex h-9 items-center gap-2 whitespace-nowrap rounded-full border border-slate-200 bg-white px-3 text-xs font-medium text-slate-600 shadow-sm transition hover:border-slate-300 hover:text-slate-800"
        >
          <LinkOutlined className="text-[12px]" />
          <span>魔搭 MCP 广场</span>
        </a>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <label className="text-xs text-slate-500">
          {t("mcpTools.registry.versionFilter")}
          <Select
            value={registryVersionMode}
            onChange={(value) => handleVersionModeChange(value)}
            className="mt-1 w-full"
            options={[
              { label: t("mcpTools.registry.versionAll"), value: "all" },
              { label: t("mcpTools.registry.versionLatest"), value: "latest" },
              { label: t("mcpTools.registry.versionCustom"), value: "custom" },
            ]}
          />
        </label>
        <label className="text-xs text-slate-500">
          {t("mcpTools.registry.updatedSince")}
          <DatePicker
            value={updatedSinceDateValue}
            onChange={(value) => onRegistryUpdatedSinceChange(value ? value.toISOString() : "")}
            showTime
            allowClear
            className="mt-1 w-full"
            placeholder={t("mcpTools.registry.updatedSincePlaceholder")}
          />
        </label>
        <div className="flex items-end justify-between rounded-2xl border border-slate-200 bg-white px-3 py-2">
          <div>
            <p className="text-xs text-slate-500">{t("mcpTools.registry.includeDeleted")}</p>
            <p className="text-xs text-slate-400">{t("mcpTools.registry.includeDeletedDesc")}</p>
          </div>
          <Switch checked={registryIncludeDeleted} onChange={onRegistryIncludeDeletedChange} />
        </div>
      </div>

      {registryVersionMode === "custom" ? (
        <label className="block text-xs text-slate-500">
          {t("mcpTools.registry.customVersion")}
          <Input
            value={customVersion}
            onChange={(event) => handleCustomVersionChange(event.target.value)}
            placeholder={t("mcpTools.registry.customVersionPlaceholder")}
            status={customVersionError ? "error" : ""}
            className="mt-1 rounded-xl"
          />
          {customVersionError ? (
            <span className="mt-1 inline-block text-xs text-rose-500">{t("mcpTools.registry.customVersionError")}</span>
          ) : null}
        </label>
      ) : null}
    </div>
  );
}
