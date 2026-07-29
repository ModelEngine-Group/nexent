const configuredBasePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "/";

function normalizeBasePath(value) {
  const trimmed = value.trim();

  if (trimmed === "" || trimmed === "/") {
    return "";
  }

  if (!trimmed.startsWith("/") || trimmed.endsWith("/")) {
    throw new Error("basePath must be '/' or start with '/' without a trailing slash");
  }

  return trimmed;
}

export const BASE_PATH = normalizeBasePath(configuredBasePath);
