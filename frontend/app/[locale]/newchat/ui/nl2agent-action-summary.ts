// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import i18n, { type TFunction } from "i18next";

/** Resolve display-only action summaries in the current page language. */
export function formatNl2AgentActionSummary(
  subtype: string,
  t: TFunction = i18n.t.bind(i18n)
): string {
  switch (subtype) {
    case "requirement_clarification":
      return t(
        "nl2agent.requirementClarification.submittedSummary",
        "Requirements submitted"
      );
    case "suggested_resource_installation":
      return t(
        "nl2agent.resourceInstallation.submittedSummary",
        "Resource installation completed"
      );
    case "installed_resource_binding":
      return t(
        "nl2agent.resourceBinding.submittedSummary",
        "Resource selection completed"
      );
    default:
      return t(
        "nl2agent.cardAction.continuedSummary",
        "Agent creation continued"
      );
  }
}
