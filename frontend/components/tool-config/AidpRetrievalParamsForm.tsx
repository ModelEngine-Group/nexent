// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { createPortal } from "react-dom";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  aidpChannels,
  aidpDefaults,
  aidpErrors,
  aidpMethods,
  resolveAidpConfig,
} from "@/lib/aidpRetrievalConfig";
import styles from "./AidpRetrievalParamsForm.module.css";

const ENHANCEMENT_KEYS = [
  "rewrite_enable",
  "query_expansion_enable",
  "related_search_enable",
  "multi_modal",
] as const;

const CANDIDATE_KEYS = {
  vector_candidates: "vector_search",
  full_text_candidates: "full_text_search",
} as const;

const THRESHOLD_KEYS = {
  vector_score_threshold: "vector_search",
  full_text_score_threshold: "full_text_search",
  graph_score_threshold: "graph_search",
} as const;

type Scope = "conversation" | "agent" | "tool";

/** Structured, sectioned help popover matching the approved prototype. */
function HelpTip({ helpKey, label }: { helpKey: string; label: string }) {
  const { t } = useTranslation("common");
  const tooltipId = useId();
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const [mounted, setMounted] = useState(false);
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [position, setPosition] = useState<{
    left: number;
    top: number;
  } | null>(null);

  useEffect(() => setMounted(true), []);

  useLayoutEffect(() => {
    if (!open || !buttonRef.current || !popoverRef.current) return;
    const anchor = buttonRef.current.getBoundingClientRect();
    const popover = popoverRef.current.getBoundingClientRect();
    const width = popover.width || Math.min(320, window.innerWidth - 24);
    const height = popover.height || 0;
    const left = Math.max(
      12,
      Math.min(anchor.left - 16, window.innerWidth - width - 12)
    );
    let top = anchor.top - height - 8;
    if (top < 8) top = anchor.bottom + 8;
    top = Math.max(8, Math.min(top, window.innerHeight - height - 8));
    setPosition({ left, top });
  }, [open, helpKey]);

  useEffect(() => {
    if (!open) return;
    const close = () => {
      setPinned(false);
      setOpen(false);
      setPosition(null);
    };
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        buttonRef.current?.contains(target) ||
        popoverRef.current?.contains(target)
      )
        return;
      close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  const sections = t(`aidpRetrieval.help.${helpKey}`)
    .split("\n\n")
    .map((block) => {
      const [heading, ...paragraphs] = block.split("\n");
      return { heading, paragraphs };
    });

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className={styles.helpButton}
        aria-label={t("aidpRetrieval.helpLabel", { label })}
        aria-describedby={open ? tooltipId : undefined}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => {
          if (!pinned) {
            setOpen(false);
            setPosition(null);
          }
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          if (!pinned) {
            setOpen(false);
            setPosition(null);
          }
        }}
        onClick={() => {
          if (open && pinned) {
            setPinned(false);
            setOpen(false);
            setPosition(null);
          } else {
            setPinned(true);
            setOpen(true);
          }
        }}
      >
        ?
      </button>
      {mounted && open
        ? createPortal(
            <div
              id={tooltipId}
              ref={popoverRef}
              role="tooltip"
              className={styles.helpPopover}
              style={{
                left: position?.left ?? 0,
                top: position?.top ?? 0,
                visibility: position ? "visible" : "hidden",
              }}
              onMouseEnter={() => setOpen(true)}
              onMouseLeave={() => {
                if (!pinned) {
                  setOpen(false);
                  setPosition(null);
                }
              }}
            >
              {sections.map((section, index) => (
                <div key={index} className={styles.helpPart}>
                  <div className={styles.helpHeading}>{section.heading}</div>
                  {section.paragraphs.map((paragraph, paragraphIndex) => (
                    <p key={paragraphIndex} className={styles.helpBody}>
                      {paragraph}
                    </p>
                  ))}
                </div>
              ))}
            </div>,
            document.body
          )
        : null}
    </>
  );
}

function FieldHeading({ label, helpKey }: { label: string; helpKey: string }) {
  return (
    <div className={styles.heading}>
      <label>{label}</label>
      <HelpTip helpKey={helpKey} label={label} />
    </div>
  );
}

function NumberControl({
  label,
  helpKey,
  value,
  min,
  max,
  step = 1,
  disabled,
  invalid,
  onChange,
  note,
}: {
  label: string;
  helpKey: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  disabled?: boolean;
  invalid?: boolean;
  onChange: (value: number) => void;
  note?: ReactNode;
}) {
  return (
    <div className={styles.field}>
      <FieldHeading label={label} helpKey={helpKey} />
      <input
        type="number"
        aria-label={label}
        className={styles.control}
        min={min}
        max={max}
        step={step}
        value={Number.isFinite(value) ? value : ""}
        disabled={disabled}
        aria-invalid={invalid || undefined}
        onChange={(event) =>
          onChange(
            event.target.value === "" ? Number.NaN : Number(event.target.value)
          )
        }
      />
      {note}
    </div>
  );
}

function SwitchControl({
  label,
  helpKey,
  checked,
  disabled,
  stateText,
  onChange,
  note,
}: {
  label: string;
  helpKey: string;
  checked: boolean;
  disabled?: boolean;
  stateText: string;
  onChange: (checked: boolean) => void;
  note?: ReactNode;
}) {
  return (
    <div className={styles.field}>
      <FieldHeading label={label} helpKey={helpKey} />
      <div className={styles.switchRow}>
        <input
          type="checkbox"
          role="switch"
          aria-label={label}
          aria-checked={checked}
          className={styles.switch}
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span className={styles.switchState}>{stateText}</span>
      </div>
      {note}
    </div>
  );
}

function Section({
  title,
  summary,
  open,
  onToggle,
  className,
  children,
}: {
  title: string;
  summary: string;
  open: boolean;
  onToggle: () => void;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={[styles.section, className].filter(Boolean).join(" ")}>
      <button
        type="button"
        className={styles.sectionSummary}
        aria-expanded={open}
        onClick={onToggle}
      >
        <span
          className={[styles.sectionArrow, open ? styles.sectionArrowOpen : ""]
            .filter(Boolean)
            .join(" ")}
        >
          <ChevronRight size={14} />
        </span>
        <span>{title}</span>
        <span className={styles.sectionState}>{summary}</span>
      </button>
      {open ? <div className={styles.sectionContent}>{children}</div> : null}
    </section>
  );
}

export function AidpRetrievalParamsForm({
  values,
  onChange,
  disabled = false,
  scope = "agent",
}: {
  values: Record<string, unknown>;
  onChange: (patch: Record<string, unknown>) => void;
  disabled?: boolean;
  scope?: Scope;
}) {
  const { t, i18n } = useTranslation("common");
  const c = resolveAidpConfig(values);
  const methods = aidpMethods(c.search_method);
  const channels = methods.filter((method) => aidpChannels.includes(method));
  const mixed =
    c.search_method === "hybrid_search" ||
    (typeof c.search_method === "string" && c.search_method.includes("|"));
  const vector = channels.includes("vector_search");
  const text = channels.includes("full_text_search");
  const graph = channels.includes("graph_search");
  const errors = aidpErrors(values);
  if (mixed && channels.length < 2) errors.search_method = "combination";

  const [combinationOpen, setCombinationOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [enhancementOpen, setEnhancementOpen] = useState(false);

  const hKey =
    vector && text
      ? "hybrid_top_k"
      : vector
        ? "vector_top_k"
        : "full_text_top_k";
  const showHybridTopK =
    (vector || text) &&
    ((graph && !c.graph_reranking_enable) || Number(c.hybrid_top_k) > 0);
  const enhancementCount = ENHANCEMENT_KEYS.filter((key) =>
    Boolean(c[key])
  ).length;

  const fieldLabel = (key: string): string => {
    if (key === "search_method") return t("aidpRetrieval.fields.search_method");
    if (key in CANDIDATE_KEYS) {
      const channel = CANDIDATE_KEYS[key as keyof typeof CANDIDATE_KEYS];
      return `${t(`aidpRetrieval.groups.${channel}`)} ${t("aidpRetrieval.fields.initialCandidates")}`;
    }
    if (key in THRESHOLD_KEYS) {
      const channel = THRESHOLD_KEYS[key as keyof typeof THRESHOLD_KEYS];
      return `${t(`aidpRetrieval.groups.${channel}`)} ${t("aidpRetrieval.fields.channelScoreThreshold")}`;
    }
    if (key === "hybrid_top_k") return t(`aidpRetrieval.fields.${hKey}`);
    return t(`aidpRetrieval.fields.${key}`);
  };

  const separator = i18n.language?.startsWith("zh") ? "：" : ": ";
  const errorMessages = Object.entries(errors).map(
    ([key, code]) =>
      `${fieldLabel(key)}${separator}${t(`aidpRetrieval.errors.${code}`)}`
  );

  const combinationSummary = channels.length
    ? channels
        .map((channel) => t(`aidpRetrieval.channelShort.${channel}`))
        .join(" + ")
    : t("aidpRetrieval.combinationEmpty");

  const detailsSummary = graph
    ? t(
        `aidpRetrieval.graphRerankSummary.${
          c.graph_reranking_enable ? "on" : "off"
        }`
      )
    : t("aidpRetrieval.graphRerankSummary.none");

  const switchState = (checked: boolean, locked = false) =>
    locked
      ? t("aidpRetrieval.switch.locked")
      : checked
        ? t("aidpRetrieval.switch.on")
        : t("aidpRetrieval.switch.off");

  const candidateNote = (key: "vector_candidates" | "full_text_candidates") => {
    const following = values[key] == null;
    return (
      <div className={styles.followRow}>
        {following ? (
          t("aidpRetrieval.followHint")
        ) : (
          <>
            {t("aidpRetrieval.fixedHint")}
            <button
              type="button"
              className={styles.followLink}
              disabled={disabled}
              onClick={() => onChange({ [key]: null })}
            >
              {t("aidpRetrieval.resumeFollow")}
            </button>
          </>
        )}
      </div>
    );
  };

  const candidateField = (
    key: "vector_candidates" | "full_text_candidates"
  ) => (
    <NumberControl
      key={key}
      label={t("aidpRetrieval.fields.initialCandidates")}
      helpKey={key}
      value={Number(c[key])}
      min={1}
      max={500}
      disabled={disabled}
      invalid={Boolean(errors[key])}
      onChange={(value) => onChange({ [key]: value })}
      note={candidateNote(key)}
    />
  );

  const thresholdField = (
    key:
      | "vector_score_threshold"
      | "full_text_score_threshold"
      | "graph_score_threshold"
  ) => (
    <NumberControl
      key={key}
      label={t("aidpRetrieval.fields.channelScoreThreshold")}
      helpKey={key}
      value={Number(c[key])}
      min={0}
      max={1}
      step={0.05}
      disabled={disabled}
      invalid={Boolean(errors[key])}
      onChange={(value) => onChange({ [key]: value })}
    />
  );

  const hybridTopKField = (
    <NumberControl
      key="hybrid_top_k"
      label={t(`aidpRetrieval.fields.${hKey}`)}
      helpKey="hybrid_top_k"
      value={Number(c.hybrid_top_k)}
      min={0}
      max={100}
      disabled={disabled}
      invalid={Boolean(errors.hybrid_top_k)}
      onChange={(value) => onChange({ hybrid_top_k: value })}
      note={
        <>
          <p className={styles.inlineNote}>
            {t("aidpRetrieval.zeroUnlimited")}
          </p>
          <p className={styles.inlineNote}>
            {t("aidpRetrieval.hybridTopKHint")}
          </p>
        </>
      }
    />
  );

  const reset = () => {
    setCombinationOpen(false);
    setDetailsOpen(false);
    setEnhancementOpen(false);
    onChange({ ...aidpDefaults });
  };

  return (
    <div className={styles.form} data-testid="aidp-retrieval-form">
      <p className={styles.scope}>{t(`aidpRetrieval.scope.${scope}`)}</p>

      <div className={styles.fields}>
        <div className={`${styles.field} ${styles.full}`}>
          <FieldHeading
            label={t("aidpRetrieval.fields.search_method")}
            helpKey="search_method"
          />
          <select
            className={styles.control}
            aria-label={t("aidpRetrieval.fields.search_method")}
            value={mixed ? "mixed" : (channels[0] ?? "")}
            disabled={disabled}
            onChange={(event) =>
              onChange({
                search_method:
                  event.target.value === "mixed"
                    ? "hybrid_search"
                    : event.target.value,
              })
            }
          >
            {["mixed", ...aidpChannels].map((method) => (
              <option key={method} value={method}>
                {t(`aidpRetrieval.methods.${method}`)}
              </option>
            ))}
          </select>
          <p className={styles.selectDescription}>
            {mixed
              ? t("aidpRetrieval.methodDescriptions.mixed")
              : channels[0]
                ? t(`aidpRetrieval.methodDescriptions.${channels[0]}`)
                : ""}
          </p>
        </div>

        {mixed ? (
          <Section
            title={t("aidpRetrieval.combination")}
            summary={combinationSummary}
            open={combinationOpen}
            onToggle={() => setCombinationOpen((current) => !current)}
            className={`${styles.full} ${styles.combinationSection}`}
          >
            <div
              role="group"
              aria-label={t("aidpRetrieval.combination")}
              className={styles.choices}
            >
              {aidpChannels.map((channel) => (
                <label key={channel} className={styles.choice}>
                  <input
                    type="checkbox"
                    checked={channels.includes(channel)}
                    disabled={disabled}
                    onChange={(event) => {
                      const next = aidpChannels.filter((method) =>
                        method === channel
                          ? event.target.checked
                          : channels.includes(method)
                      );
                      onChange({
                        search_method:
                          next.length === 3
                            ? "hybrid_search"
                            : next.length < 2
                              ? `${next.join("|")}|`
                              : next.join("|"),
                      });
                    }}
                  />
                  <span>{t(`aidpRetrieval.channelShort.${channel}`)}</span>
                </label>
              ))}
            </div>
            <p className={styles.inlineNote}>
              {t("aidpRetrieval.combinationHint")}
            </p>
          </Section>
        ) : null}
      </div>

      <div className={`${styles.fields} ${styles.commonFields}`}>
        <NumberControl
          label={t("aidpRetrieval.fields.top_k")}
          helpKey="top_k"
          value={Number(c.top_k)}
          min={1}
          max={100}
          disabled={disabled}
          invalid={Boolean(errors.top_k)}
          onChange={(value) => onChange({ top_k: value })}
        />
        <NumberControl
          label={t("aidpRetrieval.fields.score_threshold")}
          helpKey="score_threshold"
          value={Number(c.score_threshold)}
          min={0}
          max={1}
          step={0.05}
          disabled={disabled}
          invalid={Boolean(errors.score_threshold)}
          onChange={(value) => onChange({ score_threshold: value })}
        />
        <SwitchControl
          label={t("aidpRetrieval.fields.reranking_enable")}
          helpKey="reranking_enable"
          checked={Boolean(c.reranking_enable)}
          disabled={disabled}
          stateText={switchState(Boolean(c.reranking_enable))}
          onChange={(checked) =>
            onChange(
              checked
                ? { reranking_enable: true }
                : { reranking_enable: false, graph_reranking_enable: false }
            )
          }
        />
        <div className={styles.field}>
          <FieldHeading
            label={t("aidpRetrieval.fields.reranking_mode")}
            helpKey="reranking_mode"
          />
          <select
            className={styles.control}
            aria-label={t("aidpRetrieval.fields.reranking_mode")}
            value={String(c.reranking_mode)}
            disabled={disabled || !c.reranking_enable}
            onChange={(event) =>
              onChange({ reranking_mode: event.target.value })
            }
          >
            {["performance", "high_accuracy", "jargon_coverage"].map((mode) => (
              <option key={mode} value={mode}>
                {t(`aidpRetrieval.modes.${mode}`)}
              </option>
            ))}
          </select>
        </div>
      </div>

      <Section
        title={t("aidpRetrieval.details")}
        summary={detailsSummary}
        open={detailsOpen}
        onToggle={() => setDetailsOpen((current) => !current)}
      >
        {vector ? (
          <section
            className={styles.group}
            aria-label={t("aidpRetrieval.groups.vector_search")}
          >
            {channels.length > 1 ? (
              <h3 className={styles.groupHeading}>
                {t("aidpRetrieval.groups.vector_search")}
              </h3>
            ) : null}
            <div className={styles.fields}>
              {candidateField("vector_candidates")}
              {thresholdField("vector_score_threshold")}
            </div>
          </section>
        ) : null}
        {text ? (
          <section
            className={styles.group}
            aria-label={t("aidpRetrieval.groups.full_text_search")}
          >
            {channels.length > 1 ? (
              <h3 className={styles.groupHeading}>
                {t("aidpRetrieval.groups.full_text_search")}
              </h3>
            ) : null}
            <div className={styles.fields}>
              {candidateField("full_text_candidates")}
              {thresholdField("full_text_score_threshold")}
            </div>
          </section>
        ) : null}
        {graph ? (
          <section
            className={styles.group}
            aria-label={t("aidpRetrieval.groups.graph_search")}
          >
            {channels.length > 1 ? (
              <h3 className={styles.groupHeading}>
                {t("aidpRetrieval.groups.graph_search")}
              </h3>
            ) : null}
            <div className={styles.fields}>
              <NumberControl
                label={t("aidpRetrieval.fields.graph_top_k")}
                helpKey="graph_top_k"
                value={Number(c.graph_top_k)}
                min={0}
                max={100}
                disabled={disabled}
                invalid={Boolean(errors.graph_top_k)}
                onChange={(value) => onChange({ graph_top_k: value })}
                note={
                  <p className={styles.inlineNote}>
                    {t("aidpRetrieval.zeroUnlimited")}
                  </p>
                }
              />
              {thresholdField("graph_score_threshold")}
            </div>
            <div className={styles.graphSort}>
              <SwitchControl
                label={t("aidpRetrieval.fields.graph_reranking_enable")}
                helpKey="graph_reranking_enable"
                checked={Boolean(c.graph_reranking_enable)}
                disabled={disabled || !c.reranking_enable}
                stateText={switchState(
                  Boolean(c.graph_reranking_enable),
                  !c.reranking_enable
                )}
                onChange={(checked) =>
                  onChange({ graph_reranking_enable: checked })
                }
                note={
                  <p className={styles.inlineNote}>
                    {c.graph_reranking_enable
                      ? t("aidpRetrieval.graphRerankNote.on")
                      : t("aidpRetrieval.graphRerankNote.off")}
                  </p>
                }
              />
            </div>
            {showHybridTopK ? (
              <div className={styles.independentCount}>{hybridTopKField}</div>
            ) : null}
          </section>
        ) : null}
        {showHybridTopK && !graph ? (
          <div className={styles.independentCount}>{hybridTopKField}</div>
        ) : null}
      </Section>

      <Section
        title={t("aidpRetrieval.enhancement")}
        summary={t("aidpRetrieval.enhancementCount", {
          count: enhancementCount,
        })}
        open={enhancementOpen}
        onToggle={() => setEnhancementOpen((current) => !current)}
      >
        <div className={styles.fields}>
          {ENHANCEMENT_KEYS.map((key) => (
            <SwitchControl
              key={key}
              label={t(`aidpRetrieval.fields.${key}`)}
              helpKey={key}
              checked={Boolean(c[key])}
              disabled={disabled}
              stateText={switchState(Boolean(c[key]))}
              onChange={(checked) => onChange({ [key]: checked })}
            />
          ))}
        </div>
      </Section>

      {errorMessages.length > 0 ? (
        <p role="alert" className={styles.validation}>
          {errorMessages.join(" ")}
        </p>
      ) : null}
    </div>
  );
}
