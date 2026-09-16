import type {
  ClarificationAnswer,
  ClarificationQuestion,
} from "@/components/interaction/clarification-card";

export interface HumanClarificationQuestion {
  id: string;
  type: "text" | "single_choice" | "multiple_choice";
  title: string;
  required: boolean;
  options?: { id: string; label: string }[];
  allow_other?: boolean;
  placeholder?: string;
}

export interface HumanClarificationAnswer {
  question_id: string;
  value: string | string[];
  other_text: string | null;
}

export function toCardQuestions(
  questions: HumanClarificationQuestion[]
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

export function toHumanAnswers(
  answers: ClarificationAnswer[]
): HumanClarificationAnswer[] {
  return answers.map((answer) => ({
    question_id: answer.questionId,
    value: answer.value,
    other_text: answer.otherText,
  }));
}
