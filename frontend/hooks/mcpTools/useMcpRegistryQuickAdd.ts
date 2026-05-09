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
import { checkContainerPortAvailable } from "./useContainerPortAvailability";
import { McpSource, McpTransportType } from "@/const/mcpTools";
import { refreshToolListWithToast } from "./useRefreshToolListWithToast";
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
import type {
  McpContainerConfigPayload,
  RegistryMcpCard,
  RegistryQuickAddOption,
} from "@/types/mcpTools";
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

  const selectedOption = useMemo(
    () => options.find((option) => option.key === selectedKey) || null,
    [options, selectedKey]
  );

  const open = useCallback(
    (service: RegistryMcpCard) => {
      const nextOptions = resolveQuickAddOptions(service);
      if (nextOptions.length === 0) {
        message.info(t("mcpTools.registry.quickAddUnsupported"));
        return;
      }
      setCandidate(service);
      setOptions(nextOptions);
      const firstKey = nextOptions[0].key;
      setSelectedKey(firstKey);
      setValues(buildInitialQuickAddValues(nextOptions[0]));
      setContainerPort(undefined);
    },
    [message, t]
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
    const tags: string[] = [];

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
        t("mcpTools.registry.quickAddPicker.variableRequiredMissing", {
          key: missingField.key,
        })
      );
      return;
    }

    setSubmitting(true);
    try {
      if (selectedOption.transportType === McpTransportType.CONTAINER) {
        const available = await checkContainerPortAvailable(containerPort);
        if (!available) {
          message.error(
            t("mcpTools.addModal.portOccupied", { port: containerPort })
          );
          return;
        }

        const runtimeCommand = inferContainerRuntimeCommand(
          selectedOption.packageRegistryType
        );
        if (!runtimeCommand) {
          message.error(t("mcpTools.registry.quickAddUnsupported"));
          return;
        }
        const runtimeArgs = resolveRuntimeArgs(selectedOption, values);
        const envValues = collectPackageEnvValues(selectedOption, values);
        const serverKey = normalizeServerKey(candidate.server?.name);

        const mcpConfig: McpContainerConfigPayload = {
          mcpServers: {
            [serverKey]: {
              command: runtimeCommand,
              args: runtimeArgs,
              env: envValues,
            },
          },
        };

        await addContainerMcpToolService({
          name: candidate.server?.name,
          description: candidate.server?.description,
          tags,
          source: McpSource.REGISTRY,
          port: containerPort as number,
          mcp_config: mcpConfig,
        });
      } else {
        const finalUrl = resolveHttpServerUrl(selectedOption, values);
        if (!finalUrl || hasUnresolvedUrlTemplate(finalUrl)) {
          message.warning(
            t("mcpTools.registry.quickAddPicker.variableRequiredMissing", {
              key: "url",
            })
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
          name: candidate.server?.name,
          description: candidate.server?.description || "",
          source: McpSource.REGISTRY,
          server_url: finalUrl,
          tags,
          authorization_token: authorization,
          version: candidate.server?.version,
          registry_json: candidate.server as unknown as Record<string, unknown>,
        });
      }

      message.success(t("mcpTools.add.success"));
      queryClient.invalidateQueries({
        queryKey: MCP_TOOLS_QUERY_KEYS.services,
      });
      await refreshToolListWithToast({
        message,
        t,
        toastKey: "mcp-tools-refresh-tools-add-registry",
      });
      onSuccess();
      close();
    } catch (error) {
      log.error("[useMcpRegistryQuickAdd] Failed to add from registry", {
        error,
      });
      message.error(t("mcpTools.add.failed"));
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
    t,
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
