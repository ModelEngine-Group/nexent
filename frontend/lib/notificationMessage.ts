// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/**
 * Format in-app notification messages from event_type + details via i18n.
 */

import type { TFunction } from "i18next";

import type { NotificationItem } from "@/types/notification";
import { NOTIFICATION_RESOURCE_TYPES } from "@/types/notification";

const AGENT_EVENT_MESSAGE_KEYS: Record<string, string> = {
  repository_review_approved: "notifications.events.repository_review_approved",
  repository_review_rejected: "notifications.events.repository_review_rejected",
  repository_review_pending: "notifications.events.repository_review_pending",
};

const SKILL_EVENT_MESSAGE_KEYS: Record<string, string> = {
  repository_review_approved:
    "notifications.events.skill_repository_review_approved",
  repository_review_rejected:
    "notifications.events.skill_repository_review_rejected",
  repository_review_pending:
    "notifications.events.skill_repository_review_pending",
};

const MCP_EVENT_MESSAGE_KEYS: Record<string, string> = {
  repository_review_approved:
    "notifications.events.mcp_repository_review_approved",
  repository_review_rejected:
    "notifications.events.mcp_repository_review_rejected",
  repository_review_pending:
    "notifications.events.mcp_repository_review_pending",
};

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function resolveMessageKey(
  eventType: string,
  resourceType: string | undefined
): string | undefined {
  if (resourceType === NOTIFICATION_RESOURCE_TYPES.SKILL_REPOSITORY) {
    return SKILL_EVENT_MESSAGE_KEYS[eventType];
  }
  if (resourceType === NOTIFICATION_RESOURCE_TYPES.MCP_REPOSITORY) {
    return MCP_EVENT_MESSAGE_KEYS[eventType];
  }
  return AGENT_EVENT_MESSAGE_KEYS[eventType];
}

/**
 * Resolve a localized notification message from event_type and details.
 */
export function formatNotificationMessage(
  item: Pick<NotificationItem, "event_type" | "details" | "resource_type">,
  t: TFunction
): string {
  const details = item.details ?? {};
  const name = asString(details.name) ?? "";
  const content =
    asString(details.content) ?? t("notifications.events.emptyContent");

  const resourceType =
    item.resource_type === NOTIFICATION_RESOURCE_TYPES.RESOURCE_REVIEW
      ? (
          {
            agent: "agent_repository",
            skill: "skill_repository",
            mcp: "mcp_repository",
          } as Record<string, string>
        )[asString(details.resource_type) || ""]
      : item.resource_type;
  const messageKey = resolveMessageKey(item.event_type, resourceType);
  if (messageKey) {
    return t(messageKey, { name, content });
  }

  return name;
}
