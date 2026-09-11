export type Nl2AgentResourcePhase =
  "clarifying" | "installing" | "resolving_gap" | "binding";

const INSTALLED_SOURCES = new Set([
  "LOCAL_TOOL",
  "MCP_TOOL",
  "INSTALLED_SKILL",
]);
const INSTALLABLE_SOURCES = new Set([
  "NEXENT_OFFICIAL_SKILL",
  "TENANT_SKILL_REPOSITORY",
  "TENANT_MCP_REPOSITORY",
]);
const FORBIDDEN_RESOURCE_KEYS = new Set([
  "config",
  "installation_options",
  "url",
  "server_url",
  "authorization_token",
  "custom_headers",
  "container_config",
  "port",
]);

type ResourceCard = Record<string, unknown>;

function isSafeResource(
  resource: unknown,
  allowedSources: Set<string>
): boolean {
  if (!resource || typeof resource !== "object" || Array.isArray(resource))
    return false;
  const candidate = resource as ResourceCard;
  if (
    typeof candidate.candidate_ref !== "string" ||
    typeof candidate.source !== "string" ||
    !allowedSources.has(candidate.source) ||
    typeof candidate.name !== "string" ||
    typeof candidate.description !== "string" ||
    !Array.isArray(candidate.requirement_ids)
  ) {
    return false;
  }
  return !Object.keys(candidate).some((key) =>
    FORBIDDEN_RESOURCE_KEYS.has(key)
  );
}

export function isSafeNl2AgentResourceCard(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const card = value as ResourceCard;
  if (card.schema_version !== 2 || !Array.isArray(card.resources)) return false;
  if (card.subtype === "suggested_resource_installation") {
    return card.resources.every((resource) =>
      isSafeResource(resource, INSTALLABLE_SOURCES)
    );
  }
  if (card.subtype === "installed_resource_binding") {
    return card.resources.every((resource) =>
      isSafeResource(resource, INSTALLED_SOURCES)
    );
  }
  return false;
}

export function getNl2AgentCardPhase(
  subtype: string
): Nl2AgentResourcePhase | null {
  switch (subtype) {
    case "requirement_clarification":
      return "clarifying";
    case "suggested_resource_installation":
      return "installing";
    case "resource_gap_resolution":
      return "resolving_gap";
    case "installed_resource_binding":
      return "binding";
    default:
      return null;
  }
}
