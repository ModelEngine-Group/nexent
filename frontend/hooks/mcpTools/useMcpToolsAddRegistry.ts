import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { MessageInstance } from "antd/es/message/interface";
import log from "@/lib/logger";
import { MCP_TRANSPORT_TYPE, MCP_TAB } from "@/const/mcpTools";
import {
  checkMcpContainerPortConflictService,
  addContainerMcpToolService,
  addMcpToolService,
  fetchRegistryMcpCards,
  suggestMcpContainerPortService,
  type RegistryMcpCard,
} from "@/services/mcpToolsService";
import {
  type RegistryQuickAddOption,
  type RegistryRemoteVariable,
  type RegistryPackageArgumentInput,
  type McpTab,
} from "@/types/mcpTools";

type UseMcpToolsAddRegistryParams = {
  open: boolean;
  addModalTab: McpTab;
  t: (key: string, params?: Record<string, unknown>) => string;
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
  if (normalized === "oci") return "docker";
  return null;
};

const inferStdioArgs = (registryType?: string, identifier?: string): string[] => {
  const packageId = (identifier || "").trim();
  const normalized = (registryType || "").trim().toLowerCase();
  if (!packageId) return [];
  if (normalized === "npm") return ["-y", packageId];
  if (normalized === "oci") return ["run", packageId];
  return [packageId];
};

const extractPackageEnvTemplate = (service: RegistryMcpCard, pkgIdentifier?: string): Record<string, string> => {
  if (!pkgIdentifier) return {};
  const rawPackages = service.server?.packages;
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

const toStringOrUndefined = (value: unknown): string | undefined => {
  if (value === null || value === undefined) return undefined;
  return String(value);
};

const extractKeyValueInputs = (
  inputs: unknown,
  formPrefix: string,
  fallbackLabel: string
): RegistryRemoteVariable[] => {
  if (!Array.isArray(inputs)) return [];

  return inputs
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item, index) => {
      const name = toStringOrUndefined(item.name)?.trim() || `${fallbackLabel}_${index + 1}`;
      return {
        key: name,
        formKey: `${formPrefix}:${name}`,
        label: name,
        description: toStringOrUndefined(item.description),
        format: toStringOrUndefined(item.format),
        default: toStringOrUndefined(item.default),
        value: toStringOrUndefined(item.value),
        placeholder: toStringOrUndefined(item.placeholder),
        isRequired: typeof item.isRequired === "boolean" ? item.isRequired : undefined,
        isSecret: typeof item.isSecret === "boolean" ? item.isSecret : undefined,
        choices: Array.isArray(item.choices)
          ? item.choices.filter((choice): choice is string => typeof choice === "string")
          : undefined,
        variables: item.variables && typeof item.variables === "object"
          ? (item.variables as Record<string, unknown>)
          : undefined,
      };
    });
};

const extractVariableMapInputs = (
  variables: unknown,
  formPrefix: string
): RegistryRemoteVariable[] => {
  if (!variables || typeof variables !== "object") return [];

  return Object.entries(variables as Record<string, unknown>)
    .filter(([, value]) => Boolean(value) && typeof value === "object")
    .map(([key, value]) => {
      const item = value as Record<string, unknown>;
      return {
        key,
        formKey: `${formPrefix}:${key}`,
        label: key,
        description: toStringOrUndefined(item.description),
        format: toStringOrUndefined(item.format),
        default: toStringOrUndefined(item.default),
        value: toStringOrUndefined(item.value),
        placeholder: toStringOrUndefined(item.placeholder),
        isRequired: typeof item.isRequired === "boolean" ? item.isRequired : undefined,
        isSecret: typeof item.isSecret === "boolean" ? item.isSecret : undefined,
        choices: Array.isArray(item.choices)
          ? item.choices.filter((choice): choice is string => typeof choice === "string")
          : undefined,
        variables: item.variables && typeof item.variables === "object"
          ? (item.variables as Record<string, unknown>)
          : undefined,
      };
    });
};

const extractRuntimeArguments = (runtimeArguments: unknown, formPrefix: string): RegistryPackageArgumentInput[] => {
  if (!Array.isArray(runtimeArguments)) return [];

  return runtimeArguments
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item, index) => {
      const argType = String(item.type || "").toLowerCase() === "named" ? "named" : "positional";
      const name = toStringOrUndefined(item.name)?.trim();
      const valueHint = toStringOrUndefined(item.valueHint)?.trim();
      const keyBase = argType === "named" ? name || `named_${index + 1}` : valueHint || `arg_${index + 1}`;
      return {
        key: keyBase,
        formKey: `${formPrefix}:${keyBase}:${index}`,
        label: argType === "named" ? name || `--arg-${index + 1}` : valueHint || `arg-${index + 1}`,
        type: argType,
        name,
        valueHint,
        description: toStringOrUndefined(item.description),
        format: toStringOrUndefined(item.format),
        default: toStringOrUndefined(item.default),
        value: toStringOrUndefined(item.value),
        isRequired: typeof item.isRequired === "boolean" ? item.isRequired : undefined,
        isSecret: typeof item.isSecret === "boolean" ? item.isSecret : undefined,
        isRepeated: typeof item.isRepeated === "boolean" ? item.isRepeated : undefined,
      };
    });
};

const findMatchedRemote = (service: RegistryMcpCard, remoteType?: string, remoteUrl?: string): Record<string, unknown> | null => {
  const rawRemotes = service.server?.remotes;
  if (!Array.isArray(rawRemotes)) return null;

  const matchedRemote = rawRemotes.find((entry) => {
    if (!entry || typeof entry !== "object") return false;
    const candidate = entry as { type?: unknown; url?: unknown };
    const candidateType = typeof candidate.type === "string" ? candidate.type.toLowerCase() : "";
    const candidateUrl = typeof candidate.url === "string" ? candidate.url : "";
    return candidateType === String(remoteType || "").toLowerCase() && candidateUrl === String(remoteUrl || "");
  }) as Record<string, unknown> | undefined;

  return matchedRemote || null;
};


const extractRemoteVariables = (service: RegistryMcpCard, remoteType?: string, remoteUrl?: string): RegistryRemoteVariable[] => {
  const matchedRemote = findMatchedRemote(service, remoteType, remoteUrl) as { variables?: Record<string, unknown> } | null;

  if (!matchedRemote || !matchedRemote.variables || typeof matchedRemote.variables !== "object") {
    return [];
  }

  return extractVariableMapInputs(matchedRemote.variables, "remote-var");
};


const extractRemoteHeaders = (service: RegistryMcpCard, remoteType?: string, remoteUrl?: string): RegistryRemoteVariable[] => {
  const matchedRemote = findMatchedRemote(service, remoteType, remoteUrl);
  if (!matchedRemote) return [];
  return extractKeyValueInputs(matchedRemote.headers, "remote-header", "header");
};

const buildInitialVariableValues = (option: RegistryQuickAddOption | null): Record<string, string> => {
  if (!option) {
    return {};
  }

  const fields: RegistryRemoteVariable[] = [
    ...(option.remoteVariables || []),
    ...(option.remoteHeaders || []),
    ...(option.packageEnvironmentVariables || []),
    ...(option.packageTransportHeaders || []),
    ...(option.packageTransportVariables || []),
  ];

  const values = fields.reduce<Record<string, string>>((acc, field) => {
    if (!field.formKey) return acc;
    const initial = typeof field.value === "string" ? field.value : typeof field.default === "string" ? field.default : "";
    acc[field.formKey] = initial;
    return acc;
  }, {});

  (option.packageRuntimeArguments || []).forEach((arg) => {
    const initial = typeof arg.value === "string" ? arg.value : typeof arg.default === "string" ? arg.default : "";
    values[arg.formKey] = initial;
  });

  return values;
};

const applyUrlTemplateVariables = (template: string, values: Record<string, string>): string => {
  return template.replace(/\{([^{}]+)\}/g, (_match, variableName) => {
    const key = String(variableName || "").trim();
    return Object.prototype.hasOwnProperty.call(values, key) ? values[key] : _match;
  });
};

const getFieldValueByFormKey = (values: Record<string, string>, formKey?: string): string => {
  if (!formKey) return "";
  return String(values[formKey] || "").trim();
};

const isFieldRequired = (field: { isRequired?: boolean }) => Boolean(field.isRequired);

const normalizeHeaderKey = (value: string | undefined): string => String(value || "").trim().toLowerCase();

const isAuthorizationHeader = (field: RegistryRemoteVariable): boolean => {
  const key = normalizeHeaderKey(field.key);
  const label = normalizeHeaderKey(field.label);
  return key === "authorization" || label === "authorization";
};

const pickSupportedAuthorizationHeaders = (headers: RegistryRemoteVariable[] | undefined): RegistryRemoteVariable[] => {
  return (headers || []).filter(isAuthorizationHeader);
};

const collectUnsupportedRequiredHeaderNames = (headers: RegistryRemoteVariable[] | undefined): string[] => {
  return (headers || [])
    .filter((header) => isFieldRequired(header) && !isAuthorizationHeader(header))
    .map((header) => (header.label || header.key || "header").trim())
    .filter((name, index, arr) => Boolean(name) && arr.indexOf(name) === index);
};

const buildResolvedRuntimeArgs = (option: RegistryQuickAddOption, values: Record<string, string>): string[] => {
  const runtimeArgs = option.packageRuntimeArguments || [];
  if (runtimeArgs.length === 0) {
    return inferStdioArgs(option.packageRegistryType, option.packageIdentifier);
  }

  const args: string[] = [];
  runtimeArgs.forEach((arg) => {
    const finalValue = getFieldValueByFormKey(values, arg.formKey);
    if (!finalValue) return;

    if (arg.type === "named") {
      const flag = (arg.name || "").trim();
      if (!flag) return;
      args.push(`${flag}=${finalValue}`);
      return;
    }
    args.push(finalValue);
  });
  return args;
};

const resolveAuthorizationFromHeaders = (
  headers: RegistryRemoteVariable[] | undefined,
  values: Record<string, string>
): string | undefined => {
  const authorizationHeader = (headers || []).find((header) => header.key.toLowerCase() === "authorization");
  if (!authorizationHeader?.formKey) return undefined;
  const value = getFieldValueByFormKey(values, authorizationHeader.formKey);
  return value || undefined;
};

const resolveQuickAddOptions = (service: RegistryMcpCard): RegistryQuickAddOption[] => {
  const options: RegistryQuickAddOption[] = [];
  const rawPackages = service.server?.packages;
  const packageCandidates = Array.isArray(rawPackages)
    ? rawPackages.filter((pkg): pkg is Record<string, unknown> => Boolean(pkg) && typeof pkg === "object")
    : [];

  (service.server?.remotes || []).forEach((remote, index) => {
    const remoteTarget = resolveQuickAddTarget(remote.type, remote.url);
    if (!remoteTarget) return;

    const remoteVariables = extractRemoteVariables(service, remote.type, remote.url);
    const allRemoteHeaders = extractRemoteHeaders(service, remote.type, remote.url);
    const remoteHeaders = pickSupportedAuthorizationHeaders(allRemoteHeaders);
    const unsupportedRequiredHeaders = collectUnsupportedRequiredHeaderNames(allRemoteHeaders);

    options.push({
      key: `remote-${index}`,
      sourceType: "remote",
      sourceLabel: `${remote.type || "remote"} - ${remote.url}`,
      transportType: remoteTarget.transportType,
      serverUrl: remoteTarget.serverUrl,
      serverUrlTemplate: remote.url,
      remoteVariables,
      remoteHeaders,
      unsupportedRequiredHeaders,
    });
  });

  packageCandidates.forEach((rawPackage, index) => {
    const packageIdentifier = toStringOrUndefined(rawPackage.identifier)?.trim() || "package";
    const packageRegistryType = toStringOrUndefined(rawPackage.registryType)?.trim() || "";
    const packageTransport = rawPackage.transport && typeof rawPackage.transport === "object"
      ? (rawPackage.transport as Record<string, unknown>)
      : undefined;
    const transportType = toStringOrUndefined(packageTransport?.type) || "remote";
    const transportUrl = toStringOrUndefined(packageTransport?.url) || "";

    const packageTarget = resolveQuickAddTarget(transportType, transportUrl);
    const allPackageTransportHeaders = extractKeyValueInputs(packageTransport?.headers, `pkg-transport-header:${index}`, "header");
    const packageTransportHeaders = pickSupportedAuthorizationHeaders(allPackageTransportHeaders);
    const unsupportedRequiredHeaders = collectUnsupportedRequiredHeaderNames(allPackageTransportHeaders);
    const packageTransportVariables = extractVariableMapInputs(packageTransport?.variables, `pkg-transport-var:${index}`);
    const packageEnvironmentVariables = extractKeyValueInputs(rawPackage?.environmentVariables, `pkg-env:${index}`, "env");
    const packageRuntimeArguments = extractRuntimeArguments(rawPackage?.runtimeArguments, `pkg-runtime-arg:${index}`);
    const packageArguments = extractRuntimeArguments(rawPackage?.packageArguments, `pkg-arg:${index}`);
    const packageRuntimeHint = toStringOrUndefined(rawPackage?.runtimeHint) || undefined;

    if (packageTarget) {
      options.push({
        key: `package-${index}`,
        sourceType: "package",
        sourceLabel: `${packageIdentifier} - ${transportType} - ${transportUrl}`,
        transportType: packageTarget.transportType,
        serverUrl: packageTarget.serverUrl,
        serverUrlTemplate: transportUrl || undefined,
        packageIndex: index,
        packageRuntimeHint,
        packageEnvironmentVariables,
        packageTransportHeaders,
        unsupportedRequiredHeaders,
        packageTransportVariables,
        packageRuntimeArguments,
        packageArguments,
        packageIdentifier,
        packageRegistryType,
      });
      return;
    }

    if (transportType.trim().toLowerCase() === "stdio") {
      options.push({
        key: `package-${index}`,
        sourceType: "package",
        sourceLabel: `${packageIdentifier} - stdio`,
        transportType: "stdio",
        packageIndex: index,
        packageRuntimeHint,
        packageEnvironmentVariables,
        packageTransportHeaders,
        unsupportedRequiredHeaders,
        packageTransportVariables,
        packageRuntimeArguments,
        packageArguments,
        packageIdentifier,
        packageRegistryType,
        packageEnvTemplate: extractPackageEnvTemplate(service, packageIdentifier),
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
  const [debouncedRegistrySearchValue, setDebouncedRegistrySearchValue] = useState("");
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
  const [quickAddVariableValues, setQuickAddVariableValues] = useState<Record<string, string>>({});
  const [quickAddContainerPort, setQuickAddContainerPort] = useState<number | undefined>(undefined);
  const [debouncedQuickAddContainerPort, setDebouncedQuickAddContainerPort] = useState<number | undefined>(undefined);
  const [suggestingContainerPort, setSuggestingContainerPort] = useState(false);
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
    setQuickAddVariableValues({});
    setQuickAddContainerPort(undefined);
    setDebouncedQuickAddContainerPort(undefined);
    setSuggestingContainerPort(false);
    setAddingService(false);
  }, []);

  const loadRegistryFirstPage = useCallback(() => {
    setRegistryCurrentCursor(null);
    setRegistryCursorHistory([]);
    setRegistryPage(1);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedRegistrySearchValue(registrySearchValue);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [registrySearchValue]);

  useEffect(() => {
    if (!(open && addModalTab === MCP_TAB.MCP_REGISTRY)) return;
    loadRegistryFirstPage();
  }, [
    open,
    addModalTab,
    debouncedRegistrySearchValue,
    registryVersion,
    registryUpdatedSince,
    registryIncludeDeleted,
    loadRegistryFirstPage,
  ]);

  const registryQuery = useQuery<{ items: RegistryMcpCard[]; nextCursor: string | null }>({
    queryKey: [
      "mcp-tools",
      "market",
      debouncedRegistrySearchValue,
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
        search: debouncedRegistrySearchValue,
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
      search: debouncedRegistrySearchValue,
      cursor: registryCurrentCursor,
      version: registryVersion,
      updatedSince: registryUpdatedSince,
      includeDeleted: registryIncludeDeleted,
    });
    message.error(t("mcpTools.registry.loadFailed"));
  }, [
    registryQuery.error,
    debouncedRegistrySearchValue,
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
    setQuickAddVariableValues({});
    setQuickAddContainerPort(undefined);
    setDebouncedQuickAddContainerPort(undefined);
    setSuggestingContainerPort(false);
  }, []);

  useEffect(() => {
    const selectedOption = quickAddOptions.find((option) => option.key === selectedQuickAddOptionKey) || null;
    if (!(quickAddPickerVisible && selectedOption?.transportType === "stdio" && typeof quickAddContainerPort === "number")) {
      setDebouncedQuickAddContainerPort(undefined);
      return;
    }

    const timer = window.setTimeout(() => {
      setDebouncedQuickAddContainerPort(quickAddContainerPort);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [quickAddPickerVisible, quickAddOptions, selectedQuickAddOptionKey, quickAddContainerPort]);

  const registryContainerPortCheckQuery = useQuery({
    queryKey: ["mcp-tools", "registry-container-port-check", debouncedQuickAddContainerPort],
    enabled: quickAddPickerVisible && typeof debouncedQuickAddContainerPort === "number",
    retry: false,
    staleTime: 10_000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    queryFn: async () => {
      const result = await checkMcpContainerPortConflictService({
        port: debouncedQuickAddContainerPort as number,
      });
      return result.data;
    },
  });

  const isCurrentPortChecked =
    typeof quickAddContainerPort === "number" &&
    debouncedQuickAddContainerPort === quickAddContainerPort &&
    typeof registryContainerPortCheckQuery.data?.available === "boolean";
  const containerPortCheckLoading =
    quickAddPickerVisible &&
    typeof quickAddContainerPort === "number" &&
    !isCurrentPortChecked &&
    !registryContainerPortCheckQuery.isError;
  const containerPortAvailable = registryContainerPortCheckQuery.data?.available === true;

  const handleSuggestContainerPort = useCallback(async () => {
    setSuggestingContainerPort(true);
    try {
      const startPort = Math.max((quickAddContainerPort || 5500) + 1, 1);
      const result = await suggestMcpContainerPortService({ start_port: startPort });
      setQuickAddContainerPort(result.data.port);
      message.success(t("mcpTools.addModal.portSuggested", { port: result.data.port }));
    } catch (error) {
      log.error("[useMcpToolsAddRegistry] Failed to suggest container port", { error });
      message.error(t("mcpTools.addModal.portSuggestFailed"));
    } finally {
      setSuggestingContainerPort(false);
    }
  }, [message, quickAddContainerPort, t]);

  useEffect(() => {
    const selectedOption = quickAddOptions.find((option) => option.key === selectedQuickAddOptionKey) || null;
    setQuickAddVariableValues(buildInitialVariableValues(selectedOption));
  }, [quickAddOptions, selectedQuickAddOptionKey]);

  const handleQuickAddVariableValueChange = useCallback((key: string, value: string) => {
    setQuickAddVariableValues((prev) => ({ ...prev, [key]: value }));
  }, []);

  const handleQuickAddFromRegistry = useCallback((service: RegistryMcpCard) => {
    const quickAddOptionsForService = resolveQuickAddOptions(service);
    if (quickAddOptionsForService.length === 0) {
      log.warn("[useMcpToolsAddRegistry] Quick add is unsupported for selected registry service", {
        serviceName: service.server?.name,
        remotes: service.server?.remotes,
        packages: service.server?.packages,
      });
      message.warning(t("mcpTools.registry.quickAddUnsupported"));
      return;
    }

    setQuickAddCandidateService(service);
    setQuickAddOptions(quickAddOptionsForService);
    setSelectedQuickAddOptionKey(quickAddOptionsForService[0]?.key || "");
    setQuickAddContainerPort(undefined);
    setDebouncedQuickAddContainerPort(undefined);
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

    const packageRegistryType = (selectedOption.packageRegistryType || "").trim().toLowerCase();
    if (selectedOption.sourceType === "package" && packageRegistryType === "oci") {
      log.warn("[useMcpToolsAddRegistry] OCI package is blocked for quick add", {
        serviceName: quickAddCandidateService.server?.name,
        packageIdentifier: selectedOption.packageIdentifier,
        transportType: selectedOption.transportType,
      });
      message.warning(t("mcpTools.registry.quickAddUnsupported"));
      return;
    }

    if ((selectedOption.unsupportedRequiredHeaders || []).length > 0) {
      message.warning(
        t("mcpTools.registry.quickAddPicker.unsupportedRequiredHeaders", {
          headers: (selectedOption.unsupportedRequiredHeaders || []).join(", "),
        })
      );
      return;
    }

    setAddingService(true);
    try {
      if (selectedOption.transportType === "stdio") {
        const packageIdentifier = (selectedOption.packageIdentifier || "").trim();
        const packageRegistryType = (selectedOption.packageRegistryType || "").trim().toLowerCase();
        const packageRuntimeHint = (selectedOption.packageRuntimeHint || "").trim();
        if (packageRegistryType === "oci") {
          log.warn("[useMcpToolsAddRegistry] OCI stdio package is blocked for quick add because runtime container cannot execute nested docker", {
            serviceName: quickAddCandidateService.server?.name,
            packageIdentifier,
            packageRuntimeHint,
          });
          message.warning(t("mcpTools.registry.quickAddUnsupported"));
          return;
        }

        const command = packageRuntimeHint || inferStdioCommand(selectedOption.packageRegistryType);
        if (!packageIdentifier || !command) {
          message.warning(t("mcpTools.registry.quickAddUnsupported"));
          return;
        }

        if (!quickAddContainerPort) {
          message.warning(t("mcpTools.add.validate.containerRequired"));
          return;
        }

        const requiredFields = [
          ...(selectedOption.packageEnvironmentVariables || []),
          ...(selectedOption.packageTransportHeaders || []),
          ...(selectedOption.packageTransportVariables || []),
          ...(selectedOption.packageRuntimeArguments || []),
        ];
        for (const field of requiredFields) {
          const value = getFieldValueByFormKey(quickAddVariableValues, "formKey" in field ? field.formKey : undefined);
          if (isFieldRequired(field) && !value) {
            const key = typeof field.label === "string" && field.label.trim() ? field.label : field.key;
            message.warning(t("mcpTools.registry.quickAddPicker.variableRequiredMissing", { key }));
            return;
          }
        }

        const portCheck = await checkMcpContainerPortConflictService({
          port: quickAddContainerPort,
        });
        if (!portCheck.data.available) {
          message.error(t("mcpTools.addModal.portOccupied", { port: quickAddContainerPort }));
          return;
        }

        const serverKey = normalizeServerKey(packageIdentifier);

        const envFromPackage = (selectedOption.packageEnvironmentVariables || []).reduce<Record<string, string>>((acc, envVar) => {
          const value = getFieldValueByFormKey(quickAddVariableValues, envVar.formKey);
          if (!value) return acc;
          acc[envVar.key] = value;
          return acc;
        }, {});

        await addContainerMcpToolService({
          name: quickAddCandidateService.server?.name || "",
          description: quickAddCandidateService.server?.description || "",
          tags: [],
          authorization_token: resolveAuthorizationFromHeaders(selectedOption.packageTransportHeaders, quickAddVariableValues),
          port: quickAddContainerPort,
          mcp_config: {
            mcpServers: {
              [serverKey]: {
                command,
                args: buildResolvedRuntimeArgs(selectedOption, quickAddVariableValues),
                env: {
                  ...(selectedOption.packageEnvTemplate || {}),
                  ...envFromPackage,
                },
              },
            },
          },
          registry_json: quickAddCandidateService.server,
        });
      } else {
        const requiredFields = [
          ...(selectedOption.remoteVariables || []),
          ...(selectedOption.remoteHeaders || []),
          ...(selectedOption.packageTransportVariables || []),
          ...(selectedOption.packageTransportHeaders || []),
        ];
        for (const field of requiredFields) {
          const value = getFieldValueByFormKey(quickAddVariableValues, field.formKey);
          if (isFieldRequired(field) && !value) {
            message.warning(t("mcpTools.registry.quickAddPicker.variableRequiredMissing", { key: field.label || field.key }));
            return;
          }
        }

        const mergedTemplateValues = {
          ...(selectedOption.remoteVariables || []).reduce<Record<string, string>>((acc, variable) => {
            if (!variable.formKey) return acc;
            const value = getFieldValueByFormKey(quickAddVariableValues, variable.formKey);
            if (value) acc[variable.key] = value;
            return acc;
          }, {}),
          ...(selectedOption.packageTransportVariables || []).reduce<Record<string, string>>((acc, variable) => {
            if (!variable.formKey) return acc;
            const value = getFieldValueByFormKey(quickAddVariableValues, variable.formKey);
            if (value) acc[variable.key] = value;
            return acc;
          }, {}),
        };

        const templateUrl = selectedOption.serverUrlTemplate || selectedOption.serverUrl || "";
        const resolvedUrl = applyUrlTemplateVariables(templateUrl, mergedTemplateValues);
        if (/\{[^{}]+\}/.test(resolvedUrl)) {
          message.warning(t("mcpTools.registry.quickAddPicker.variableUnresolved"));
          return;
        }

        await addMutation.mutateAsync({
          name: quickAddCandidateService.server?.name || "",
          description: quickAddCandidateService.server?.description || "",
          source: MCP_TAB.MCP_REGISTRY,
          transport_type: selectedOption.transportType === "sse" ? MCP_TRANSPORT_TYPE.SSE : MCP_TRANSPORT_TYPE.HTTP,
          server_url: resolvedUrl,
          tags: [],
          authorization_token: resolveAuthorizationFromHeaders(
            [...(selectedOption.remoteHeaders || []), ...(selectedOption.packageTransportHeaders || [])],
            quickAddVariableValues
          ),
          version: quickAddCandidateService.server?.version || undefined,
          registry_json: quickAddCandidateService.server,
        });
      }

      await onServiceAdded();
      message.success(t("mcpTools.registry.quickAddSuccess"));
      handleCloseQuickAddPicker();
      onClose();
    } catch (error) {
      log.error("[useMcpToolsAddRegistry] Failed to quick add registry service", {
        error,
        serviceName: quickAddCandidateService.server?.name,
        remotes: quickAddCandidateService.server?.remotes,
        packages: quickAddCandidateService.server?.packages,
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
    quickAddContainerPort,
    quickAddVariableValues,
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
    quickAddVariableValues,
    quickAddContainerPort,
    quickAddSubmitting: addingService,
    setQuickAddContainerPort,
    handleSuggestContainerPort,
    containerPortCheckLoading,
    containerPortSuggesting: suggestingContainerPort,
    containerPortAvailable,
    setRegistrySearchValue,
    setSelectedRegistryService,
    setRegistryVersion,
    setRegistryUpdatedSince,
    setRegistryIncludeDeleted,
    setSelectedQuickAddOptionKey,
    handleQuickAddVariableValueChange,
    handleRegistryPrevPage,
    handleRegistryNextPage,
    handleQuickAddFromRegistry,
    handleCloseQuickAddPicker,
    handleConfirmQuickAddOption,
    addingService,
    reset,
  };
}
