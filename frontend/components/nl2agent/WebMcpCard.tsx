"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Checkbox, message } from "antd";
import { Download } from "lucide-react";
import { useNl2AgentCardLifecycle } from "./useNl2AgentCardLifecycle";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";
import { WebMcpInstallConfiguration } from "./WebMcpInstallConfiguration";
import type { WebMcpCardItem } from "./webMcpTypes";

export type { WebMcpCardItem } from "./webMcpTypes";

export interface WebMcpCardProps {
  /** The draft agent_id used by the NL2AGENT MCP workflow endpoints. */
  agentId: number;
  recommendationBatchId: string;
  item: WebMcpCardItem;
  workflowRevision?: number;
}

const initialFieldValues = (
  option: NonNullable<WebMcpCardItem["install_options"]>[number] | undefined
) =>
  (option?.fields ?? []).reduce<Record<string, string>>((values, field) => {
    if (!field.secret && field.default != null)
      values[field.key] = String(field.default);
    return values;
  }, {});

const fieldValueIsValid = (
  field: NonNullable<
    NonNullable<WebMcpCardItem["install_options"]>[number]["fields"]
  >[number],
  value: string
) => {
  const normalized = value.trim();
  if (field.required && !normalized) return false;
  if (!normalized) return true;
  if (field.type === "json") {
    try {
      JSON.parse(normalized);
    } catch {
      return false;
    }
  }
  if (field.name === "port") {
    const port = Number(normalized);
    if (!Number.isInteger(port) || port < 1 || port > 65535) return false;
  }
  if (field.type === "url") {
    try {
      const url = new URL(normalized);
      if (
        !["http:", "https:"].includes(url.protocol) ||
        /\{[^{}]+\}/.test(normalized)
      )
        return false;
    } catch {
      return false;
    }
  }
  return true;
};

/** Renders the in-chat MCP configuration, installation, and tool-binding flow. */
export const WebMcpCard: React.FC<WebMcpCardProps> = ({
  agentId,
  recommendationBatchId,
  item,
  workflowRevision,
}) => {
  const workflowState = useNl2AgentWorkflow().sessionState;
  const lifecycle = useNl2AgentCardLifecycle(
    `web-mcp:${agentId}:${item.recommendation_id ?? item.name}`,
    workflowRevision
  );
  const { t } = useTranslation("common");
  const options = item.install_options ?? [];
  const [optionId, setOptionId] = React.useState(
    options[0]?.option_id ?? "remote"
  );
  const [fieldValues, setFieldValues] = React.useState<Record<string, string>>(
    () => initialFieldValues(options[0])
  );
  const [installError, setInstallError] = React.useState<string>();
  const [installed, setInstalled] = React.useState<{
    mcp_id: number;
    tools: Array<{ tool_id: number; name: string; description?: string }>;
  }>();
  const [selectedTools, setSelectedTools] = React.useState<number[]>([]);
  const [bound, setBound] = React.useState(false);
  const [skipped, setSkipped] = React.useState(false);
  const selectedOption = options.find(
    (option) => option.option_id === optionId
  );
  const fields = selectedOption?.fields ?? [];
  const fieldsAreValid = fields.every((field) =>
    fieldValueIsValid(field, String(fieldValues[field.key] ?? ""))
  );
  const canInstall = Boolean(
    item.recommendation_id &&
    selectedOption &&
    selectedOption.supported !== false &&
    fieldsAreValid
  );

  React.useEffect(() => {
    if (!item.recommendation_id) return;
    if (workflowState?.agent_id !== agentId) return;
    const workflow =
      workflowState.resource_review.mcp_workflows?.[item.recommendation_id];
    if (!workflow) return;
    if (workflow.option_id) setOptionId(workflow.option_id);
    if (workflow.status === "failed")
      setInstallError(workflow.error || "MCP installation failed.");
    if (
      workflow.mcp_id &&
      ["connected", "tools_bound", "binding_skipped"].includes(
        workflow.status || ""
      )
    ) {
      const tools = (workflow.discovered_tools ?? []).map((tool) => ({
        ...tool,
        description: tool.description ?? undefined,
      }));
      setInstalled({ mcp_id: workflow.mcp_id, tools });
      setSelectedTools(
        workflow.status === "tools_bound"
          ? (workflow.bound_tool_ids ?? [])
          : tools.map((tool) => tool.tool_id)
      );
      setBound(workflow.status === "tools_bound");
      setSkipped(workflow.status === "binding_skipped");
    }
  }, [agentId, item.recommendation_id, workflowState]);

  const chooseOption = (nextOptionId: string) => {
    setOptionId(nextOptionId);
    const nextOption = options.find(
      (option) => option.option_id === nextOptionId
    );
    setFieldValues(initialFieldValues(nextOption));
    setInstallError(undefined);
  };

  const install = async () => {
    if (!item.recommendation_id) {
      message.error(
        "This MCP recommendation cannot be installed from the current session."
      );
      return;
    }
    if (!selectedOption || selectedOption.supported === false) {
      message.error(
        selectedOption?.unsupported_reason ||
          "This MCP installation option is unsupported."
      );
      return;
    }
    const missing = fields.find(
      (field) => field.required && !String(fieldValues[field.key] ?? "").trim()
    );
    if (missing) {
      message.warning(`${missing.label || missing.name} is required.`);
      return;
    }
    for (const field of fields.filter(
      (candidate) => candidate.type === "json"
    )) {
      const value = String(fieldValues[field.key] ?? "").trim();
      if (!value) continue;
      try {
        JSON.parse(value);
      } catch {
        message.error(`${field.label || field.name} must be valid JSON.`);
        return;
      }
    }
    for (const field of fields.filter(
      (candidate) => candidate.name === "port"
    )) {
      const port = Number(fieldValues[field.key]);
      if (!Number.isInteger(port) || port < 1 || port > 65535) {
        message.error("Container port must be between 1 and 65535.");
        return;
      }
    }
    setInstallError(undefined);
    try {
      await lifecycle.execute(
        {
          action: "install_mcp",
          display_text: t("nl2agent.action.installMcp", {
            defaultValue: "MCP installed: {{name}}",
            name: item.name,
          }),
          payload: {
            recommendation_batch_id: recommendationBatchId,
            recommendation_id: item.recommendation_id!,
            option_id: optionId,
            config_values: {
              fields: fieldValues,
            },
          },
        },
        {
          onSuccess: (response) => {
            const result = response.result as {
              mcp_id: number;
              tools: Array<{
                tool_id: number;
                name: string;
                description?: string | null;
              }>;
            };
            setInstalled({
              mcp_id: result.mcp_id,
              tools: result.tools.map((tool) => ({
                ...tool,
                description: tool.description ?? undefined,
              })),
            });
            setSelectedTools(
              result.tools.map((tool: { tool_id: number }) => tool.tool_id)
            );
            message.success("MCP installed and connected.");
          },
          continueAfterSuccess: false,
        }
      );
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : "MCP installation failed.";
      setInstallError(errorMessage);
      message.error(errorMessage);
    }
  };

  const bind = async () => {
    if (!installed) return;
    try {
      await lifecycle.execute(
        {
          action: "bind_mcp_tools",
          display_text: t("nl2agent.action.bindMcpTools", {
            defaultValue: "MCP tools bound: {{count}}",
            count: selectedTools.length,
          }),
          payload: {
            recommendation_id: item.recommendation_id!,
            tool_ids: selectedTools,
          },
        },
        {
          onSuccess: () => {
            setBound(true);
            setInstallError(undefined);
            message.success("Selected MCP tools are bound to the draft.");
          },
          continueAfterSuccess: false,
        }
      );
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : "MCP tool binding failed.";
      setInstallError(errorMessage);
      message.error(errorMessage);
    }
  };

  const skip = async () => {
    if (!installed) return;
    try {
      await lifecycle.execute(
        {
          action: "skip_mcp_tools",
          display_text: t(
            "nl2agent.action.skipMcpTools",
            "MCP tool binding skipped"
          ),
          payload: { recommendation_id: item.recommendation_id! },
        },
        {
          onSuccess: () => {
            setSkipped(true);
            setInstallError(undefined);
            message.success("MCP tool binding skipped.");
          },
          continueAfterSuccess: false,
        }
      );
    } catch (error) {
      const errorMessage =
        error instanceof Error
          ? error.message
          : "Unable to skip MCP tool binding.";
      setInstallError(errorMessage);
      message.error(errorMessage);
    }
  };

  return (
    <div className="my-2 border border-sky-200 rounded-lg p-3 bg-sky-50/40">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm">{item.name}</span>
            {item.source && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-50 text-sky-700 border border-sky-200">
                {item.source}
              </span>
            )}
            {item.transport && (
              <span className="text-[10px] text-gray-500">
                {item.transport}
              </span>
            )}
            {typeof item.score === "number" && (
              <span className="text-[10px] text-gray-500">
                score: {item.score}
              </span>
            )}
          </div>
          {item.description && (
            <div className="text-xs text-gray-600 mt-1">{item.description}</div>
          )}
          {item.reason && (
            <div className="text-xs text-gray-400 mt-1 italic">
              {item.reason}
            </div>
          )}
        </div>
        {!installed && (
          <Button
            size="small"
            icon={<Download className="h-3.5 w-3.5" />}
            loading={lifecycle.pending}
            disabled={!canInstall || lifecycle.pending}
            onClick={install}
          >
            {t("nl2agent.webMcp.install", "Install")}
          </Button>
        )}
      </div>
      {!installed && (
        <WebMcpInstallConfiguration
          options={options}
          optionId={optionId}
          selectedOption={selectedOption}
          fieldValues={fieldValues}
          installError={installError}
          onOptionChange={chooseOption}
          onFieldChange={(key, value) =>
            setFieldValues((current) => ({ ...current, [key]: value }))
          }
        />
      )}
      {installed && (
        <div className="mt-3 border-t border-sky-100 pt-2">
          {installError ? (
            <Alert
              type="error"
              showIcon
              title="MCP action failed"
              description={installError}
            />
          ) : null}
          <div className="mb-1 text-xs font-medium">
            Connected. Choose tools to bind:
          </div>
          {installed.tools.map((tool) => (
            <Checkbox
              key={tool.tool_id}
              checked={selectedTools.includes(tool.tool_id)}
              disabled={bound}
              onChange={(event) =>
                setSelectedTools((current) =>
                  event.target.checked
                    ? [...current, tool.tool_id]
                    : current.filter((id) => id !== tool.tool_id)
                )
              }
              className="block"
            >
              {tool.name}
            </Checkbox>
          ))}
          <div className="mt-2 flex gap-2">
            <Button
              size="small"
              type="primary"
              disabled={
                bound ||
                skipped ||
                selectedTools.length === 0 ||
                lifecycle.pending
              }
              onClick={bind}
            >
              {bound ? "Tools bound" : "Bind selected tools"}
            </Button>
            <Button
              size="small"
              disabled={bound || skipped || lifecycle.pending}
              onClick={skip}
            >
              {skipped ? "Binding skipped" : "Skip tool binding"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};
