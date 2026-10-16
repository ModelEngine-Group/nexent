// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ArrowRight, Blocks, Library, Sparkles, Wrench } from "lucide-react";

import { StandardCard } from "@/components/common/StandardCard";
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
}

function SuggestionList({
  suggestions,
  onSelect,
  disabled = false,
  className,
  renderItem,
  itemClassName,
  listClassName,
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
      <h2 className="mb-4 text-center text-base font-medium leading-6 text-foreground">
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
      listClassName="grid grid-cols-1 gap-3 @[400px]:grid-cols-2"
      itemClassName="transition-[translate,box-shadow] duration-200 motion-safe:enabled:hover:-translate-y-0.5 enabled:hover:shadow-md motion-reduce:transition-none"
      renderItem={({ id, title, description, icon }) => {
        const hash = Array.from(id).reduce(
          (value, character) =>
            (Math.imul(value, 31) + character.codePointAt(0)!) >>> 0,
          0
        );
        const Icon = icon ?? icons[hash % icons.length];
        return (
          <StandardCard
            bordered
            borderRadius={14}
            className="h-full w-full !bg-background text-left transition-colors duration-200 group-[:enabled:hover]:!border-primary/60 group-[:enabled:hover]:!bg-accent/40 group-focus-visible:!border-primary/60 motion-reduce:transition-none"
            styles={{ body: { padding: 16, height: "100%" } }}
          >
            <span className="flex items-start gap-3">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-accent text-primary">
                <Icon className="size-[18px]" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block break-words text-sm font-medium leading-[22px] text-foreground">
                  {title}
                </span>
                {description && (
                  <span className="mt-1 block break-words text-xs leading-5 text-muted-foreground">
                    {description}
                  </span>
                )}
              </span>
            </span>
          </StandardCard>
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
