/** Validate declared Skill fields without exposing configuration values in errors. */
export function validateSkillConfig(
  schemas: readonly unknown[],
  values: Record<string, unknown>
): string[] {
  const errors: string[] = [];
  for (const raw of schemas) {
    if (!raw || typeof raw !== "object") continue;
    const schema = raw as {
      name?: string;
      type?: string;
      required?: boolean;
      default?: unknown;
      enum?: unknown[];
      minimum?: number;
      maximum?: number;
    };
    if (!schema.name) continue;
    const value = values[schema.name] ?? schema.default;
    if (value === undefined || value === null || value === "") {
      if (schema.required) errors.push(schema.name);
      continue;
    }
    const valid =
      schema.type === "integer"
        ? typeof value === "number" && Number.isInteger(value)
        : schema.type === "number"
          ? typeof value === "number" && Number.isFinite(value)
          : schema.type === "array"
            ? Array.isArray(value)
            : schema.type === "object"
              ? typeof value === "object" && !Array.isArray(value)
              : ["string", "boolean"].includes(schema.type ?? "")
                ? typeof value === schema.type
                : true;
    if (
      !valid ||
      (schema.enum && !schema.enum.includes(value)) ||
      (typeof value === "number" &&
        ((schema.minimum !== undefined && value < schema.minimum) ||
          (schema.maximum !== undefined && value > schema.maximum)))
    )
      errors.push(schema.name);
  }
  return errors;
}
