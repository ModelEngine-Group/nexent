// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { useState } from "react";
import Link from "next/link";
import { Alert, Button, Input, Modal } from "antd";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { evolutionService as api, type SuggestionReceipt } from "@/services/evolutionService";

export function SuggestionReceiptActions({ receipt }: { receipt: SuggestionReceipt }) {
  const { t, i18n } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const viewer = JSON.stringify([user?.tenantId, user?.id]);
  const [editing, setEditing] = useState<number>();
  const actions = useQuery({
    queryKey: ["suggestion-actions", viewer, receipt.conversation_id, receipt.message_id],
    queryFn: () => api.suggestionActions(receipt),
    enabled: !!user,
    retry: false,
    gcTime: 0,
  });
  if (!user || actions.isError || (!actions.data?.compare && !actions.data?.edit)) return null;
  const compare = actions.data.compare;
  const edit = actions.data.edit;
  const params = new URLSearchParams({ tab: "evolution" });
  if (compare) {
    for (const [key, value] of Object.entries(compare)) {
      if (value !== null) params.set(key, String(value));
    }
  }
  const locale = i18n.language.startsWith("zh") ? "zh" : "en";
  return (
    <div className="flex items-center gap-3 text-sm">
      {compare && <Link className="text-primary hover:underline" href={`/${locale}/evaluation?${params}`}>
        {t("evolution.receipt.compare")}
      </Link>}
      {edit && <Button size="small" type="link" onClick={() => setEditing(edit.candidate_id)}>
        {t("evolution.receipt.edit")}
      </Button>}
      {editing && edit && <CandidateEditor key={`${viewer}:${editing}`} viewer={viewer} receipt={receipt} candidate={editing}
        onClose={() => setEditing(undefined)} onSaved={() => void actions.refetch()} />}
    </div>
  );
}

function CandidateEditor({ viewer, receipt, candidate, onClose, onSaved }: {
  viewer: string;
  receipt: SuggestionReceipt;
  candidate: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation("common");
  const [replacement, setReplacement] = useState<string>();
  const current = useQuery({
    queryKey: ["suggestion-candidate", viewer, receipt.conversation_id, receipt.message_id, candidate],
    queryFn: () => api.suggestionCandidate(receipt, candidate),
    retry: false,
    gcTime: 0,
  });
  const revision = useMutation({
    mutationFn: (text: string) => api.reviseSuggestionCandidate(receipt, candidate, text),
    onSuccess: onSaved,
  });
  const disabled = !current.data || current.isError || !replacement?.trim() ||
    replacement.trim() === current.data.new.trim() || replacement.trim() === current.data.old.trim();
  return <Modal open title={t("evolution.receipt.edit")} onCancel={onClose}
    okText={t("evolution.receipt.save")} cancelText={t("common.close")}
    okButtonProps={{ disabled: disabled || !!revision.data }} confirmLoading={revision.isPending}
    onOk={() => { if (!disabled && replacement) revision.mutate(replacement); }}>
    {current.isPending && <p>{t("common.loading")}</p>}
    {current.data && !current.isError && <div className="space-y-3">
      <p className="font-medium">{current.data.skill_name} · #{candidate}</p>
      <p>{t("evolution.receipt.original")}</p>
      <pre className="whitespace-pre-wrap break-words rounded bg-muted p-2">{current.data.old}</pre>
      <label className="block">{t("evolution.receipt.replacement")}
        <Input.TextArea maxLength={3000} rows={5} value={replacement ?? current.data.new} disabled={!!revision.data || revision.isPending}
          onChange={(event) => { setReplacement(event.target.value); revision.reset(); }} />
      </label>
    </div>}
    {(current.error || revision.error) && <Alert type="error" message={(current.error || revision.error)?.message} />}
    {revision.data && <Alert type="success" message={t("evolution.receipt.saved", { id: revision.data.candidate_id })} />}
  </Modal>;
}
