"use client";

import { useEffect, useState } from "react";
import { Braces } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

const MAX_METADATA_BYTES = 64 * 1024;

interface RuntimeMetadataEditorProps {
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  disabled?: boolean;
  compact?: boolean;
  elevated?: boolean;
}

export function RuntimeMetadataEditor({
  value,
  onChange,
  disabled = false,
  compact = false,
  elevated = false,
}: Readonly<RuntimeMetadataEditorProps>) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("{}");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setDraft(JSON.stringify(value, null, 2));
      setError(null);
    }
  }, [open, value]);

  const save = () => {
    try {
      if (new TextEncoder().encode(draft).length > MAX_METADATA_BYTES) {
        setError(t("chat.runtimeMetadata.tooLarge"));
        return;
      }
      const parsed: unknown = JSON.parse(draft);
      if (
        parsed === null ||
        typeof parsed !== "object" ||
        Array.isArray(parsed)
      ) {
        setError(t("chat.runtimeMetadata.objectRequired"));
        return;
      }
      onChange(parsed as Record<string, unknown>);
      setOpen(false);
    } catch {
      setError(t("chat.runtimeMetadata.invalidJson"));
    }
  };

  const count = Object.keys(value).length;

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-8 gap-1.5 px-2 text-xs text-muted-foreground"
        onClick={() => setOpen(true)}
        disabled={disabled}
        title={t("chat.runtimeMetadata.description")}
      >
        <Braces className="size-3.5" />
        {!compact && <span>{t("chat.runtimeMetadata.title")}</span>}
        {count > 0 && <span>({count})</span>}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          className={elevated ? "z-[1100] sm:max-w-xl" : "sm:max-w-xl"}
        >
          <DialogHeader>
            <DialogTitle>{t("chat.runtimeMetadata.title")}</DialogTitle>
            <DialogDescription>
              {t("chat.runtimeMetadata.description")}
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value);
              setError(null);
            }}
            className="min-h-64 font-mono text-xs"
            spellCheck={false}
            aria-invalid={Boolean(error)}
          />
          {error && <p className="text-sm text-destructive">{error}</p>}
          <p className="text-xs text-muted-foreground">
            {t("chat.runtimeMetadata.securityWarning")}
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button onClick={save}>{t("common.confirm")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
