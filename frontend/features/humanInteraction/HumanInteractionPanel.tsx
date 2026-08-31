"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  humanInteractionClient,
  type HumanRequest,
  type HumanRun,
} from "./client";

export function HumanInteractionPanel({
  conversationId,
  enabled,
  onEnabledChange,
  isRunning,
  onContinue,
}: {
  conversationId?: number;
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  isRunning: boolean;
  onContinue: (runId: string, after: number) => void;
}) {
  const { i18n } = useTranslation();
  const zh = i18n.language.startsWith("zh");
  const [available, setAvailable] = useState(false);
  const [acceptNewRuns, setAcceptNewRuns] = useState(true);
  const [run, setRun] = useState<HumanRun | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const resume = useRef<{ runId: string; after: number } | null>(null);

  useEffect(() => {
    let active = true;
    humanInteractionClient
      .capabilities()
      .then((value) => {
        if (active) {
          setAvailable(value.enabled);
          setAcceptNewRuns(value.accept_new_runs !== false);
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    setRun(null);
    setError("");
    resume.current = null;
    if (!available || !conversationId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await humanInteractionClient.conversation(conversationId);
        if (active) setRun(value);
      } catch (cause) {
        if (active)
          setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        if (active) timer = setTimeout(poll, 1500);
      }
    };
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [available, conversationId]);

  useEffect(() => {
    if (!isRunning && resume.current) {
      const pending = resume.current;
      resume.current = null;
      onContinue(pending.runId, pending.after);
    }
  }, [isRunning, run, onContinue]);

  if (!available) return null;
  const active =
    run &&
    [
      "INITIALIZING",
      "READY",
      "RUNNING",
      "WAITING_HUMAN",
      "RECOVERY_REQUIRED",
    ].includes(run.status);
  const control = async (action: "pause" | "terminate") => {
    if (!run) return;
    setBusy(true);
    setError("");
    try {
      setRun(await humanInteractionClient.control(run.run_id, action));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="mx-auto w-full max-w-4xl space-y-2 border-b px-6 py-3 text-sm"
      aria-label={zh ? "人在回路" : "Human interaction"}
    >
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={enabled}
            disabled={isRunning || !!active || (!acceptNewRuns && !enabled)}
            onChange={(event) => onEnabledChange(event.target.checked)}
          />
          {zh
            ? "人在回路（受控工具执行）"
            : "Human interaction (controlled tools)"}
        </label>
        {run && (
          <span role="status">
            {run.pause_requested
              ? zh
                ? "暂停请求已受理，等待当前调用到达安全边界"
                : "Pause accepted; waiting for a safe boundary"
              : (
                  {
                    INITIALIZING: zh ? "正在初始化" : "Initializing",
                    READY: zh ? "准备继续" : "Ready",
                    RUNNING: zh ? "正在执行" : "Running",
                    WAITING_HUMAN: zh
                      ? "等待你的回复"
                      : "Waiting for your response",
                    RECOVERY_REQUIRED: zh
                      ? "执行结果待核对，禁止自动重试"
                      : "Outcome uncertain; reconciliation required",
                    COMPLETED: zh ? "本次任务已完成" : "Run completed",
                    FAILED: zh ? "本次任务失败" : "Run failed",
                    STOPPED: zh ? "本次任务已终止" : "Run terminated",
                    EXPIRED: zh
                      ? "回复已过期，未执行待批动作"
                      : "Response expired; pending action was not executed",
                  } as Record<string, string>
                )[run.status]}
          </span>
        )}
        {active && run.status !== "RECOVERY_REQUIRED" && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy || run.pause_requested}
            onClick={() => void control("pause")}
          >
            {zh ? "暂停并提供意见" : "Pause and steer"}
          </Button>
        )}
        {active && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => void control("terminate")}
          >
            {zh ? "终止任务" : "Terminate"}
          </Button>
        )}
        {active && !isRunning && ["READY", "RUNNING"].includes(run.status) && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onContinue(run.run_id, 0)}
          >
            {zh ? "重新连接执行输出" : "Reconnect output"}
          </Button>
        )}
      </div>
      {enabled && !active && (
        <p className="text-xs text-muted-foreground">
          {zh
            ? "支持 ReAct / Planning 的反问、审批与暂停续跑；暂不支持附件、子 Agent、任意 Python 或并行执行。"
            : "ReAct / Planning supports questions, approval and pause/resume. Attachments, sub-agents, arbitrary Python and parallel execution are unavailable."}
        </p>
      )}
      {run?.requests?.map((item) => (
        <DecisionForm
          key={item.request_id}
          item={item}
          zh={zh}
          disabled={busy}
          onAccepted={() => {
            resume.current = { runId: run.run_id, after: run.event_seq };
            setRun({ ...run, status: "READY", requests: [] });
          }}
          onError={setError}
        />
      ))}
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
    </section>
  );
}

function DecisionForm({
  item,
  zh,
  disabled,
  onAccepted,
  onError,
}: {
  item: HumanRequest;
  zh: boolean;
  disabled: boolean;
  onAccepted: () => void;
  onError: (error: string) => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const previous = useRef<{ body: string; key: string } | null>(null);
  const approval = item.kind === "ACTION_APPROVAL";
  const expired = Date.parse(item.expires_at) <= Date.now();
  const submit = async (
    decision: "answer" | "approve" | "reject" | "steer"
  ) => {
    const body = JSON.stringify([decision, text]);
    if (previous.current?.body !== body)
      previous.current = { body, key: crypto.randomUUID() };
    setBusy(true);
    onError("");
    try {
      await humanInteractionClient.decide(
        item,
        decision,
        text,
        previous.current.key
      );
      onAccepted();
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };
  return (
    <fieldset
      disabled={disabled || busy || expired}
      className="space-y-2 rounded-lg border bg-card p-3"
    >
      <legend className="px-1 font-medium">{item.payload.question}</legend>
      {approval && (
        <>
          <p className="font-mono text-xs">{item.payload.tool}</p>
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded bg-muted p-2 text-xs">
            {JSON.stringify(item.payload.arguments, null, 2)}
          </pre>
          <p className="text-xs text-muted-foreground">
            {zh
              ? "批准仅执行以上冻结参数；拒绝不会执行该动作。"
              : "Approval applies only to these frozen arguments; rejection does not execute the action."}
          </p>
        </>
      )}
      {item.payload.options?.length ? (
        <select
          value={text}
          onChange={(event) => setText(event.target.value)}
          className="w-full rounded border bg-background p-2"
          aria-label={item.payload.question}
        >
          <option value="">{zh ? "请选择" : "Choose an option"}</option>
          {item.payload.options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : (
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          maxLength={8000}
          aria-label={zh ? "回复或意见" : "Response or feedback"}
          className="w-full rounded border bg-background p-2"
          rows={2}
          placeholder={
            approval
              ? zh
                ? "可选：拒绝原因或修改建议"
                : "Optional reason or requested changes"
              : zh
                ? "请输入回复，不要填写密码或密钥"
                : "Enter your response; never enter passwords or keys"
          }
        />
      )}
      <div className="flex gap-2">
        {approval ? (
          <>
            <Button size="sm" onClick={() => void submit("approve")}>
              {zh ? "批准此次操作" : "Approve once"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void submit("reject")}
            >
              {zh ? "拒绝" : "Reject"}
            </Button>
          </>
        ) : (
          <Button
            size="sm"
            disabled={!text.trim()}
            onClick={() =>
              void submit(item.kind === "USER_STEERING" ? "steer" : "answer")
            }
          >
            {zh ? "提交并继续" : "Submit and continue"}
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        {zh ? "有效期至：" : "Expires: "}
        {new Date(item.expires_at).toLocaleString()}
      </p>
    </fieldset>
  );
}
