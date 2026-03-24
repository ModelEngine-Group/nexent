import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { MessageInstance } from "antd/es/message/interface";
import log from "@/lib/logger";
import { MCP_TRANSPORT_TYPE, MCP_TAB } from "@/const/mcpTools";
import {
  addContainerMcpToolService,
  addMcpToolService,
  fetchMarketMcpCards,
  type MarketMcpCard,
} from "@/services/mcpToolsService";
import {
  type MarketQuickAddOption,
  type McpTab,
} from "@/types/mcpTools";

type UseMcpToolsAddMarketParams = {
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

const extractPackageEnvTemplate = (service: MarketMcpCard, pkgIdentifier?: string): Record<string, string> => {
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

const resolveQuickAddOptions = (service: MarketMcpCard): MarketQuickAddOption[] => {
  const options: MarketQuickAddOption[] = [];

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

export function useMcpToolsAddMarket({
  open,
  addModalTab,
  t,
  message,
  onServiceAdded,
  onClose,
}: UseMcpToolsAddMarketParams) {
  const [marketSearchValue, setMarketSearchValue] = useState("");
  const [selectedMarketService, setSelectedMarketService] = useState<MarketMcpCard | null>(null);
  const [marketCurrentCursor, setMarketCurrentCursor] = useState<string | null>(null);
  const [marketCursorHistory, setMarketCursorHistory] = useState<string[]>([]);
  const [marketPage, setMarketPage] = useState(1);
  const [marketVersion, setMarketVersion] = useState("latest");
  const [marketUpdatedSince, setMarketUpdatedSince] = useState("");
  const [marketIncludeDeleted, setMarketIncludeDeleted] = useState(false);
  const [quickAddPickerVisible, setQuickAddPickerVisible] = useState(false);
  const [quickAddCandidateService, setQuickAddCandidateService] = useState<MarketMcpCard | null>(null);
  const [quickAddOptions, setQuickAddOptions] = useState<MarketQuickAddOption[]>([]);
  const [selectedQuickAddOptionKey, setSelectedQuickAddOptionKey] = useState("");
  const [addingService, setAddingService] = useState(false);

  const addMutation = useMutation({ mutationFn: addMcpToolService });

  const reset = useCallback(() => {
    setMarketSearchValue("");
    setMarketCurrentCursor(null);
    setMarketCursorHistory([]);
    setMarketPage(1);
    setMarketVersion("latest");
    setMarketUpdatedSince("");
    setMarketIncludeDeleted(false);
    setSelectedMarketService(null);
    setQuickAddPickerVisible(false);
    setQuickAddCandidateService(null);
    setQuickAddOptions([]);
    setSelectedQuickAddOptionKey("");
    setAddingService(false);
  }, []);

  const loadMarketFirstPage = useCallback(() => {
    setMarketCurrentCursor(null);
    setMarketCursorHistory([]);
    setMarketPage(1);
  }, []);

  useEffect(() => {
    if (!(open && addModalTab === MCP_TAB.MCP_REGISTRY)) return;
    const timer = window.setTimeout(() => {
      loadMarketFirstPage();
    }, 350);
    return () => window.clearTimeout(timer);
  }, [
    open,
    addModalTab,
    marketSearchValue,
    marketVersion,
    marketUpdatedSince,
    marketIncludeDeleted,
    loadMarketFirstPage,
  ]);

  const marketQuery = useQuery<{ items: MarketMcpCard[]; nextCursor: string | null }>({
    queryKey: [
      "mcp-tools",
      "market",
      marketSearchValue,
      marketCurrentCursor,
      marketVersion,
      marketUpdatedSince,
      marketIncludeDeleted,
    ],
    enabled: open && addModalTab === MCP_TAB.MCP_REGISTRY,
    retry: false,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    queryFn: async () => {
      const result = await fetchMarketMcpCards({
        search: marketSearchValue,
        cursor: marketCurrentCursor,
        version: marketVersion,
        updatedSince: marketUpdatedSince,
        includeDeleted: marketIncludeDeleted,
      });
      return result.data;
    },
  });

  const marketServices = marketQuery.data?.items ?? [];
  const marketNextCursor = marketQuery.data?.nextCursor ?? null;

  useEffect(() => {
    if (!(marketQuery.error instanceof Error)) return;
    log.error("[useMcpToolsAddMarket] Failed to load market MCP cards", {
      error: marketQuery.error,
      search: marketSearchValue,
      cursor: marketCurrentCursor,
      version: marketVersion,
      updatedSince: marketUpdatedSince,
      includeDeleted: marketIncludeDeleted,
    });
    message.error(t("mcpTools.market.loadFailed"));
  }, [
    marketQuery.error,
    marketSearchValue,
    marketCurrentCursor,
    marketVersion,
    marketUpdatedSince,
    marketIncludeDeleted,
    message,
  ]);

  const handleMarketNextPage = useCallback(() => {
    if (!marketNextCursor || marketQuery.isFetching) return;
    const currentCursorSnapshot = marketCurrentCursor;
    setMarketCursorHistory((prev) => [...prev, currentCursorSnapshot ?? ""]);
    setMarketCurrentCursor(marketNextCursor);
    setMarketPage((prev) => prev + 1);
  }, [marketCurrentCursor, marketNextCursor, marketQuery.isFetching]);

  const handleMarketPrevPage = useCallback(() => {
    if (marketCursorHistory.length === 0 || marketQuery.isFetching) return;
    const previousCursor = marketCursorHistory[marketCursorHistory.length - 1] || null;
    setMarketCursorHistory((prev) => prev.slice(0, -1));
    setMarketCurrentCursor(previousCursor);
    setMarketPage((prev) => Math.max(1, prev - 1));
  }, [marketCursorHistory, marketQuery.isFetching]);

  const handleCloseQuickAddPicker = useCallback(() => {
    setQuickAddPickerVisible(false);
    setQuickAddCandidateService(null);
    setQuickAddOptions([]);
    setSelectedQuickAddOptionKey("");
  }, []);

  const handleQuickAddFromMarket = useCallback((service: MarketMcpCard) => {
    const quickAddOptionsForService = resolveQuickAddOptions(service);
    if (quickAddOptionsForService.length === 0) {
      log.warn("[useMcpToolsAddMarket] Quick add is unsupported for selected market service", {
        serviceName: service.name,
        remotes: service.remotes,
        packages: service.packages,
      });
      message.warning(t("mcpTools.market.quickAddUnsupported"));
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
      message.warning(t("mcpTools.market.quickAddUnsupported"));
      return;
    }

    setAddingService(true);
    try {
      if (selectedOption.transportType === "stdio") {
        const packageIdentifier = (selectedOption.packageIdentifier || "").trim();
        const command = inferStdioCommand(selectedOption.packageRegistryType);
        if (!packageIdentifier || !command) {
          message.warning(t("mcpTools.market.quickAddUnsupported"));
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
          mcp_registry_json: quickAddCandidateService.serverJson || undefined,
        });
      }

      await onServiceAdded();
      message.success(t("mcpTools.market.quickAddSuccess"));
      handleCloseQuickAddPicker();
      onClose();
    } catch (error) {
      log.error("[useMcpToolsAddMarket] Failed to quick add market service", {
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
    marketSearchValue,
    selectedMarketService,
    filteredMarketServices: marketServices,
    marketLoading: marketQuery.isFetching,
    marketPage,
    hasPrevMarketPage: marketCursorHistory.length > 0,
    hasNextMarketPage: Boolean(marketNextCursor),
    marketVersion,
    marketUpdatedSince,
    marketIncludeDeleted,
    quickAddPickerVisible,
    quickAddCandidateService,
    quickAddOptions,
    selectedQuickAddOptionKey,
    quickAddSubmitting: addingService,
    setMarketSearchValue,
    setSelectedMarketService,
    setMarketVersion,
    setMarketUpdatedSince,
    setMarketIncludeDeleted,
    setSelectedQuickAddOptionKey,
    handleMarketPrevPage,
    handleMarketNextPage,
    handleQuickAddFromMarket,
    handleCloseQuickAddPicker,
    handleConfirmQuickAddOption,
    addingService,
    reset,
  };
}
