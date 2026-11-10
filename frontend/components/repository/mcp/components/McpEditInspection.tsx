// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useRef, useState } from "react";
import { App, Button, Collapse, Empty, Spin } from "antd";
import { ChevronDown, Copy, Wrench } from "lucide-react";
import { useTranslation } from "react-i18next";
import { McpContainerLogOutput } from "@/components/mcp/McpContainerLogsModal";
import type { McpTool } from "@/types/agentConfig";

const codeStyle =
  "mcp-edit-code m-0 overflow-auto bg-[#191919]/[0.03] px-5 py-4 font-mono text-xs leading-5 text-[#191919]";
const previewStyle =
  "@container overflow-hidden rounded border border-[#DFDFDF] bg-white";
const previewHeaderStyle =
  "flex h-8 items-center justify-between gap-2 border-b border-[#DFDFDF] px-3 text-sm leading-[22px] text-[#191919]";

function JsonPreview({ name, json }: { name: string; json: string }) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  return (
    <div className={previewStyle}>
      <div className={previewHeaderStyle}>
        <span className="truncate" title={name}>
          {name}
        </span>
        <Button
          type="text"
          size="small"
          aria-label={t("common.copy")}
          title={t("common.copy")}
          icon={<Copy size={16} aria-hidden />}
          className="shrink-0 !text-[#191919]/70 hover:!bg-transparent"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(json);
              message.success(t("common.copied"));
            } catch {
              message.error(t("agentUsageGuide.copyFailed"));
            }
          }}
        />
      </div>
      <pre className={codeStyle}>{json}</pre>
    </div>
  );
}

interface McpEditInspectionProps {
  name: string;
  tools: McpTool[];
  loadingTools: boolean;
  onLoadTools: () => Promise<void>;
  serverJson?: string;
  containerConfig?: string;
  showLogs: boolean;
  containerId?: string;
  active: boolean;
}

export default function McpEditInspection({
  name,
  tools,
  loadingTools,
  onLoadTools,
  serverJson,
  containerConfig,
  showLogs,
  containerId,
  active,
}: McpEditInspectionProps) {
  const { t } = useTranslation("common");
  const [expanded, setExpanded] = useState<string[]>([]);
  const inspectionRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const inspection = inspectionRef.current;
    if (!inspection) return;

    const updateOverflow = () => {
      inspection
        .querySelectorAll<HTMLPreElement>(".mcp-edit-code")
        .forEach((preview) => {
          preview.toggleAttribute(
            "data-overflow-y",
            preview.scrollHeight > preview.clientHeight
          );
        });
    };
    const resizeObserver = new ResizeObserver(updateOverflow);
    const mutationObserver = new MutationObserver(updateOverflow);
    resizeObserver.observe(inspection);
    mutationObserver.observe(inspection, {
      childList: true,
      characterData: true,
      subtree: true,
    });
    updateOverflow();

    return () => {
      resizeObserver.disconnect();
      mutationObserver.disconnect();
    };
  }, []);

  const sectionLabel = (key: string, label: string) => (
    <span className="inline-flex items-center gap-2 text-sm leading-[22px] text-[#191919]">
      {label}
      <ChevronDown
        size={12}
        className={expanded.includes(key) ? "rotate-180" : undefined}
        aria-hidden
      />
    </span>
  );

  const sections = (
    <Collapse
      ghost
      className="flex flex-col gap-4"
      classNames={{
        header: "!bg-transparent !p-0 !shadow-none hover:!bg-transparent",
        body: "!p-0 !pt-2",
      }}
      activeKey={expanded}
      onChange={(keys) => {
        if (
          keys.includes("tools") &&
          !expanded.includes("tools") &&
          !loadingTools
        ) {
          void onLoadTools();
        }
        setExpanded(keys);
      }}
      items={[
        {
          key: "tools",
          showArrow: false,
          label: sectionLabel("tools", t("mcpTools.detail.tools")),
          children: loadingTools ? (
            <div className="flex justify-center py-3" role="status">
              <Spin aria-label={t("mcpConfig.toolsList.loading")} />
            </div>
          ) : tools.length ? (
            <Collapse
              ghost
              expandIconPlacement="end"
              expandIcon={({ isActive }) => (
                <ChevronDown
                  size={12}
                  aria-hidden
                  className={isActive ? "rotate-180" : undefined}
                />
              )}
              className="flex flex-col gap-2"
              classNames={{
                header:
                  "!min-h-8 !items-center !gap-2 !bg-transparent !px-3 !py-1 !shadow-none hover:!bg-transparent",
                title: "!min-w-0",
                body: "!px-3 !pt-0 !pb-2",
              }}
              items={tools.map((tool) => ({
                key: tool.name,
                className:
                  "group/tool !rounded !border !border-[#D8D8D8] !bg-transparent",
                label: (
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="flex size-5 shrink-0 items-center justify-center text-[#0067D1]">
                      <Wrench size={12} aria-hidden />
                    </span>
                    <span
                      className="max-w-[45%] shrink-0 truncate text-sm leading-[22px] text-[#191919]"
                      title={tool.name}
                    >
                      {tool.name}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-xs leading-[18px] text-[#777777] group-[.ant-collapse-item-active]/tool:hidden">
                      {tool.description}
                    </span>
                  </span>
                ),
                children: (
                  <div className="text-xs leading-[18px] break-words whitespace-pre-wrap text-[#777777]">
                    {tool.description || "—"}
                  </div>
                ),
              }))}
            />
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("mcpConfig.toolsList.empty")}
            />
          ),
        },
        ...(serverJson
          ? [
              {
                key: "server-json",
                showArrow: false,
                label: sectionLabel(
                  "server-json",
                  t("mcpTools.detail.fullServerJson")
                ),
                children: <JsonPreview name="server.json" json={serverJson} />,
              },
            ]
          : []),
        ...(showLogs
          ? [
              {
                key: "logs",
                showArrow: false,
                label: sectionLabel("logs", t("mcpConfig.containerLogs.title")),
                children: containerId ? (
                  <div className={previewStyle}>
                    <div className={previewHeaderStyle}>
                      {containerId.slice(0, 12)}
                    </div>
                    <McpContainerLogOutput
                      open={active && expanded.includes("logs")}
                      containerId={containerId}
                      className={`${codeStyle} whitespace-pre-wrap break-words`}
                    />
                  </div>
                ) : (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={t("mcpConfig.containerList.empty")}
                  />
                ),
              },
            ]
          : []),
        ...(containerConfig
          ? [
              {
                key: "container-config",
                showArrow: false,
                label: sectionLabel(
                  "container-config",
                  t("mcpTools.detail.containerConfig")
                ),
                children: <JsonPreview name={name} json={containerConfig} />,
              },
            ]
          : []),
      ]}
    />
  );

  return <div ref={inspectionRef}>{sections}</div>;
}
