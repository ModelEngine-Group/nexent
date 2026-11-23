// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ArrowRight, Blocks, Library, Sparkles, Wrench } from "lucide-react";

import { cn } from "@/lib/utils";
import type {
  AgentSuggestionItem,
  AgentSuggestionProps,
  AgentSuggestionStyleProps,
} from "@/types/agentSuggestion";

interface SuggestionListProps extends AgentSuggestionStyleProps {
  renderItem: (suggestion: AgentSuggestionItem) => ReactNode;
  itemClassName?: string;
  listClassName?: string;
  headingClassName?: string;
}

function SuggestionList({
  suggestions,
  onSelect,
  disabled = false,
  className,
  renderItem,
  itemClassName,
  listClassName,
  headingClassName,
}: SuggestionListProps) {
  const { t } = useTranslation("common");
  if (suggestions.length === 0) return null;

  return (
    <section
      className={cn(
        "@container mx-auto w-full min-w-0 max-w-[672px] text-left",
        className
      )}
    >
      <h2
        className={cn(
          "mb-4 text-center text-base font-medium leading-6 text-foreground",
          headingClassName
        )}
      >
        {t("agentSuggestion.heading")}
      </h2>
      <ul
        className={cn("m-0 flex list-none flex-col gap-2 p-0", listClassName)}
      >
        {suggestions.map((suggestion) => (
          <li key={suggestion.id} className="min-w-0">
            <button
              type="button"
              disabled={disabled || suggestion.disabled}
              onClick={() => onSelect(suggestion.prompt, suggestion)}
              className={cn(
                "group h-full w-full min-w-0 cursor-pointer rounded-[14px] text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
                itemClassName
              )}
            >
              {renderItem(suggestion)}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function TextSuggestion(props: AgentSuggestionStyleProps) {
  return (
    <SuggestionList
      {...props}
      className={cn("max-w-[576px]", props.className)}
      listClassName="gap-3"
      itemClassName="flex min-h-[46px] items-center gap-3 border border-border bg-background px-4 py-3 hover:border-primary/40 hover:bg-accent/40"
      renderItem={({ title, icon: Icon }) => (
        <>
          {Icon ? (
            <Icon className="size-4 shrink-0 text-primary" aria-hidden />
          ) : (
            <span
              className="size-1.5 shrink-0 rounded-full bg-primary/50"
              aria-hidden
            />
          )}
          <span className="min-w-0 flex-1 break-words text-sm leading-5">
            {title}
          </span>
          <ArrowRight
            className="size-4 shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5"
            aria-hidden
          />
        </>
      )}
    />
  );
}

export function CardSuggestion(props: AgentSuggestionStyleProps) {
  const icons = [Wrench, Blocks, Sparkles, Library];
  return (
    <SuggestionList
      {...props}
      headingClassName="mb-3 text-left text-sm font-semibold leading-normal"
      itemClassName="flex items-start gap-3 rounded-xl px-3 py-3 enabled:hover:bg-accent/50 motion-reduce:transition-none"
      renderItem={({ id, title, description, icon }) => {
        const hash = Array.from(id).reduce(
          (value, character) =>
            (Math.imul(value, 31) + character.codePointAt(0)!) >>> 0,
          0
        );
        const Icon = icon ?? icons[hash % icons.length];
        return (
          <>
            <span className="mt-0.5 shrink-0 text-muted-foreground">
              <Icon className="size-4" aria-hidden />
            </span>
            <span className="min-w-0">
              <span className="block break-words text-sm font-medium text-foreground">
                {title}
              </span>
              {description && (
                <span className="mt-1 block break-words text-xs leading-5 text-muted-foreground">
                  {description}
                </span>
              )}
            </span>
          </>
        );
      }}
    />
  );
}

export function AgentSuggestion({ variant, ...props }: AgentSuggestionProps) {
  switch (variant) {
    case "text":
      return <TextSuggestion {...props} />;
    case "card":
      return <CardSuggestion {...props} />;
  }
}
