import { useEffect, useMemo, useState } from "react";
import { DatePicker, Dropdown, Input, Select, Switch } from "antd";
import type { MenuProps } from "antd";
import dayjs from "dayjs";
import { useTranslation } from "react-i18next";
import { McpVersionFilterMode } from "@/const/mcpTools";

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

/**
 * Two-line toolbar for the registry browser:
 *   row 1 — search input + 3 compact filters
 *   row 2 — paginated result count + "more markets" dropdown
 */
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
  const [versionMode, setVersionMode] = useState<McpVersionFilterMode>(
    McpVersionFilterMode.LATEST
  );

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

  useEffect(() => {
    const value = (version || "").trim().toLowerCase();
    if (!value) setVersionMode(McpVersionFilterMode.ALL);
    else if (value === "latest") setVersionMode(McpVersionFilterMode.LATEST);
    else setVersionMode(McpVersionFilterMode.LATEST);
  }, [version]);

  const handleVersionModeChange = (mode: McpVersionFilterMode) => {
    setVersionMode(mode);
    onVersionChange(mode === McpVersionFilterMode.LATEST ? "latest" : "");
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
        <Input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder={t("mcpTools.registry.searchPlaceholder")}
          allowClear
          className="h-9 rounded-md border border-slate-200 text-sm lg:flex-1"
        />
        <div className="flex flex-wrap gap-2 lg:flex-none">
          <Select
            value={versionMode}
            onChange={handleVersionModeChange}
            className="h-9 min-w-[120px] flex-1 rounded-md border border-slate-200 text-sm lg:flex-none lg:w-32"
            popupMatchSelectWidth={false}
            options={[
              {
                label: t("mcpTools.registry.versionAll"),
                value: McpVersionFilterMode.ALL,
              },
              {
                label: t("mcpTools.registry.versionLatest"),
                value: McpVersionFilterMode.LATEST,
              },
            ]}
          />
          <DatePicker
            value={updatedSinceDateValue}
            onChange={(value) =>
              onUpdatedSinceChange(value ? value.toISOString() : "")
            }
            allowClear
            className="h-9 min-w-[160px] flex-1 rounded-md border border-slate-200 text-sm lg:flex-none lg:w-44"
            placeholder={t("mcpTools.registry.updatedSincePlaceholder")}
          />
          <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-1.5">
            <span className="text-xs text-slate-500">
              {t("mcpTools.registry.includeDeleted")}
            </span>
            <Switch
              size="small"
              checked={includeDeleted}
              onChange={onIncludeDeletedChange}
            />
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-400">
          {t("mcpTools.registry.pageResult", { page, count: resultCount })}
        </span>
        <Dropdown
          menu={{ items: marketMenuItems }}
          trigger={["hover"]}
          placement="bottomRight"
        >
          <span className="cursor-pointer text-xs font-medium text-[#1677ff] hover:underline">
            {t("mcpTools.registry.market.more")}
          </span>
        </Dropdown>
      </div>
    </div>
  );
}
