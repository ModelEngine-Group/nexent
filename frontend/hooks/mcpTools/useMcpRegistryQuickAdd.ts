"use client";

import { useCallback, useMemo, useState } from "react";
import { App } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import log from "@/lib/logger";
import {
  addContainerMcpToolService,
  addMcpToolService,
} from "@/services/mcpToolsService";
import { updateToolList } from "@/services/mcpService";
import { ensureContainerPortAvailableOnce } from "./useContainerPortAvailability";
import { MCP_TAB } from "@/const/mcpTools";
import {
  buildInitialQuickAddValues,
  collectPackageEnvValues,
  findMissingRequiredField,
  hasUnresolvedUrlTemplate,
  inferContainerRuntimeCommand,
  normalizeServerKey,
  resolveAuthorizationFromHeaders,
  resolveHttpServerUrl,
  resolveQuickAddOptions,
  resolveRuntimeArgs,
} from "@/lib/mcpTools";
import type { RegistryMcpCard, RegistryQuickAddOption } from "@/types/mcpTools";
import { McpTransportType } from "@/types/mcpTools";
import { MCP_TOOLS_QUERY_KEYS } from "@/const/mcpTools";

interface UseMcpRegistryQuickAddParams {
  onSuccess: () => void;
}

/**
 * Picker + submission flow launched from the registry list. The component
 * owning this hook just renders a modal and wires in the returned values.
 */
export function useMcpRegistryQuickAdd({
  onSuccess,
}: UseMcpRegistryQuickAddParams) {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();

  const [candidate, setCandidate] = useState<RegistryMcpCard | null>(null);
  const [options, setOptions] = useState<RegistryQuickAddOption[]>([]);
  const [selectedKey, setSelectedKey] = useState<string>("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [containerPort, setContainerPort] = useState<number | undefined>(
    undefined
  );
  const [submitting, setSubmitting] = useState(false);

  const translate = useCallback(
    (key: string, params?: Record<string, unknown>) => String(t(key, params)),
    [t]
  );

  const selectedOption = useMemo(
    () => options.find((option) => option.key === selectedKey) || null,
    [options, selectedKey]
  );

  const open = useCallback(
    (service: RegistryMcpCard) => {
      const nextOptions = resolveQuickAddOptions(service);
      if (nextOptions.length === 0) {
        message.info(translate("mcpTools.registry.quickAddUnsupported"));
        return;
      }
      setCandidate(service);
      setOptions(nextOptions);
      const firstKey = nextOptions[0].key;
      setSelectedKey(firstKey);
      setValues(buildInitialQuickAddValues(nextOptions[0]));
      setContainerPort(undefined);
    },
    [message, translate]
  );

  const close = useCallback(() => {
    setCandidate(null);
    setOptions([]);
    setSelectedKey("");
    setValues({});
    setContainerPort(undefined);
  }, []);

  const chooseOption = useCallback(
    (key: string) => {
      setSelectedKey(key);
      const next = options.find((option) => option.key === key) || null;
      setValues(buildInitialQuickAddValues(next));
    },
    [options]
  );

  const setValue = useCallback((formKey: string, value: string) => {
    setValues((prev) => ({ ...prev, [formKey]: value }));
  }, []);

  const confirm = useCallback(async () => {
    if (!candidate || !selectedOption) return;
    const tags = ["quick-add"];

    const allFields = [
      ...(selectedOption.remoteVariables || []),
      ...(selectedOption.remoteHeaders || []),
      ...(selectedOption.packageEnvironmentVariables || []),
      ...(selectedOption.packageTransportHeaders || []),
      ...(selectedOption.packageTransportVariables || []),
    ];
    const missingField = findMissingRequiredField(allFields, values);
    if (missingField) {
      message.warning(
        translate("mcpTools.registry.quickAddPicker.variableRequiredMissing", {
          key: missingField.key,
        })
      );
      return;
    }

    setSubmitting(true);
    try {
      if (selectedOption.transportType === "container") {
        const ok = await ensureContainerPortAvailableOnce({
          containerPort,
          message,
          translate,
        });
        if (!ok) return;

        const runtimeCommand = inferContainerRuntimeCommand(
          selectedOption.packageRegistryType
        );
        if (!runtimeCommand) {
          message.error(translate("mcpTools.registry.quickAddUnsupported"));
          return;
        }
        const runtimeArgs = resolveRuntimeArgs(selectedOption, values);
        const envValues = collectPackageEnvValues(selectedOption, values);
        const serverKey = normalizeServerKey(
          candidate.server?.name ||
            selectedOption.packageIdentifier ||
            "market-mcp"
        );

        const mcpConfig = {
          mcpServers: {
            [serverKey]: {
              command: runtimeCommand,
              args: runtimeArgs,
              env: envValues,
              port: containerPort as number,
            },
          },
        };

        await addContainerMcpToolService({
          name:
            candidate.server?.name ||
            selectedOption.packageIdentifier ||
            "market-mcp",
          description: candidate.server?.description || "",
          tags,
          source: "market",
          port: containerPort as number,
          mcp_config: mcpConfig,
        });
      } else {
        const finalUrl = resolveHttpServerUrl(selectedOption, values);
        if (!finalUrl || hasUnresolvedUrlTemplate(finalUrl)) {
          message.warning(
            translate(
              "mcpTools.registry.quickAddPicker.variableRequiredMissing",
              { key: "url" }
            )
          );
          return;
        }
        const authorization = resolveAuthorizationFromHeaders(
          [
            ...(selectedOption.remoteHeaders || []),
            ...(selectedOption.packageTransportHeaders || []),
          ],
          values
        );

        await addMcpToolService({
          name: candidate.server?.name || "market-mcp",
          description: candidate.server?.description || "",
          source: MCP_TAB.MCP_REGISTRY,
          transport_type: selectedOption.transportType as McpTransportType,
          server_url: finalUrl,
          tags,
          authorization_token: authorization,
          version: candidate.server?.version,
          registry_json: candidate.server as unknown as Record<string, unknown>,
        });
      }

      message.success(translate("mcpTools.add.success"));
      queryClient.invalidateQueries({
        queryKey: MCP_TOOLS_QUERY_KEYS.services,
      });
      queryClient.invalidateQueries({
        queryKey: MCP_TOOLS_QUERY_KEYS.tagStats,
      });
      try {
        await updateToolList();
      } catch (error) {
        log.error("[useMcpRegistryQuickAdd] Failed to refresh tool list", {
          error,
        });
      }
      onSuccess();
      close();
    } catch (error) {
      log.error("[useMcpRegistryQuickAdd] Failed to add from registry", {
        error,
      });
      message.error(translate("mcpTools.add.failed"));
    } finally {
      setSubmitting(false);
    }
  }, [
    candidate,
    close,
    containerPort,
    message,
    onSuccess,
    queryClient,
    selectedOption,
    translate,
    values,
  ]);

  return {
    visible: Boolean(candidate),
    candidate,
    options,
    selectedOption,
    selectedKey,
    values,
    containerPort,
    setContainerPort,
    open,
    close,
    chooseOption,
    setValue,
    confirm,
    submitting,
  };
}
