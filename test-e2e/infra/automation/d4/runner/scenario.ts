import type { JourneyContext } from "./journey";

type Action = () => Promise<unknown>;
export type FixedScenario = {
  preconditions: Action[];
  steps: Action[];
  assertions: Action[];
};

export async function executeFixedScenario(context: JourneyContext, scenario: FixedScenario): Promise<void> {
  const { contract } = context;
  // Validate the complete V5 shape before the first precondition can mutate
  // product or browser state. A contract/code drift is an authoring error,
  // not a partially executed Journey.
  for (const kind of ["preconditions", "steps", "assertions"] as const) {
    const expected = contract.expectedIds(kind);
    const actions = scenario[kind];
    if (actions.length !== expected.length) {
      throw new Error(`${contract.caseId}: fixed ${kind} implementation has ${actions.length} actions but V5 requires ${expected.length}`);
    }
  }
  for (const kind of ["preconditions", "steps", "assertions"] as const) {
    const expected = contract.expectedIds(kind);
    const actions = scenario[kind];
    for (let index = 0; index < expected.length; index += 1) {
      await contract[kind === "preconditions" ? "precondition" : kind === "steps" ? "step" : "assertion"](
        expected[index],
        actions[index],
      );
    }
  }
}
