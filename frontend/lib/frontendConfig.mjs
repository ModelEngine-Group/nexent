function trimTrailingSlashes(value) {
  return value.trim().replace(/\/+$/, "");
}

export function buildPublicFrontendConfig(environment) {
  const config = {
    shareBaseUrl: environment.SHARE_BASE_URL || environment.NEXT_PUBLIC_SHARE_BASE_URL || "",
  };
  const northboundBaseUrl = environment.NORTHBOUND_EXTERNAL_URL;
  if (northboundBaseUrl?.trim()) {
    config.northboundBaseUrl = trimTrailingSlashes(northboundBaseUrl);
  }
  return config;
}
