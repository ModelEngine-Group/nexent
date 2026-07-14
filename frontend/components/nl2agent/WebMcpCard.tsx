"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Checkbox,
  Input,
  InputNumber,
  Select,
  message,
} from "antd";
import { Download } from "lucide-react";
import {
  bindNl2AgentMcpTools,
  getNl2AgentSessionState,
  installNl2AgentMcp,
  skipNl2AgentMcpTools,
} from "@/services/nl2agentService";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";

export interface WebMcpCardItem {
  recommendation_id?: string;
  name: string;
  description?: string;
  source?: string;
  url?: string;
  transport?: string;
  score?: number;
  reason?: string;
  install_options?: Array<{
    option_id: string;
    type: string;
    transport?: string;
    server_url_template?: string;
    requires_configuration?: boolean;
    label?: string;
    description?: string;
    status?: "ready" | "configuration_required" | "unsupported";
    supported?: boolean;
    unsupported_reason?: string;
    fields?: Array<{
      key: string;
      name: string;
      label?: string;
      description?: string;
      type?: "text" | "number" | "url" | "json";
      required?: boolean;
      secret?: boolean;
      default?: string | null;
      placeholder?: string;
      choices?: string[];
      category?: string;
    }>;
  }>;
  prefill?: Record<string, string>;
}

export interface WebMcpCardProps {
  /** The draft agent_id (used for the install callback context, though MCP
   * install is handled by opening the existing AddMcpServiceModal). */
  agentId: number;
  item: WebMcpCardItem;
  /** Optional callback to open the existing AddMcpServiceModal prefilled. */
  onInstall?: (item: WebMcpCardItem) => void;
}

const initialFieldValues = (
  option: NonNullable<WebMcpCardItem["install_options"]>[number] | undefined,
  prefill: Record<string, string> | undefined
) =>
  (option?.fields ?? []).reduce<Record<string, string>>((values, field) => {
    if (!field.secret && field.default != null)
      values[field.key] = String(field.default);
    if (!field.secret && prefill?.[field.key] != null)
      values[field.key] = String(prefill[field.key]);
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
export const WebMcpCard: React.FC<WebMcpCardProps> = ({ agentId, item }) => {
  const workflow = useNl2AgentWorkflow();
  const { t } = useTranslation("common");
  const options = item.install_options ?? [];
  const [optionId, setOptionId] = React.useState(
    options[0]?.option_id ?? "remote"
  );
  const [fieldValues, setFieldValues] = React.useState<Record<string, string>>(
    () => initialFieldValues(options[0], item.prefill)
  );
  const [installing, setInstalling] = React.useState(false);
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
    let active = true;
    void getNl2AgentSessionState(agentId)
      .then((state) => {
        if (!active) return;
        const workflow =
          state.resource_review.mcp_workflows?.[item.recommendation_id!];
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
          const tools = workflow.discovered_tools ?? [];
          setInstalled({ mcp_id: workflow.mcp_id, tools });
          setSelectedTools(
            workflow.status === "tools_bound"
              ? (workflow.bound_tool_ids ?? [])
              : tools.map((tool) => tool.tool_id)
          );
          setBound(workflow.status === "tools_bound");
          setSkipped(workflow.status === "binding_skipped");
        }
      })
      .catch(() => {
        // Installation remains available; the API will still validate authoritative state.
      });
    return () => {
      active = false;
    };
  }, [agentId, item.recommendation_id]);

  const chooseOption = (nextOptionId: string) => {
    setOptionId(nextOptionId);
    const nextOption = options.find(
      (option) => option.option_id === nextOptionId
    );
    setFieldValues(initialFieldValues(nextOption, item.prefill));
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
    workflow.beginAction();
    setInstalling(true);
    setInstallError(undefined);
    try {
      const result = await installNl2AgentMcp(agentId, {
        recommendation_id: item.recommendation_id,
        option_id: optionId,
        config_values: {
          fields: fieldValues,
        },
      });
      setInstalled(result);
      setSelectedTools(
        result.tools.map((tool: { tool_id: number }) => tool.tool_id)
      );
      message.success("MCP installed and connected.");
      workflow.notifyStateChanged();
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : "MCP installation failed.";
      setInstallError(errorMessage);
      message.error(errorMessage);
    } finally {
      setInstalling(false);
      workflow.endAction();
    }
  };

  const bind = async () => {
    if (!installed) return;
    workflow.beginAction();
    try {
      await bindNl2AgentMcpTools(agentId, installed.mcp_id, selectedTools);
      setBound(true);
      setInstallError(undefined);
      message.success("Selected MCP tools are bound to the draft.");
      workflow.notifyStateChanged();
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : "MCP tool binding failed.";
      setInstallError(errorMessage);
      message.error(errorMessage);
    } finally {
      workflow.endAction();
    }
  };

  const skip = async () => {
    if (!installed) return;
    workflow.beginAction();
    try {
      await skipNl2AgentMcpTools(agentId, installed.mcp_id);
      setSkipped(true);
      setInstallError(undefined);
      message.success("MCP tool binding skipped.");
      workflow.notifyStateChanged();
    } catch (error) {
      const errorMessage =
        error instanceof Error
          ? error.message
          : "Unable to skip MCP tool binding.";
      setInstallError(errorMessage);
      message.error(errorMessage);
    } finally {
      workflow.endAction();
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
          {item.url && (
            <div className="text-[11px] text-gray-400 mt-1 truncate">
              {item.url}
            </div>
          )}
        </div>
        {!installed && (
          <Button
            size="small"
            icon={<Download className="h-3.5 w-3.5" />}
            loading={installing}
            disabled={!canInstall || workflow.busy}
            onClick={install}
          >
            {t("nl2agent.webMcp.install", "Install")}
          </Button>
        )}
      </div>
      {!installed && (
        <div className="mt-3 space-y-2 border-t border-sky-100 pt-2">
          {options.length > 1 && (
            <Select
              className="w-full"
              value={optionId}
              onChange={chooseOption}
              options={options.map((option) => ({
                value: option.option_id,
                label:
                  option.label || `${option.type} ${option.transport ?? ""}`,
                disabled: option.supported === false,
              }))}
            />
          )}
          {selectedOption?.supported === false ? (
            <Alert
              type="warning"
              showIcon
              message={
                selectedOption.unsupported_reason || "Unsupported option"
              }
            />
          ) : null}
          {selectedOption?.description ? (
            <div className="text-xs text-gray-500">
              {selectedOption.description}
            </div>
          ) : null}
          {fields.map((field) => {
            const label = `${field.label || field.name}${field.required ? " *" : ""}`;
            const update = (value: string) =>
              setFieldValues((current) => ({ ...current, [field.key]: value }));
            return (
              <div key={field.key}>
                <div className="mb-1 text-xs font-medium text-gray-600">
                  {label}
                </div>
                {field.description ? (
                  <div className="mb-1 text-[11px] text-gray-400">
                    {field.description}
                  </div>
                ) : null}
                {field.secret ? (
                  <Input.Password
                    placeholder={field.placeholder || label}
                    value={fieldValues[field.key] ?? ""}
                    onChange={(event) => update(event.target.value)}
                  />
                ) : field.choices?.length ? (
                  <Select
                    className="w-full"
                    value={fieldValues[field.key]}
                    onChange={update}
                    options={field.choices.map((choice) => ({
                      value: choice,
                      label: choice,
                    }))}
                  />
                ) : field.type === "json" ? (
                  <Input.TextArea
                    rows={4}
                    placeholder={field.placeholder || label}
                    value={fieldValues[field.key] ?? ""}
                    onChange={(event) => update(event.target.value)}
                  />
                ) : field.type === "number" ? (
                  <InputNumber
                    className="w-full"
                    placeholder={field.placeholder || label}
                    value={
                      fieldValues[field.key]
                        ? Number(fieldValues[field.key])
                        : null
                    }
                    onChange={(value) =>
                      update(value == null ? "" : String(value))
                    }
                  />
                ) : (
                  <Input
                    type={field.type === "url" ? "url" : "text"}
                    placeholder={field.placeholder || label}
                    value={fieldValues[field.key] ?? ""}
                    onChange={(event) => update(event.target.value)}
                  />
                )}
              </div>
            );
          })}
          {installError ? (
            <Alert
              type="error"
              showIcon
              message="Installation failed"
              description={installError}
            />
          ) : null}
        </div>
      )}
      {installed && (
        <div className="mt-3 border-t border-sky-100 pt-2">
          {installError ? (
            <Alert
              type="error"
              showIcon
              message="MCP action failed"
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
                bound || skipped || selectedTools.length === 0 || workflow.busy
              }
              onClick={bind}
            >
              {bound ? "Tools bound" : "Bind selected tools"}
            </Button>
            <Button
              size="small"
              disabled={bound || skipped || workflow.busy}
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
