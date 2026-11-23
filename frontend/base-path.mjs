const configuredBasePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "/";

function normalizeBasePath(value) {
  const trimmed = value.trim();

  if (trimmed === "" || trimmed === "/") {
    return "";
  }

  if (!trimmed.startsWith("/") || trimmed.endsWith("/")) {
    throw new Error(
      "basePath must be '/' or start with '/' without a trailing slash"
    );
  }

  return trimmed;
}

export const BASE_PATH = normalizeBasePath(configuredBasePath);

function trimTrailingSlashes(value) {
  return value.trim().replace(/\/+$/, "");
}

export function buildPublicFrontendConfig(environment) {
  const config = {
    shareBaseUrl:
      environment.SHARE_BASE_URL ||
      environment.NEXT_PUBLIC_SHARE_BASE_URL ||
      "",
  };
  const northboundBaseUrl = environment.NORTHBOUND_EXTERNAL_URL;
  if (northboundBaseUrl?.trim()) {
    config.northboundBaseUrl = trimTrailingSlashes(northboundBaseUrl);
  }
  return config;
}
