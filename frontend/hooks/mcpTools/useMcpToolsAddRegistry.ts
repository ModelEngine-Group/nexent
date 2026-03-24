import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { MessageInstance } from "antd/es/message/interface";
import log from "@/lib/logger";
import { MCP_TRANSPORT_TYPE, MCP_TAB } from "@/const/mcpTools";
import {
  addContainerMcpToolService,
  addMcpToolService,
  fetchRegistryMcpCards,
  type RegistryMcpCard,
} from "@/services/mcpToolsService";
import {
  type RegistryQuickAddOption,
  type McpTab,
} from "@/types/mcpTools";

type UseMcpToolsAddRegistryParams = {
  open: boolean;
  addModalTab: McpTab;
  t: (key: string) => string;
  message: MessageInstance;
  onServiceAdded: () => Promise<unknown>;
  onClose: () => void;
};

const resolveQuickAddTarget = (type?: string | null, url?: string | null): { transportType: "http" | "sse"; serverUrl: string } | null => {
  const serverUrl = (url || "").trim();
  if (!serverUrl) return null;

  const normalizedType = (type || "").trim().toLowerCase();
  if (normalizedType.includes("sse")) {
    return { transportType: "sse", serverUrl };
  }
  if (normalizedType.includes("http")) {
    return { transportType: "http", serverUrl };
  }
  if (/^https?:\/\//i.test(serverUrl)) {
    return { transportType: "http", serverUrl };
  }

  return null;
};

const normalizeServerKey = (raw: string): string => {
  const normalized = raw.trim().toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "");
  return normalized || "market-mcp";
};

const inferStdioCommand = (registryType?: string): string | null => {
  const normalized = (registryType || "").trim().toLowerCase();
  if (normalized === "npm") return "npx";
  if (normalized === "pypi") return "uvx";
  return null;
};

const inferStdioArgs = (registryType?: string, identifier?: string): string[] => {
  const packageId = (identifier || "").trim();
  const normalized = (registryType || "").trim().toLowerCase();
  if (!packageId) return [];
  if (normalized === "npm") return ["-y", packageId];
  return [packageId];
};

const pickQuickAddPort = (): number => {
  const seed = Date.now() % 1000;
  return 5500 + seed;
};

const extractPackageEnvTemplate = (service: RegistryMcpCard, pkgIdentifier?: string): Record<string, string> => {
  if (!pkgIdentifier) return {};
  const rawPackages = (service.serverJson as { packages?: unknown[] } | undefined)?.packages;
  if (!Array.isArray(rawPackages)) return {};

  const targetPackage = rawPackages.find((entry) => {
    if (!entry || typeof entry !== "object") return false;
    const identifier = String((entry as { identifier?: unknown }).identifier || "").trim();
    return identifier === pkgIdentifier;
  }) as { environmentVariables?: Array<{ name?: string; default?: string }> } | undefined;

  const environmentVariables = targetPackage?.environmentVariables;
  if (!Array.isArray(environmentVariables)) return {};

  return environmentVariables.reduce<Record<string, string>>((acc, item) => {
    const envName = String(item?.name || "").trim();
    if (!envName) return acc;
    acc[envName] = String(item?.default || "");
    return acc;
  }, {});
};

const resolveQuickAddOptions = (service: RegistryMcpCard): RegistryQuickAddOption[] => {
  const options: RegistryQuickAddOption[] = [];

  (service.remotes || []).forEach((remote, index) => {
    const remoteTarget = resolveQuickAddTarget(remote.type, remote.url);
    if (!remoteTarget) return;

    options.push({
      key: `remote-${index}`,
      sourceType: "remote",
      sourceLabel: `${remote.type || "remote"} - ${remote.url}`,
      transportType: remoteTarget.transportType,
      serverUrl: remoteTarget.serverUrl,
    });
  });

  (service.packages || []).forEach((pkg, index) => {
    const packageId = pkg.identifier || "package";
    const transportType = pkg.transport?.type || "remote";
    const transportUrl = pkg.transport?.url || "";

    const packageTarget = resolveQuickAddTarget(pkg.transport?.type, pkg.transport?.url);
    if (packageTarget) {
      options.push({
        key: `package-${index}`,
        sourceType: "package",
        sourceLabel: `${packageId} - ${transportType} - ${transportUrl}`,
        transportType: packageTarget.transportType,
        serverUrl: packageTarget.serverUrl,
      });
      return;
    }

    if ((pkg.transport?.type || "").trim().toLowerCase() === "stdio") {
      options.push({
        key: `package-${index}`,
        sourceType: "package",
        sourceLabel: `${packageId} - stdio`,
        transportType: "stdio",
        packageIdentifier: pkg.identifier,
        packageRegistryType: pkg.registryType,
        packageEnvTemplate: extractPackageEnvTemplate(service, pkg.identifier),
      });
    }
  });

  return options;
};

export function useMcpToolsAddRegistry({
  open,
  addModalTab,
  t,
  message,
  onServiceAdded,
  onClose,
}: UseMcpToolsAddRegistryParams) {
  const [registrySearchValue, setRegistrySearchValue] = useState("");
  const [selectedRegistryService, setSelectedRegistryService] = useState<RegistryMcpCard | null>(null);
  const [registryCurrentCursor, setRegistryCurrentCursor] = useState<string | null>(null);
  const [registryCursorHistory, setRegistryCursorHistory] = useState<string[]>([]);
  const [registryPage, setRegistryPage] = useState(1);
  const [registryVersion, setRegistryVersion] = useState("latest");
  const [registryUpdatedSince, setRegistryUpdatedSince] = useState("");
  const [registryIncludeDeleted, setRegistryIncludeDeleted] = useState(false);
  const [quickAddPickerVisible, setQuickAddPickerVisible] = useState(false);
  const [quickAddCandidateService, setQuickAddCandidateService] = useState<RegistryMcpCard | null>(null);
  const [quickAddOptions, setQuickAddOptions] = useState<RegistryQuickAddOption[]>([]);
  const [selectedQuickAddOptionKey, setSelectedQuickAddOptionKey] = useState("");
  const [addingService, setAddingService] = useState(false);

  const addMutation = useMutation({ mutationFn: addMcpToolService });

  const reset = useCallback(() => {
    setRegistrySearchValue("");
    setRegistryCurrentCursor(null);
    setRegistryCursorHistory([]);
    setRegistryPage(1);
    setRegistryVersion("latest");
    setRegistryUpdatedSince("");
    setRegistryIncludeDeleted(false);
    setSelectedRegistryService(null);
    setQuickAddPickerVisible(false);
    setQuickAddCandidateService(null);
    setQuickAddOptions([]);
    setSelectedQuickAddOptionKey("");
    setAddingService(false);
  }, []);

  const loadRegistryFirstPage = useCallback(() => {
    setRegistryCurrentCursor(null);
    setRegistryCursorHistory([]);
    setRegistryPage(1);
  }, []);

  useEffect(() => {
    if (!(open && addModalTab === MCP_TAB.MCP_REGISTRY)) return;
    const timer = window.setTimeout(() => {
      loadRegistryFirstPage();
    }, 350);
    return () => window.clearTimeout(timer);
  }, [
    open,
    addModalTab,
    registrySearchValue,
    registryVersion,
    registryUpdatedSince,
    registryIncludeDeleted,
    loadRegistryFirstPage,
  ]);

  const registryQuery = useQuery<{ items: RegistryMcpCard[]; nextCursor: string | null }>({
    queryKey: [
      "mcp-tools",
      "market",
      registrySearchValue,
      registryCurrentCursor,
      registryVersion,
      registryUpdatedSince,
      registryIncludeDeleted,
    ],
    enabled: open && addModalTab === MCP_TAB.MCP_REGISTRY,
    retry: false,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    queryFn: async () => {
      const result = await fetchRegistryMcpCards({
        search: registrySearchValue,
        cursor: registryCurrentCursor,
        version: registryVersion,
        updatedSince: registryUpdatedSince,
        includeDeleted: registryIncludeDeleted,
      });
      return result.data;
    },
  });

  const registryServices = registryQuery.data?.items ?? [];
  const registryNextCursor = registryQuery.data?.nextCursor ?? null;

  useEffect(() => {
    if (!(registryQuery.error instanceof Error)) return;
    log.error("[useMcpToolsAddRegistry] Failed to load registry MCP cards", {
      error: registryQuery.error,
      search: registrySearchValue,
      cursor: registryCurrentCursor,
      version: registryVersion,
      updatedSince: registryUpdatedSince,
      includeDeleted: registryIncludeDeleted,
    });
    message.error(t("mcpTools.registry.loadFailed"));
  }, [
    registryQuery.error,
    registrySearchValue,
    registryCurrentCursor,
    registryVersion,
    registryUpdatedSince,
    registryIncludeDeleted,
    message,
  ]);

  const handleRegistryNextPage = useCallback(() => {
    if (!registryNextCursor || registryQuery.isFetching) return;
    const currentCursorSnapshot = registryCurrentCursor;
    setRegistryCursorHistory((prev) => [...prev, currentCursorSnapshot ?? ""]);
    setRegistryCurrentCursor(registryNextCursor);
    setRegistryPage((prev) => prev + 1);
  }, [registryCurrentCursor, registryNextCursor, registryQuery.isFetching]);

  const handleRegistryPrevPage = useCallback(() => {
    if (registryCursorHistory.length === 0 || registryQuery.isFetching) return;
    const previousCursor = registryCursorHistory[registryCursorHistory.length - 1] || null;
    setRegistryCursorHistory((prev) => prev.slice(0, -1));
    setRegistryCurrentCursor(previousCursor);
    setRegistryPage((prev) => Math.max(1, prev - 1));
  }, [registryCursorHistory, registryQuery.isFetching]);

  const handleCloseQuickAddPicker = useCallback(() => {
    setQuickAddPickerVisible(false);
    setQuickAddCandidateService(null);
    setQuickAddOptions([]);
    setSelectedQuickAddOptionKey("");
  }, []);

  const handleQuickAddFromRegistry = useCallback((service: RegistryMcpCard) => {
    const quickAddOptionsForService = resolveQuickAddOptions(service);
    if (quickAddOptionsForService.length === 0) {
      log.warn("[useMcpToolsAddRegistry] Quick add is unsupported for selected registry service", {
        serviceName: service.name,
        remotes: service.remotes,
        packages: service.packages,
      });
      message.warning(t("mcpTools.registry.quickAddUnsupported"));
      return;
    }

    setQuickAddCandidateService(service);
    setQuickAddOptions(quickAddOptionsForService);
    setSelectedQuickAddOptionKey(quickAddOptionsForService[0]?.key || "");
    setQuickAddPickerVisible(true);
  }, [message, t]);

  const handleConfirmQuickAddOption = useCallback(async () => {
    const service = quickAddCandidateService;
    if (!service) return;

    const selectedOption = quickAddOptions.find((option) => option.key === selectedQuickAddOptionKey);
    if (!selectedOption) {
      message.warning(t("mcpTools.registry.quickAddUnsupported"));
      return;
    }

    setAddingService(true);
    try {
      if (selectedOption.transportType === "stdio") {
        const packageIdentifier = (selectedOption.packageIdentifier || "").trim();
        const command = inferStdioCommand(selectedOption.packageRegistryType);
        if (!packageIdentifier || !command) {
          message.warning(t("mcpTools.registry.quickAddUnsupported"));
          return;
        }

        const serverKey = normalizeServerKey(packageIdentifier);
        const containerPort = pickQuickAddPort();
        await addContainerMcpToolService({
          name: quickAddCandidateService.name,
          description: quickAddCandidateService.description,
          tags: [],
          port: containerPort,
          mcp_config: {
            mcpServers: {
              [serverKey]: {
                command,
                args: inferStdioArgs(selectedOption.packageRegistryType, packageIdentifier),
                env: selectedOption.packageEnvTemplate || {},
              },
            },
          },
        });
      } else {
        await addMutation.mutateAsync({
          name: quickAddCandidateService.name,
          description: quickAddCandidateService.description,
          source: MCP_TAB.MCP_REGISTRY,
          transport_type: selectedOption.transportType === "sse" ? MCP_TRANSPORT_TYPE.SSE : MCP_TRANSPORT_TYPE.HTTP,
          server_url: selectedOption.serverUrl || "",
          tags: [],
          version: quickAddCandidateService.version || undefined,
          registry_json: quickAddCandidateService.serverJson || undefined,
        });
      }

      await onServiceAdded();
      message.success(t("mcpTools.registry.quickAddSuccess"));
      handleCloseQuickAddPicker();
      onClose();
    } catch (error) {
      log.error("[useMcpToolsAddRegistry] Failed to quick add registry service", {
        error,
        serviceName: quickAddCandidateService.name,
        remotes: quickAddCandidateService.remotes,
        packages: quickAddCandidateService.packages,
        quickAddOption: selectedOption,
      });
      message.error(t("mcpTools.add.failed"));
    } finally {
      setAddingService(false);
    }
  }, [
    addMutation,
    handleCloseQuickAddPicker,
    message,
    onClose,
    onServiceAdded,
    quickAddCandidateService,
    quickAddOptions,
    selectedQuickAddOptionKey,
    t,
  ]);

  return {
    registrySearchValue,
    selectedRegistryService,
    filteredRegistryServices: registryServices,
    registryLoading: registryQuery.isFetching,
    registryPage,
    hasPrevRegistryPage: registryCursorHistory.length > 0,
    hasNextRegistryPage: Boolean(registryNextCursor),
    registryVersion,
    registryUpdatedSince,
    registryIncludeDeleted,
    quickAddPickerVisible,
    quickAddCandidateService,
    quickAddOptions,
    selectedQuickAddOptionKey,
    quickAddSubmitting: addingService,
    setRegistrySearchValue,
    setSelectedRegistryService,
    setRegistryVersion,
    setRegistryUpdatedSince,
    setRegistryIncludeDeleted,
    setSelectedQuickAddOptionKey,
    handleRegistryPrevPage,
    handleRegistryNextPage,
    handleQuickAddFromRegistry,
    handleCloseQuickAddPicker,
    handleConfirmQuickAddOption,
    addingService,
    reset,
  };
}
