// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import AutomationProposalMessage from "@/features/agentAutomation/components/AutomationProposalMessage";
import { publishAutomationConfirmation } from "@/features/agentAutomation/confirmationEvent";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { id?: number }) =>
      options?.id ? `${key} ${options.id}` : key,
    i18n: { language: "en" },
  }),
}));
vi.mock(
  "@/features/agentAutomation/components/AutomationProposalEditor",
  () => ({
    default: () => null,
  })
);

it("updates only the matching card and refreshes the list for a valid task receipt", () => {
  const proposal = { proposal_id: 13, executable: true };
  const refresh = vi.fn();
  window.addEventListener("automationListUpdated", refresh);
  try {
    const { rerender } = render(
      <AutomationProposalMessage proposal={proposal} />
    );
    const createButton = () =>
      screen.queryByRole("button", { name: "agentAutomation.proposal.create" });
    expect(createButton()).toBeInTheDocument();

    act(() => publishAutomationConfirmation('{"proposal_id":13,"task_id":0}'));
    expect(createButton()).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();

    act(() => publishAutomationConfirmation('{"proposal_id":14,"task_id":21}'));
    expect(createButton()).toBeInTheDocument();

    act(() => publishAutomationConfirmation('{"proposal_id":13,"task_id":27}'));
    expect(
      screen.getByText("agentAutomation.proposal.confirmed 27")
    ).toBeInTheDocument();
    expect(createButton()).not.toBeInTheDocument();
    expect(refresh).toHaveBeenCalledTimes(2);

    rerender(<AutomationProposalMessage proposal={{ ...proposal }} />);
    expect(
      screen.getByText("agentAutomation.proposal.confirmed 27")
    ).toBeInTheDocument();
  } finally {
    window.removeEventListener("automationListUpdated", refresh);
  }
});
