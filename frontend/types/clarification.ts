export type ClarificationQuestionType =
  | "single_choice"
  | "multiple_choice"
  | "text";

export interface ClarificationOption {
  id: string;
  label: string;
}

export interface ClarificationQuestion {
  id: string;
  type: ClarificationQuestionType;
  title: string;
  required?: boolean;
  options?: ClarificationOption[];
  allowOther?: boolean;
  otherInputExpanded?: boolean;
  placeholder?: string;
}

export interface ClarificationAnswer {
  questionId: string;
  value: string | string[];
  otherText: string | null;
}

export interface RuntimeClarificationQuestion {
  id: string;
  type: ClarificationQuestionType;
  title: string;
  required: boolean;
  options: ClarificationOption[];
  allow_other: boolean;
  placeholder: string;
}

export interface ClarificationForm {
  schema_version: 1;
  questions: RuntimeClarificationQuestion[];
}

export interface HumanInteractionEvent {
  type: "human_interaction";
  // Validate the form before rendering content received over SSE.
  content: unknown;
  unit_index?: number;
}

export interface ClarificationMessageData {
  form: ClarificationForm;
  unitIndex?: number;
  completed?: boolean;
}
