// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export const AUTOMATION_CONFIRMED_EVENT = "automationConfirmed";
export const AUTOMATION_LIST_UPDATED_EVENT = "automationListUpdated";

export interface AutomationConfirmation {
  proposal_id: number;
  task_id: number;
}

export function publishAutomationConfirmation(content: string): void {
  let receipt: AutomationConfirmation;
  try {
    receipt = JSON.parse(content) as AutomationConfirmation;
  } catch {
    return;
  }
  if (
    !receipt ||
    !Number.isSafeInteger(receipt.proposal_id) ||
    receipt.proposal_id <= 0 ||
    !Number.isSafeInteger(receipt.task_id) ||
    receipt.task_id <= 0
  ) {
    return;
  }

  window.dispatchEvent(
    new CustomEvent(AUTOMATION_CONFIRMED_EVENT, { detail: receipt })
  );
  window.dispatchEvent(new Event(AUTOMATION_LIST_UPDATED_EVENT));
}
