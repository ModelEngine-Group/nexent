"use client";

import { Plus } from "lucide-react";

import { cn } from "@/lib/utils";

export interface CreateResourceCardProps {
  title: string;
  onClick: () => void;
  className?: string;
}

export default function CreateResourceCard({
  title,
  onClick,
  className,
}: CreateResourceCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={title}
      className={cn(
        "group flex h-full min-h-[240px] w-full flex-col items-center justify-center rounded-lg border-2 border-dashed border-slate-300 bg-white p-6 text-center transition hover:border-blue-400 hover:bg-slate-50/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2",
        className
      )}
    >
      <span className="mb-4 flex size-12 items-center justify-center rounded-full border-2 border-slate-400 text-slate-400 transition group-hover:border-blue-500 group-hover:text-blue-500">
        <Plus size={24} aria-hidden="true" />
      </span>
      <span className="text-base font-normal text-slate-500 transition group-hover:text-blue-600">
        {title}
      </span>
    </button>
  );
}
