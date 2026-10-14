import type {
  ClarificationAnswer,
  ClarificationForm,
  ClarificationMessageData,
  ClarificationQuestion,
  HumanInteractionEvent,
  RuntimeClarificationQuestion,
} from "../types/clarification";

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const identifier = (value: unknown): value is string =>
  typeof value === "string" && /^[a-zA-Z0-9_-]{1,64}$/.test(value);
const text = (value: unknown, max: number, min = 1): value is string =>
  typeof value === "string" &&
  value.trim().length >= min &&
  value.length <= max;

export function isHumanInteractionEvent(event: {
  type: string;
}): event is HumanInteractionEvent {
  return event.type === "human_interaction";
}

/** Invalid or unsupported cards retain the ordinary final-answer fallback. */
export function parseClarification(value: unknown): ClarificationForm | null {
  try {
    const raw: unknown = typeof value === "string" ? JSON.parse(value) : value;
    if (
      !record(raw) ||
      raw.schema_version !== 1 ||
      Object.keys(raw).some(
        (key) => !["schema_version", "questions"].includes(key)
      ) ||
      !Array.isArray(raw.questions) ||
      raw.questions.length < 1 ||
      raw.questions.length > 5
    )
      return null;
    const questions: RuntimeClarificationQuestion[] = [];
    for (const item of raw.questions) {
      if (
        !record(item) ||
        !identifier(item.id) ||
        !text(item.title, 500) ||
        !["text", "single_choice", "multiple_choice"].includes(
          String(item.type)
        ) ||
        Object.keys(item).some(
          (key) =>
            ![
              "id",
              "type",
              "title",
              "required",
              "options",
              "allow_other",
              "placeholder",
            ].includes(key)
        ) ||
        (item.required !== undefined && typeof item.required !== "boolean") ||
        (item.allow_other !== undefined &&
          typeof item.allow_other !== "boolean") ||
        (item.placeholder !== undefined && !text(item.placeholder, 300, 0))
      )
        return null;
      const options = item.options ?? [];
      if (
        !Array.isArray(options) ||
        options.length > 12 ||
        options.some(
          (option) =>
            !record(option) ||
            !identifier(option.id) ||
            !text(option.label, 300) ||
            Object.keys(option).some((key) => !["id", "label"].includes(key))
        )
      )
        return null;
      if (new Set(options.map((option) => option.id)).size !== options.length)
        return null;
      if (
        item.type === "text"
          ? options.length > 0 || item.allow_other === true
          : options.length < 2
      )
        return null;
      questions.push({
        id: item.id,
        type: item.type as RuntimeClarificationQuestion["type"],
        title: item.title,
        required: item.required !== false,
        options,
        allow_other: item.allow_other === true,
        placeholder:
          typeof item.placeholder === "string" ? item.placeholder : "",
      });
    }
    if (
      new Set(questions.map((q) => q.id)).size !== questions.length ||
      new Set(questions.map((q) => q.title)).size !== questions.length
    )
      return null;
    return { schema_version: 1, questions };
  } catch {
    return null;
  }
}

export function toCardQuestions(
  questions: RuntimeClarificationQuestion[]
): ClarificationQuestion[] {
  return questions.map((question) => ({
    id: question.id,
    type: question.type,
    title: question.title,
    required: question.required,
    options: question.options,
    allowOther: question.allow_other,
    otherInputExpanded: question.allow_other,
    placeholder: question.placeholder,
  }));
}

/** Must match the SDK's deterministic fallback renderer exactly. */
export function renderQuestionText(form: ClarificationForm): string {
  return form.questions
    .flatMap((question, index) => [
      `${index + 1}. ${question.title}`,
      ...question.options.map((option) => `   - ${option.label}`),
      ...(question.allow_other ? ["   - 其他 / Other"] : []),
      ...(question.placeholder ? [`   ${question.placeholder}`] : []),
    ])
    .join("\n");
}

export function formatClarificationQuery(
  form: ClarificationForm,
  answers: ClarificationAnswer[],
  language: string
): string {
  const zh = language.startsWith("zh");
  const byId = new Map(answers.map((answer) => [answer.questionId, answer]));
  if (
    byId.size !== answers.length ||
    answers.some(
      (answer) => !form.questions.some((q) => q.id === answer.questionId)
    )
  ) {
    throw new Error(
      zh ? "回答包含无效问题" : "Answers contain an invalid question"
    );
  }
  const lines = [
    zh ? "补充上一轮问题：" : "Answers to the previous questions:",
  ];
  form.questions.forEach((question, index) => {
    const answer = byId.get(question.id);
    const value =
      answer?.value ?? (question.type === "multiple_choice" ? [] : "");
    const other = answer?.otherText?.trim() ?? "";
    const options = new Map(
      question.options.map((option) => [option.id, option.label])
    );
    const valid =
      question.type === "multiple_choice"
        ? Array.isArray(value) &&
          new Set(value).size === value.length &&
          value.every((id) => options.has(id))
        : typeof value === "string" &&
          value.length <= 8000 &&
          (question.type === "text" || !value || options.has(value));
    const hasValue = Array.isArray(value)
      ? value.length > 0
      : Boolean(value.trim());
    if (
      !valid ||
      other.length > 8000 ||
      (other && !question.allow_other) ||
      (question.required && !hasValue && !other)
    ) {
      throw new Error(
        zh
          ? `请检查回答：${question.title}`
          : `Check the answer: ${question.title}`
      );
    }
    const resolved = Array.isArray(value)
      ? value.map((id) => options.get(id)).join(zh ? "；" : "; ")
      : (options.get(value) ?? value.trim());
    lines.push(`${index + 1}. ${question.title}`);
    lines.push(
      `   ${zh ? "回答" : "Answer"}：${resolved || (zh ? "未选择" : "No selection")}${other ? `${zh ? "；其他补充：" : "; Other: "}${other}` : ""}`
    );
  });
  return lines.join("\n");
}

interface ContentPart {
  type: string;
  name?: string;
  data?: unknown;
}

export function appendClarificationPart(
  parts: ContentPart[],
  content: unknown,
  unitIndex?: number,
  completed?: boolean
): boolean {
  const form = parseClarification(content);
  if (!form) return false;
  const existing = parts.find(
    (part) =>
      part.type === "data" &&
      part.name === "clarification" &&
      (part.data as ClarificationMessageData)?.unitIndex === unitIndex
  );
  const data: ClarificationMessageData = { form, unitIndex, completed };
  if (existing) existing.data = data;
  else parts.push({ type: "data", name: "clarification", data });
  return true;
}

export function isClarificationFallback(
  parts: ContentPart[],
  content: string
): boolean {
  return parts.some(
    (part) =>
      part.type === "data" &&
      part.name === "clarification" &&
      renderQuestionText((part.data as ClarificationMessageData).form) ===
        content
  );
}
