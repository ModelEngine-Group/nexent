/**
 * Deep-link helpers for in-app notifications.
 */

import type { NotificationDetails, NotificationItem } from "@/types/notification";
import {
  NOTIFICATION_EVENT_TYPES,
  NOTIFICATION_RESOURCE_TYPES,
} from "@/types/notification";

function asPositiveInt(value: unknown): number | null {
  if (typeof value === "number" && Number.isInteger(value) && value > 0) {
    return value;
  }
  if (typeof value === "string" && /^\d+$/.test(value)) {
    const parsed = Number.parseInt(value, 10);
    return parsed > 0 ? parsed : null;
  }
  return null;
}

export function extractReviewDeepLinkIds(
  details: NotificationDetails | Record<string, unknown> | null | undefined
): { agentRepositoryId: number; agentId: number } | null {
  if (!details) {
    return null;
  }
  const agentRepositoryId = asPositiveInt(details.agent_repository_id);
  const agentId = asPositiveInt(details.agent_id);
  if (agentRepositoryId == null || agentId == null) {
    return null;
  }
  return { agentRepositoryId, agentId };
}

export function isAgentRepositoryReviewResultNotification(
  item: Pick<NotificationItem, "event_type" | "resource_type" | "details">
): boolean {
  if (item.resource_type !== NOTIFICATION_RESOURCE_TYPES.AGENT_REPOSITORY) {
    return false;
  }

  if (item.event_type === NOTIFICATION_EVENT_TYPES.REPOSITORY_REVIEW_PENDING) {
    return true;
  }

  const isReviewResultEvent =
    item.event_type === NOTIFICATION_EVENT_TYPES.REPOSITORY_REVIEW_APPROVED ||
    item.event_type === NOTIFICATION_EVENT_TYPES.REPOSITORY_REVIEW_REJECTED;
  if (!isReviewResultEvent) {
    return false;
  }
  return extractReviewDeepLinkIds(item.details) != null;
}

export function buildAgentRepositoryReviewDeepLink(
  locale: string,
  details: NotificationDetails | Record<string, unknown> | null | undefined,
  eventType?: string
): string | null {
  if (eventType === NOTIFICATION_EVENT_TYPES.REPOSITORY_REVIEW_PENDING) {
    return `/${locale}/agent-space?tab=review`;
  }

  const ids = extractReviewDeepLinkIds(details);
  if (!ids) {
    return null;
  }
  const params = new URLSearchParams({
    tab: "mine",
    agent_repository_id: String(ids.agentRepositoryId),
    agent_id: String(ids.agentId),
  });
  return `/${locale}/agent-space?${params.toString()}`;
}

export function parseReviewDeepLinkParams(searchParams: URLSearchParams): {
  agentRepositoryId: number;
  agentId: number;
} | null {
  const agentRepositoryId = asPositiveInt(searchParams.get("agent_repository_id"));
  const agentId = asPositiveInt(searchParams.get("agent_id"));
  if (agentRepositoryId == null || agentId == null) {
    return null;
  }
  return { agentRepositoryId, agentId };
}
