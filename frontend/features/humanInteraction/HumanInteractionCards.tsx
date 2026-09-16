"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ShieldAlert, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  ClarificationCard,
  InteractionCardShell,
  type ClarificationAnswer,
} from "@/components/interaction/clarification-card";
import { Button } from "@/components/ui/button";
import type { HumanRequest } from "./client";
import { toCardQuestions, toHumanAnswers } from "./clarification";
import type { HumanInteractionController } from "./useHumanInteractionController";

export function HumanInteractionCards({
  controller,
}: {
  controller: HumanInteractionController;
}) {
  const anchor = useRef<HTMLDivElement>(null);
  const requestId = controller.run?.requests?.[0]?.request_id;

  useEffect(() => {
    if (requestId) {
      anchor.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [requestId]);

  if (!controller.run?.requests?.length) return null;

  return (
    <div ref={anchor} className="w-full" aria-live="polite">
      {controller.run.requests.map((item) => (
        <HumanInteractionRequestCard
          key={item.request_id}
          item={item}
          disabled={controller.busy}
          onDecide={controller.decide}
        />
      ))}
    </div>
  );
}

function HumanInteractionRequestCard({
  item,
  disabled,
  onDecide,
}: {
  item: HumanRequest;
  disabled: boolean;
  onDecide: HumanInteractionController["decide"];
}) {
  const { i18n } = useTranslation();
  const zh = i18n.language.startsWith("zh");
  const expired = Date.parse(item.expires_at) <= Date.now();

  if (item.kind === "ACTION_APPROVAL") {
    return (
      <ActionApprovalCard
        item={item}
        zh={zh}
        disabled={disabled || expired}
        onDecide={onDecide}
      />
    );
  }

  const submit = async (answers: ClarificationAnswer[]) => {
    if (item.kind === "CLARIFICATION" && item.payload.questions) {
      await onDecide(item, "answer", toHumanAnswers(answers));
      return;
    }
    const answer = answers[0];
    const value =
      answer.otherText ??
      (Array.isArray(answer.value) ? answer.value.join(", ") : answer.value);
    await onDecide(
      item,
      item.kind === "USER_STEERING" ? "steer" : "answer",
      value
    );
  };

  return (
    <ClarificationCard
      dataSlot="human-interaction-clarification"
      title={
        item.kind === "USER_STEERING"
          ? zh
            ? "调整执行方向"
            : "Adjust execution"
          : zh
            ? "澄清需求"
            : "More information needed"
      }
      description={
        item.kind === "USER_STEERING"
          ? zh
            ? "你的意见会加入当前上下文，智能体将从挂起位置继续。"
            : "Your feedback is added to the current context before the Agent resumes."
          : zh
            ? "请补充当前智能体继续执行所需的信息。"
            : "Provide the information this Agent needs to continue."
      }
      questions={
        item.payload.questions
          ? toCardQuestions(item.payload.questions)
          : [
              {
                id: item.request_id,
                type: item.payload.options?.length ? "single_choice" : "text",
                title:
                  item.payload.question ||
                  (zh ? "请提供更多信息" : "Please provide more information"),
                required: true,
                options: item.payload.options?.map((option) => ({
                  id: option,
                  label: option,
                })),
                allowOther: item.payload.allow_other === true,
                otherInputExpanded: item.payload.allow_other === true,
                placeholder: zh
                  ? "请输入回复，请勿填写密码或密钥"
                  : "Enter your response; never enter passwords or keys",
              },
            ]
      }
      disabled={disabled || expired}
      otherLabel={zh ? "其他" : "Other"}
      submitLabel={zh ? "提交并继续" : "Submit and continue"}
      submittedLabel={zh ? "已提交" : "Submitted"}
      footerHint={
        expired
          ? zh
            ? "该请求已过期"
            : "This request has expired"
          : `${zh ? "有效期至" : "Expires"}: ${new Date(
              item.expires_at
            ).toLocaleString()}`
      }
      onSubmit={submit}
    />
  );
}

function ActionApprovalCard({
  item,
  zh,
  disabled,
  onDecide,
}: {
  item: HumanRequest;
  zh: boolean;
  disabled: boolean;
  onDecide: HumanInteractionController["decide"];
}) {
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (decision: "approve" | "reject") => {
    setBusy(true);
    setError("");
    try {
      await onDecide(item, decision, feedback);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <InteractionCardShell
      dataSlot="human-interaction-approval"
      icon={<ShieldAlert className="size-4 text-amber-600" />}
      title={zh ? "操作需要审核" : "Action approval required"}
      description={
        zh
          ? "核对冻结的工具与参数后，决定是否允许本次执行。"
          : "Review the frozen tool and arguments before allowing this execution."
      }
      footer={
        <div className="space-y-2">
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground">
              {zh ? "有效期至" : "Expires"}:{" "}
              {new Date(item.expires_at).toLocaleString()}
            </span>
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                disabled={disabled || busy}
                onClick={() => void submit("approve")}
              >
                <Check />
                {zh ? "批准此次操作" : "Approve once"}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={disabled || busy}
                onClick={() => void submit("reject")}
              >
                <X />
                {zh ? "拒绝" : "Reject"}
              </Button>
            </div>
          </div>
        </div>
      }
    >
      <div className="space-y-4 p-4">
        <div>
          <p className="text-sm font-medium text-foreground">
            {item.payload.question ||
              (zh ? "是否允许执行此操作？" : "Allow this action?")}
          </p>
          <p className="mt-2 font-mono text-xs text-muted-foreground">
            {item.payload.tool}
          </p>
          <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted p-3 text-xs">
            {JSON.stringify(item.payload.arguments, null, 2)}
          </pre>
        </div>
        <label className="block text-xs text-muted-foreground">
          <span>
            {zh
              ? "意见或拒绝原因（可选）"
              : "Feedback or rejection reason (optional)"}
          </span>
          <textarea
            value={feedback}
            onChange={(event) => setFeedback(event.target.value)}
            rows={2}
            maxLength={8000}
            disabled={disabled || busy}
            className="mt-1 w-full resize-y rounded-md border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary disabled:cursor-not-allowed"
          />
        </label>
      </div>
    </InteractionCardShell>
  );
}
