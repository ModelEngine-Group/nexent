import type { ModelParameterValue } from "@/types/modelParameterSettings";

/** UI levels only; backend/provider conversion belongs to a future adapter. */
export const DEFAULT_MODEL_PARAMETER_VALUES: ModelParameterValue = {
  temperatureLevel: 50,
  topPLevel: 90,
};
