import type { McpServer } from "@/types/agentConfig";
import type {
  McpServiceItem,
  RegistryMcpCard,
  RegistryPackageArgumentInput,
  RegistryQuickAddOption,
  RegistryRemoteVariable,
} from "@/types/mcpTools";
import {
  MCP_PORT_RANGE,
  McpContainerStatus,
  McpHealthStatus,
  McpSource,
  McpTransportType,
} from "@/const/mcpTools";

// ---------------------------------------------------------------------------
// Label resolvers (used by cards / detail modals)
// ---------------------------------------------------------------------------

/** i18n key for the label shown next to a service's `source` enum. */
export const getSourceLabelKey = (source: McpServiceItem["source"]): string => {
  if (source === McpSource.LOCAL) return "mcpTools.source.local";
  if (source === McpSource.COMMUNITY) return "mcpTools.source.community";
  return "mcpTools.source.registry";
};

/** i18n key for the label shown next to a service's `transportType` enum. */
export const getTransportLabelKey = (
  transportType: McpTransportType | string
): string => {
  if (transportType === McpTransportType.HTTP)
    return "mcpTools.serverType.http";
  if (transportType === McpTransportType.SSE)
    return "mcpTools.serverType.sse";
  if (transportType === McpTransportType.CONTAINER)
    return "mcpTools.serverType.container";
  return "mcpTools.serverType.url";
};

/** i18n key for a service's `healthStatus`. */
export const getHealthStatusKey = (status: McpHealthStatus): string => {
  if (status === McpHealthStatus.HEALTHY) return "mcpTools.health.healthy";
  if (status === McpHealthStatus.UNHEALTHY)
    return "mcpTools.health.unhealthy";
  return "mcpTools.health.unchecked";
};

/** i18n key for a service's container `containerStatus`. */
export const getContainerStatusKey = (
  status: McpContainerStatus | undefined
): string => {
  if (status === McpContainerStatus.RUNNING)
    return "mcpTools.containerStatus.running";
  if (status === McpContainerStatus.STOPPED)
    return "mcpTools.containerStatus.stopped";
  return "mcpTools.containerStatus.unknown";
};

export const filterServiceCards = (
  services: McpServiceItem[],
  searchValue: string
): McpServiceItem[] => {
  const keyword = searchValue.trim().toLowerCase();
  if (!keyword) {
    return services;
  }

  return services.filter((item) => {
    return (
      item.name.toLowerCase().includes(keyword) ||
      (item.description ?? "").toLowerCase().includes(keyword) ||
      item.tags.some((tag) => tag.toLowerCase().includes(keyword))
    );
  });
};

// ---------------------------------------------------------------------------
// Registry/community formatters
// ---------------------------------------------------------------------------

export const formatRegistryDate = (value: string): string => {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()}`;
};

export const formatRegistryVersion = (value: string): string => {
  const version = (value || "").trim();
  if (!version) return "-";
  return /^v/i.test(version) ? version : `v${version}`;
};

export const extractRegistryLinks = (
  registryJson?: Record<string, unknown>
) => {
  if (!registryJson || typeof registryJson !== "object") {
    return { websiteUrl: "", repositoryUrl: "" };
  }

  const websiteUrlRaw = registryJson.websiteUrl;
  const websiteUrl = typeof websiteUrlRaw === "string" ? websiteUrlRaw : "";

  const repositoryRaw = registryJson.repository;
  let repositoryUrl = "";
  if (repositoryRaw && typeof repositoryRaw === "object") {
    const repositoryUrlRaw = (repositoryRaw as Record<string, unknown>).url;
    repositoryUrl =
      typeof repositoryUrlRaw === "string" ? repositoryUrlRaw : "";
  }

  return { websiteUrl, repositoryUrl };
};

export const toPrettyRegistryJson = (
  registryJson?: Record<string, unknown>
) => {
  return JSON.stringify(registryJson || {}, null, 2);
};

// ---------------------------------------------------------------------------
// Generic validators
// ---------------------------------------------------------------------------

export const isHttpUrl = (value: string): boolean => {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
};

export const isSameStringArray = (
  left: string[] = [],
  right: string[] = []
) => {
  if (left.length !== right.length) return false;
  return left.every((item, index) => item === right[index]);
};

// ---------------------------------------------------------------------------
// Registry quick-add builders
// ---------------------------------------------------------------------------

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
    .filter(
      (item): item is Record<string, unknown> =>
        Boolean(item) && typeof item === "object"
    )
    .map((item, index) => {
      const name =
        toStringOrUndefined(item.name)?.trim() ||
        `${fallbackLabel}_${index + 1}`;
      return {
        key: name,
        formKey: `${formPrefix}:${name}`,
        label: name,
        description: toStringOrUndefined(item.description),
        format: toStringOrUndefined(item.format),
        default: toStringOrUndefined(item.default),
        value: toStringOrUndefined(item.value),
        placeholder: toStringOrUndefined(item.placeholder),
        isRequired:
          typeof item.isRequired === "boolean" ? item.isRequired : undefined,
        isSecret:
          typeof item.isSecret === "boolean" ? item.isSecret : undefined,
        choices: Array.isArray(item.choices)
          ? item.choices.filter(
              (choice): choice is string => typeof choice === "string"
            )
          : undefined,
        variables:
          item.variables && typeof item.variables === "object"
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
        isRequired:
          typeof item.isRequired === "boolean" ? item.isRequired : undefined,
        isSecret:
          typeof item.isSecret === "boolean" ? item.isSecret : undefined,
        choices: Array.isArray(item.choices)
          ? item.choices.filter(
              (choice): choice is string => typeof choice === "string"
            )
          : undefined,
        variables:
          item.variables && typeof item.variables === "object"
            ? (item.variables as Record<string, unknown>)
            : undefined,
      };
    });
};

const extractRuntimeArguments = (
  runtimeArguments: unknown,
  formPrefix: string
): RegistryPackageArgumentInput[] => {
  if (!Array.isArray(runtimeArguments)) return [];

  return runtimeArguments
    .filter(
      (item): item is Record<string, unknown> =>
        Boolean(item) && typeof item === "object"
    )
    .map((item, index) => {
      const argType =
        String(item.type || "").toLowerCase() === "named"
          ? "named"
          : "positional";
      const name = toStringOrUndefined(item.name)?.trim();
      const valueHint = toStringOrUndefined(item.valueHint)?.trim();
      const keyBase =
        argType === "named"
          ? name || `named_${index + 1}`
          : valueHint || `arg_${index + 1}`;
      return {
        key: keyBase,
        formKey: `${formPrefix}:${keyBase}:${index}`,
        label:
          argType === "named"
            ? name || `--arg-${index + 1}`
            : valueHint || `arg-${index + 1}`,
        type: argType,
        name,
        valueHint,
        description: toStringOrUndefined(item.description),
        format: toStringOrUndefined(item.format),
        default: toStringOrUndefined(item.default),
        value: toStringOrUndefined(item.value),
        isRequired:
          typeof item.isRequired === "boolean" ? item.isRequired : undefined,
        isSecret:
          typeof item.isSecret === "boolean" ? item.isSecret : undefined,
        isRepeated:
          typeof item.isRepeated === "boolean" ? item.isRepeated : undefined,
      };
    });
};

const resolveQuickAddTarget = (
  type?: string | null,
  url?: string | null
): { transportType: "http" | "sse"; serverUrl: string } | null => {
  const serverUrl = String(url || "").trim();
  if (!serverUrl) return null;

  const normalizedType = String(type || "")
    .trim()
    .toLowerCase();
  if (normalizedType === "sse") {
    return { transportType: McpTransportType.SSE, serverUrl };
  }
  if (normalizedType === "streamable-http" || normalizedType === "http") {
    return { transportType: McpTransportType.HTTP, serverUrl };
  }
  if (/^https?:\/\//i.test(serverUrl)) {
    return { transportType: McpTransportType.HTTP, serverUrl };
  }

  return null;
};

const findMatchedRemote = (
  service: RegistryMcpCard,
  remoteType?: string,
  remoteUrl?: string
): Record<string, unknown> | null => {
  const rawRemotes = service.server?.remotes;
  if (!Array.isArray(rawRemotes)) return null;

  const matched = rawRemotes.find((entry) => {
    if (!entry || typeof entry !== "object") return false;
    const candidate = entry as { type?: unknown; url?: unknown };
    const candidateType =
      typeof candidate.type === "string" ? candidate.type.toLowerCase() : "";
    const candidateUrl = typeof candidate.url === "string" ? candidate.url : "";
    return (
      candidateType === String(remoteType || "").toLowerCase() &&
      candidateUrl === String(remoteUrl || "")
    );
  }) as Record<string, unknown> | undefined;

  return matched || null;
};

const extractPackageEnvTemplate = (
  service: RegistryMcpCard,
  pkgIdentifier?: string
): Record<string, string> => {
  if (!pkgIdentifier) return {};
  const rawPackages = service.server?.packages;
  if (!Array.isArray(rawPackages)) return {};

  const targetPackage = rawPackages.find((entry) => {
    if (!entry || typeof entry !== "object") return false;
    const identifier = String(
      (entry as { identifier?: unknown }).identifier || ""
    ).trim();
    return identifier === pkgIdentifier;
  }) as
    | { environmentVariables?: Array<{ name?: string; default?: string }> }
    | undefined;

  const environmentVariables = targetPackage?.environmentVariables;
  if (!Array.isArray(environmentVariables)) return {};

  return environmentVariables.reduce<Record<string, string>>((acc, item) => {
    const envName = String(item?.name || "").trim();
    if (!envName) return acc;
    acc[envName] = String(item?.default || "");
    return acc;
  }, {});
};

const normalizeHeaderKey = (value: string | undefined): string =>
  String(value || "")
    .trim()
    .toLowerCase();

const isAuthorizationHeader = (field: RegistryRemoteVariable): boolean => {
  const key = normalizeHeaderKey(field.key);
  const label = normalizeHeaderKey(field.label);
  return key === "authorization" || label === "authorization";
};

const pickSupportedAuthorizationHeaders = (
  headers: RegistryRemoteVariable[] | undefined
): RegistryRemoteVariable[] => (headers || []).filter(isAuthorizationHeader);

const collectUnsupportedRequiredHeaderNames = (
  headers: RegistryRemoteVariable[] | undefined
): string[] => {
  return (headers || [])
    .filter((header) => header.isRequired && !isAuthorizationHeader(header))
    .map((header) => (header.label || header.key || "header").trim())
    .filter((name, index, arr) => Boolean(name) && arr.indexOf(name) === index);
};

export const inferContainerRuntimeCommand = (
  registryType?: string
): string | null => {
  const normalized = (registryType || "").trim().toLowerCase();
  if (normalized === "npm") return "npx";
  if (normalized === "pypi") return "uvx";
  return null;
};

const inferContainerRuntimeArgs = (
  registryType?: string,
  identifier?: string
): string[] => {
  const packageId = (identifier || "").trim();
  const normalized = (registryType || "").trim().toLowerCase();
  if (!packageId) return [];
  if (normalized === "npm") return ["-y", packageId];
  return [packageId];
};

export const normalizeServerKey = (raw: string): string => {
  const normalized = raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  return normalized;
};

/**
 * Build the list of quick-add targets (remote URLs + packages) that a registry
 * service exposes. The caller only needs to pick one option.
 */
export const resolveQuickAddOptions = (
  service: RegistryMcpCard
): RegistryQuickAddOption[] => {
  const options: RegistryQuickAddOption[] = [];
  const packageCandidates = Array.isArray(service.server?.packages)
    ? service.server.packages.filter(
        (pkg): pkg is Record<string, unknown> =>
          Boolean(pkg) && typeof pkg === "object"
      )
    : [];

  (service.server?.remotes || []).forEach((remote, index) => {
    const remoteTarget = resolveQuickAddTarget(remote.type, remote.url);
    if (!remoteTarget) return;

    const matchedRemote = findMatchedRemote(
      service,
      remote.type,
      remote.url
    ) as { variables?: Record<string, unknown>; headers?: unknown } | null;
    const remoteVariables = matchedRemote?.variables
      ? extractVariableMapInputs(matchedRemote.variables, "remote-var")
      : [];
    const allRemoteHeaders = matchedRemote
      ? extractKeyValueInputs(matchedRemote.headers, "remote-header", "header")
      : [];

    options.push({
      key: `remote-${index}`,
      sourceType: "remote",
      sourceLabel: `${remote.type || "remote"} - ${remote.url}`,
      transportType: remoteTarget.transportType as McpTransportType,
      serverUrl: remoteTarget.serverUrl,
      remoteVariables,
      remoteHeaders: pickSupportedAuthorizationHeaders(allRemoteHeaders),
      unsupportedRequiredHeaders:
        collectUnsupportedRequiredHeaderNames(allRemoteHeaders),
    });
  });

  packageCandidates.forEach((rawPackage, index) => {
    const packageIdentifier =
      toStringOrUndefined(rawPackage.identifier)?.trim() || "package";
    const packageRegistryType =
      toStringOrUndefined(rawPackage.registryType)?.trim() || "";
    const packageTransport =
      rawPackage.transport && typeof rawPackage.transport === "object"
        ? (rawPackage.transport as Record<string, unknown>)
        : undefined;
    const transportType = toStringOrUndefined(packageTransport?.type) || "";
    const transportUrl = toStringOrUndefined(packageTransport?.url) || "";

    const packageTarget = resolveQuickAddTarget(transportType, transportUrl);
    const allPackageTransportHeaders = extractKeyValueInputs(
      packageTransport?.headers,
      `pkg-transport-header:${index}`,
      "header"
    );
    const packageTransportVariables = extractVariableMapInputs(
      packageTransport?.variables,
      `pkg-transport-var:${index}`
    );
    const packageEnvironmentVariables = extractKeyValueInputs(
      rawPackage?.environmentVariables,
      `pkg-env:${index}`,
      "env"
    );
    const packageRuntimeArguments = extractRuntimeArguments(
      rawPackage?.runtimeArguments,
      `pkg-runtime-arg:${index}`
    );
    const packageArguments = extractRuntimeArguments(
      rawPackage?.packageArguments,
      `pkg-arg:${index}`
    );
    const packageRuntimeHint =
      toStringOrUndefined(rawPackage?.runtimeHint) || undefined;

    const basePackageOption = {
      sourceType: "package" as const,
      packageRuntimeHint,
      packageEnvironmentVariables,
      packageTransportHeaders: pickSupportedAuthorizationHeaders(
        allPackageTransportHeaders
      ),
      unsupportedRequiredHeaders: collectUnsupportedRequiredHeaderNames(
        allPackageTransportHeaders
      ),
      packageTransportVariables,
      packageRuntimeArguments,
      packageArguments,
      packageIdentifier,
      packageRegistryType,
    };

    if (packageTarget) {
      options.push({
        ...basePackageOption,
        key: `package-${index}`,
        sourceLabel: `${packageIdentifier} - ${transportType} - ${transportUrl}`,
        transportType: packageTarget.transportType as McpTransportType,
        serverUrl: packageTarget.serverUrl,
      });
      return;
    }

    if (transportType.trim().toLowerCase() === "stdio") {
      options.push({
        ...basePackageOption,
        key: `package-${index}`,
        sourceLabel: `${packageIdentifier} - stdio`,
        transportType: McpTransportType.CONTAINER,
        packageEnvTemplate: extractPackageEnvTemplate(
          service,
          packageIdentifier
        ),
      });
    }
  });

  return options;
};

export const buildInitialQuickAddValues = (
  option: RegistryQuickAddOption | null
): Record<string, string> => {
  if (!option) return {};

  const fields: RegistryRemoteVariable[] = [
    ...(option.remoteVariables || []),
    ...(option.remoteHeaders || []),
    ...(option.packageEnvironmentVariables || []),
    ...(option.packageTransportHeaders || []),
    ...(option.packageTransportVariables || []),
  ];

  const values = fields.reduce<Record<string, string>>((acc, field) => {
    if (!field.formKey) return acc;
    const initial =
      typeof field.value === "string"
        ? field.value
        : typeof field.default === "string"
          ? field.default
          : "";
    acc[field.formKey] = initial;
    return acc;
  }, {});

  (option.packageRuntimeArguments || []).forEach((arg) => {
    const initial =
      typeof arg.value === "string"
        ? arg.value
        : typeof arg.default === "string"
          ? arg.default
          : "";
    values[arg.formKey] = initial;
  });

  return values;
};

const applyUrlTemplateVariables = (
  template: string,
  values: Record<string, string>
): string => {
  return template.replace(/\{([^{}]+)\}/g, (_match, variableName) => {
    const key = String(variableName || "").trim();
    return Object.prototype.hasOwnProperty.call(values, key)
      ? values[key]
      : _match;
  });
};

const getValueByFormKey = (
  values: Record<string, string>,
  formKey?: string
): string => {
  if (!formKey) return "";
  return String(values[formKey] || "").trim();
};

export const resolveRuntimeArgs = (
  option: RegistryQuickAddOption,
  values: Record<string, string>
): string[] => {
  const runtimeArgs = option.packageRuntimeArguments || [];
  if (runtimeArgs.length === 0) {
    return inferContainerRuntimeArgs(
      option.packageRegistryType,
      option.packageIdentifier
    );
  }

  const args: string[] = [];
  runtimeArgs.forEach((arg) => {
    const finalValue = getValueByFormKey(values, arg.formKey);
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

export const resolveAuthorizationFromHeaders = (
  headers: RegistryRemoteVariable[] | undefined,
  values: Record<string, string>
): string | undefined => {
  const authorizationHeader = (headers || []).find(
    (header) => header.key.toLowerCase() === "authorization"
  );
  if (!authorizationHeader?.formKey) return undefined;
  const value = getValueByFormKey(values, authorizationHeader.formKey);
  return value || undefined;
};

export const resolveHttpServerUrl = (
  option: RegistryQuickAddOption,
  values: Record<string, string>
): string => {
  const mergedValues = {
    ...(option.remoteVariables || []).reduce<Record<string, string>>(
      (acc, variable) => {
        if (!variable.formKey) return acc;
        const value = getValueByFormKey(values, variable.formKey);
        if (value) acc[variable.key] = value;
        return acc;
      },
      {}
    ),
    ...(option.packageTransportVariables || []).reduce<Record<string, string>>(
      (acc, variable) => {
        if (!variable.formKey) return acc;
        const value = getValueByFormKey(values, variable.formKey);
        if (value) acc[variable.key] = value;
        return acc;
      },
      {}
    ),
  };

  return applyUrlTemplateVariables(option.serverUrl || "", mergedValues);
};

export const hasUnresolvedUrlTemplate = (url: string): boolean =>
  /\{[^{}]+\}/.test(url);

export const findMissingRequiredField = (
  fields: Array<{
    formKey?: string;
    isRequired?: boolean;
    label?: string;
    key: string;
  }>,
  values: Record<string, string>
): { key: string } | null => {
  for (const field of fields) {
    if (!field.isRequired) continue;
    const value = getValueByFormKey(values, field.formKey);
    if (!value) {
      return {
        key:
          typeof field.label === "string" && field.label.trim()
            ? field.label
            : field.key,
      };
    }
  }
  return null;
};

export const collectPackageEnvValues = (
  option: RegistryQuickAddOption,
  values: Record<string, string>
): Record<string, string> => {
  return (option.packageEnvironmentVariables || []).reduce<
    Record<string, string>
  >((acc, envVar) => {
    const value = getValueByFormKey(values, envVar.formKey);
    if (!value) return acc;
    acc[envVar.key] = value;
    return acc;
  }, {});
};

export const isValidPort = (port: number | undefined): port is number => {
  return typeof port === "number" && Number.isInteger(port) && port >= MCP_PORT_RANGE.MIN && port <= MCP_PORT_RANGE.MAX;
};

