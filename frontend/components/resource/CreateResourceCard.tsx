"use client";

import { Plus } from "lucide-react";

import ResourceCardShell from "./ResourceCardShell";

interface CreateResourceCardProps {
  title: string;
  onClick: () => void;
}

export default function CreateResourceCard({
  title,
  onClick,
}: CreateResourceCardProps) {
  return (
    <ResourceCardShell variant="create" onClick={onClick}>
      <span className="mb-4 flex size-12 items-center justify-center rounded-full border-2 border-slate-400 text-slate-400 transition group-hover:border-blue-500 group-hover:text-blue-500">
        <Plus size={24} />
      </span>
      <span className="text-base font-normal text-slate-500 transition group-hover:text-blue-600">
        {title}
      </span>
    </ResourceCardShell>
  );
}
