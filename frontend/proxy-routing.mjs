const RUNTIME_API_PATH_PREFIXES = [
  "/api/agent/run",
  "/api/agent/nl2agent/run",
  "/api/agent-share/",
  "/api/skills/nl2skill/run",
  "/api/agent/stop",
  "/api/agent/automations",
  "/api/conversation/",
  "/api/share/",
  "/api/file/storage",
  "/api/file/preprocess",
];

export function isRuntimeApiPath(pathname) {
  return RUNTIME_API_PATH_PREFIXES.some((prefix) =>
    pathname.startsWith(prefix)
  );
}
