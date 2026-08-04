import type { AgentAutomationProposalData } from "@/types/agentAutomation";

export function parseAutomationProposal(
  content: string
): AgentAutomationProposalData | null {
  try {
    const value = JSON.parse(content) as unknown;
    if (typeof value !== "object" || value === null) return null;
    const proposal = value as AgentAutomationProposalData;
    return typeof proposal.proposal_id === "number" && proposal.task
      ? proposal
      : null;
  } catch {
    return null;
  }
}
