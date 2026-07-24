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
  const content = asString(details.content);
  const contentSuffix = content
    ? t("notifications.events.contentSuffix", { content })
    : "";

  const messageKey = resolveMessageKey(item.event_type, item.resource_type);
  if (messageKey) {
    return t(messageKey, { name, contentSuffix, content: content ?? "" });
  }

  return name;
}
