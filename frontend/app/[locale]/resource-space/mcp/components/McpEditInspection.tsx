// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useRef, useState } from "react";
import { App, Button, Collapse, Empty, Spin } from "antd";
import { ChevronDown, Copy, Wrench } from "lucide-react";
import { useTranslation } from "react-i18next";
import { McpContainerLogOutput } from "@/components/mcp/McpContainerLogsModal";
import type { McpTool } from "@/types/agentConfig";

const codeStyle =
  "mcp-edit-code m-0 overflow-auto bg-muted/40 px-5 py-4 font-mono text-body-1 leading-5 text-foreground";
const previewStyle =
  "@container overflow-hidden rounded-lg border border-border bg-background";
const previewHeaderStyle =
  "flex h-10 items-center justify-between gap-2 border-b border-border px-3 text-body-2 font-medium text-foreground";

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
  const [expanded, setExpanded] = useState<string[]>(["server-json"]);
  const [showAllTools, setShowAllTools] = useState(false);
  const inspectionRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (active) void onLoadTools();
  }, [active, onLoadTools]);

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
    <span className="inline-flex items-center gap-2 text-body-2 leading-[22px] text-foreground">
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
      onChange={setExpanded}
      items={[
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

  const visibleTools = showAllTools ? tools : tools.slice(0, 4);
  const hiddenToolCount = Math.max(0, tools.length - 4);

  return (
    <div ref={inspectionRef} className="space-y-6">
      <section
        className="space-y-3"
        aria-labelledby="mcp-edit-tools"
      >
        <div>
          <h3 id="mcp-edit-tools" className="text-body-2 font-semibold">
            {t("mcpTools.detail.tools")}
          </h3>
          <p className="text-xs text-muted-foreground">
            {t("mcpTools.editDetail.toolsHint")}
          </p>
        </div>
        {loadingTools ? (
          <div className="flex justify-center py-3" role="status">
            <Spin aria-label={t("mcpConfig.toolsList.loading")} />
          </div>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              {t("mcpTools.editDetail.toolsFound", { count: tools.length })}
            </p>
            {tools.length > 0 ? (
              <ul className="space-y-2">
                {visibleTools.map((tool) => (
                  <li
                    key={tool.name}
                    className="flex min-w-0 items-start gap-2 rounded border border-border p-2.5"
                  >
                    <Wrench
                      size={14}
                      className="mt-0.5 shrink-0 text-primary"
                      aria-hidden
                    />
                    <div className="min-w-0">
                      <span className="break-all font-mono text-xs">
                        {tool.name}
                      </span>
                      {tool.description && (
                        <p className="mt-1 whitespace-pre-wrap break-words text-xs text-muted-foreground">
                          {tool.description}
                        </p>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("mcpConfig.toolsList.empty")}
              </p>
            )}
            {hiddenToolCount > 0 && (
              <Button
                type="link"
                size="small"
                className="!px-0"
                aria-expanded={showAllTools}
                onClick={() => setShowAllTools((current) => !current)}
              >
                {showAllTools
                  ? t("mcpTools.editDetail.showFewerTools")
                  : t("mcpTools.editDetail.showMoreTools", {
                      count: hiddenToolCount,
                    })}
              </Button>
            )}
          </>
        )}
      </section>
      {(serverJson || containerConfig || showLogs) && (
        <section
          className="space-y-3"
          aria-labelledby="mcp-edit-advanced"
        >
          <div>
            <h3 id="mcp-edit-advanced" className="text-body-2 font-semibold">
              {t("mcpTools.editDetail.advanced")}
            </h3>
            <p className="text-xs text-muted-foreground">
              {t("mcpTools.editDetail.advancedHint")}
            </p>
          </div>
          {sections}
        </section>
      )}
    </div>
  );
}
