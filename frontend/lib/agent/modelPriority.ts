import { arrayMove } from "@dnd-kit/sortable";

export type ModelPriorityOption = {
  value: number;
  displayName: string;
};

export function reorderModelIds(
  modelIds: number[],
  activeId: number,
  overId: number
): number[] {
  const activeIndex = modelIds.indexOf(activeId);
  const overIndex = modelIds.indexOf(overId);

  if (activeIndex === -1 || overIndex === -1 || activeIndex === overIndex) {
    return modelIds;
  }

  return arrayMove(modelIds, activeIndex, overIndex);
}

export function resolveModelSelection(
  modelIds: number[],
  modelOptions: ModelPriorityOption[]
) {
  const modelsById = new Map(
    modelOptions.map((option) => [option.value, option])
  );
  const modelNames = modelIds.map(
    (id) => modelsById.get(id)?.displayName ?? ""
  );

  return {
    model_ids: modelIds,
    model: modelNames[0] ?? "",
    model_names: modelNames,
  };
}
