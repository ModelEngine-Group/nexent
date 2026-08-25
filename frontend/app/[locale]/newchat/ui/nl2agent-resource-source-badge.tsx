"use client";

import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import type { Nl2aResourceCandidate } from "../adapter/remote-chat-model-adapter";

export type ResourceAvailability = "local" | "installed" | "uninstalled";

const AVAILABILITY_BY_SOURCE: Record<
  Nl2aResourceCandidate["source"],
  ResourceAvailability
> = {
  LOCAL_TOOL: "local",
  MCP_TOOL: "installed",
  INSTALLED_SKILL: "installed",
  NEXENT_OFFICIAL_SKILL: "uninstalled",
  TENANT_SKILL_REPOSITORY: "uninstalled",
  TENANT_MCP_REPOSITORY: "uninstalled",
};

export function Nl2AgentResourceSourceBadge({
  source,
  availability: availabilityOverride,
}: {
  source: Nl2aResourceCandidate["source"];
  availability?: ResourceAvailability;
}) {
  const { t } = useTranslation("common");
  const availability = availabilityOverride || AVAILABILITY_BY_SOURCE[source];
  const isTenantRepository =
    source === "TENANT_SKILL_REPOSITORY" ||
    source === "TENANT_MCP_REPOSITORY";
  const label = {
    local: t("nl2agent.resourceSource.local", "Local"),
    installed: t("nl2agent.resourceSource.installed", "Installed"),
    uninstalled: isTenantRepository
      ? t(
          "nl2agent.resourceSource.uninstalledTenantRepository",
          "Not installed · Tenant repository"
        )
      : t(
          "nl2agent.resourceSource.uninstalledOther",
          "Not installed · Other"
        ),
  }[availability];

  return (
    <Badge variant="outline" className="rounded-md text-[10px]">
      {label}
    </Badge>
  );
}
