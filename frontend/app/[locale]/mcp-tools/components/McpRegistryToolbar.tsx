import { useEffect, useMemo, useState } from "react";
import { DatePicker, Dropdown, Input, Select, Switch } from "antd";
import type { MenuProps } from "antd";
import dayjs from "dayjs";
import { useTranslation } from "react-i18next";
import { VERSION_PATTERN } from "@/const/mcpTools";

interface McpRegistryToolbarProps {
  search: string;
  version: string;
  updatedSince: string;
  includeDeleted: boolean;
  page: number;
  resultCount: number;
  onSearchChange: (value: string) => void;
  onVersionChange: (value: string) => void;
  onUpdatedSinceChange: (value: string) => void;
  onIncludeDeletedChange: (value: boolean) => void;
}

export default function McpRegistryToolbar({
  search,
  version,
  updatedSince,
  includeDeleted,
  page,
  resultCount,
  onSearchChange,
  onVersionChange,
  onUpdatedSinceChange,
  onIncludeDeletedChange,
}: McpRegistryToolbarProps) {
  const { t } = useTranslation("common");
  const [versionMode, setVersionMode] = useState<"all" | "latest" | "custom">(
    "latest"
  );
  const [customVersion, setCustomVersion] = useState("");

  const marketMenuItems: MenuProps["items"] = [
    {
      key: "modelscope",
      label: (
        <a
          href="https://www.modelscope.cn/mcp"
          target="_blank"
          rel="noreferrer"
          className="text-[#1677ff] hover:underline"
        >
          {t("mcpTools.registry.market.modelscope")}
        </a>
      ),
    },
    {
      key: "mcp-so",
      label: (
        <a
          href="https://mcp.so/"
          target="_blank"
          rel="noreferrer"
          className="text-[#1677ff] hover:underline"
        >
          {t("mcpTools.registry.market.mcpso")}
        </a>
      ),
    },
  ];

  const updatedSinceDateValue = useMemo(() => {
    if (!updatedSince) return null;
    const parsed = dayjs(updatedSince);
    return parsed.isValid() ? parsed : null;
  }, [updatedSince]);

  const customVersionError =
    customVersion.trim().length > 0 &&
    !VERSION_PATTERN.test(customVersion.trim());

  useEffect(() => {
    const value = (version || "").trim();
    if (!value) {
      setVersionMode("all");
      setCustomVersion("");
      return;
    }
    if (value.toLowerCase() === "latest") {
      setVersionMode("latest");
      setCustomVersion("");
      return;
    }
    setVersionMode("custom");
    setCustomVersion(value);
  }, [version]);

  const handleVersionModeChange = (mode: "all" | "latest" | "custom") => {
    setVersionMode(mode);
    if (mode === "all") {
      setCustomVersion("");
      onVersionChange("");
      return;
    }
    if (mode === "latest") {
      setCustomVersion("");
      onVersionChange("latest");
      return;
    }
    setCustomVersion("");
    onVersionChange("");
  };

  const handleCustomVersionChange = (value: string) => {
    setCustomVersion(value);
    const trimmed = value.trim();
    if (!trimmed) {
      onVersionChange("");
      return;
    }
    if (VERSION_PATTERN.test(trimmed)) {
      onVersionChange(trimmed);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <Input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder={t("mcpTools.registry.searchPlaceholder")}
          size="large"
          className="w-full rounded-2xl"
        />
        <div className="whitespace-nowrap rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
          {t("mcpTools.registry.pageResult", { page, count: resultCount })}
        </div>
        <Dropdown
          menu={{ items: marketMenuItems }}
          trigger={["hover"]}
          placement="bottomRight"
        >
          <span className="cursor-pointer whitespace-nowrap text-sm font-medium text-[#1677ff] hover:underline">
            {t("mcpTools.registry.market.more")}
          </span>
        </Dropdown>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <label className="text-xs text-slate-500">
          {t("mcpTools.registry.versionFilter")}
          <Select
            value={versionMode}
            onChange={handleVersionModeChange}
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
            onChange={(value) =>
              onUpdatedSinceChange(value ? value.toISOString() : "")
            }
            showTime
            allowClear
            className="mt-1 w-full"
            placeholder={t("mcpTools.registry.updatedSincePlaceholder")}
          />
        </label>
        <div className="flex items-end justify-between rounded-2xl border border-slate-200 bg-white px-3 py-2">
          <div>
            <p className="text-xs text-slate-500">
              {t("mcpTools.registry.includeDeleted")}
            </p>
            <p className="text-xs text-slate-400">
              {t("mcpTools.registry.includeDeletedDesc")}
            </p>
          </div>
          <Switch checked={includeDeleted} onChange={onIncludeDeletedChange} />
        </div>
      </div>

      {versionMode === "custom" ? (
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
            <span className="mt-1 inline-block text-xs text-rose-500">
              {t("mcpTools.registry.customVersionError")}
            </span>
          ) : null}
        </label>
      ) : null}
    </div>
  );
}
