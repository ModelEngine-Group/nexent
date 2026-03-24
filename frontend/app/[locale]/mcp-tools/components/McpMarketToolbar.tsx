import { useEffect, useMemo, useState } from "react";
import { DatePicker, Input, Select, Switch } from "antd";
import dayjs from "dayjs";
import { VERSION_PATTERN } from "@/lib/mcpTools";

interface Props {
  marketSearchValue: string;
  marketPage: number;
  resultCount: number;
  marketVersion: string;
  marketUpdatedSince: string;
  marketIncludeDeleted: boolean;
  onMarketSearchChange: (value: string) => void;
  onMarketVersionChange: (value: string) => void;
  onMarketUpdatedSinceChange: (value: string) => void;
  onMarketIncludeDeletedChange: (value: boolean) => void;
  t: (key: string, params?: Record<string, unknown>) => string;
}

export default function McpMarketToolbar({
  marketSearchValue,
  marketPage,
  resultCount,
  marketVersion,
  marketUpdatedSince,
  marketIncludeDeleted,
  onMarketSearchChange,
  onMarketVersionChange,
  onMarketUpdatedSinceChange,
  onMarketIncludeDeletedChange,
  t,
}: Props) {
  const [marketVersionMode, setMarketVersionMode] = useState<"all" | "latest" | "custom">("latest");
  const [customVersion, setCustomVersion] = useState("");

  const updatedSinceDateValue = useMemo(() => {
    if (!marketUpdatedSince) return null;
    const parsed = dayjs(marketUpdatedSince);
    return parsed.isValid() ? parsed : null;
  }, [marketUpdatedSince]);

  const customVersionError = customVersion.trim().length > 0 && !VERSION_PATTERN.test(customVersion.trim());

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

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <Input
          value={marketSearchValue}
          onChange={(event) => onMarketSearchChange(event.target.value)}
          placeholder={t("mcpTools.market.searchPlaceholder")}
          size="large"
          className="w-full rounded-2xl"
        />
        <div className="whitespace-nowrap rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
          {t("mcpTools.market.pageResult", { page: marketPage, count: resultCount })}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <label className="text-xs text-slate-500">
          {t("mcpTools.market.versionFilter")}
          <Select
            value={marketVersionMode}
            onChange={(value) => handleVersionModeChange(value)}
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
    </div>
  );
}
