import AgentEvaluateClient from "./internal/AgentEvaluateClient";

interface AgentEvaluatePageProps {
  params: Promise<{ agentId: string }>;
}

export default async function AgentEvaluatePage({ params }: AgentEvaluatePageProps) {
  const { agentId } = await params;
  const parsedAgentId = Number(agentId);

  return <AgentEvaluateClient agentId={parsedAgentId} />;
}