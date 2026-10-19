// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

interface RelationClient {
  addRelation: (
    agentId: number,
    externalId: number
  ) => Promise<{ success: boolean }>;
  removeRelation: (
    agentId: number,
    externalId: number
  ) => Promise<{ success: boolean }>;
}

/** Return confirmed remote state, including partial success, for safe retries. */
export async function synchronizeExternalAgentRelations(
  agentId: number,
  currentIds: readonly number[],
  targetIds: readonly number[],
  client: RelationClient
) {
  const current = new Set(currentIds);
  const target = new Set(targetIds);
  const operations = [
    ...[...target]
      .filter((id) => !current.has(id))
      .map((id) => ({ id, adding: true })),
    ...[...current]
      .filter((id) => !target.has(id))
      .map((id) => ({ id, adding: false })),
  ];
  const results = await Promise.allSettled(
    operations.map(async ({ id, adding }) =>
      adding
        ? client.addRelation(agentId, id)
        : client.removeRelation(agentId, id)
    )
  );
  let failed = 0;
  results.forEach((result, index) => {
    if (result.status !== "fulfilled" || !result.value.success) {
      failed += 1;
      return;
    }
    const { id, adding } = operations[index];
    if (adding) current.add(id);
    else current.delete(id);
  });
  return {
    synchronizedIds: [...current],
    succeeded: results.length - failed,
    failed,
  };
}
