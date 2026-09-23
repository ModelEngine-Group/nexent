/**
 * AIDP knowledge-file status helpers.
 *
 * Intentionally dependency-free (no imports) so the behaviour can be unit
 * tested directly with `node --test`, like the other standalone helpers under
 * `lib/`.
 *
 * Background: AIDP accepts an upload before it has chunked/embedded/indexed the
 * file, and the file may not show up in the history directory for a moment
 * after that. The list therefore has to keep refreshing itself after an upload
 * until every uploaded file is listed with a terminal status — that is what
 * `findPendingUploadIds` decides.
 */

/** Processing statuses AIDP reports for a knowledge file. */
export const AIDP_DOCUMENT_STATUS = {
  UPLOADING: "UPLOADING",
  PROCESSING: "PROCESSING",
  EXTRACTING: "EXTRACTING",
  COMPLETED: "COMPLETED",
  FAILED: "FAILED",
} as const;

/**
 * Terminal statuses: the file will not change again, so it is pointless to keep
 * polling for it.
 */
export const AIDP_DOC_TERMINAL_STATUSES: readonly string[] = [
  AIDP_DOCUMENT_STATUS.COMPLETED,
  AIDP_DOCUMENT_STATUS.FAILED,
];

/**
 * In-progress statuses, in the order AIDP walks through them: the file is being
 * uploaded, then chunked/embedded, then its content is extracted. Every one of
 * them keeps the status column live and must keep the list polling.
 */
export const AIDP_DOC_IN_PROGRESS_STATUSES: readonly string[] = [
  AIDP_DOCUMENT_STATUS.UPLOADING,
  AIDP_DOCUMENT_STATUS.PROCESSING,
  AIDP_DOCUMENT_STATUS.EXTRACTING,
];

/**
 * Polling interval of the AIDP document list while work is outstanding.
 * Ingestion takes seconds to minutes, so ten seconds keeps the status column
 * responsive without hammering the backend.
 */
export const AIDP_DOC_STATUS_POLL_MS = 10000;

/**
 * Upper bound on how long the list keeps refreshing for files the user just
 * uploaded. Guards against polling forever when AIDP silently drops an upload
 * (or never reports the file through the history endpoint).
 */
export const AIDP_DOC_UPLOAD_WATCH_TIMEOUT_MS = 5 * 60 * 1000;

/** Normalize a status for comparison; AIDP capitalization is not guaranteed. */
export const normalizeAidpDocStatus = (status?: string): string =>
  (status || "").trim().toUpperCase();

/**
 * Whether the status means "still on its way in".
 *
 * Any status AIDP has not told us is terminal counts as in progress, so a new
 * upstream state keeps the column live instead of freezing the list.
 */
export const isAidpDocProcessing = (status?: string): boolean => {
  const normalized = normalizeAidpDocStatus(status);
  if (!normalized) return false;
  return !isAidpDocTerminal(normalized);
};

/** Whether the status means "finished, one way or the other". */
export const isAidpDocTerminal = (status?: string): boolean =>
  AIDP_DOC_TERMINAL_STATUSES.includes(normalizeAidpDocStatus(status));

/** Structural view of a listed document, so this module stays import-free. */
export interface AidpDocumentStatusView {
  file_ino_no?: string | number | null;
  status?: string;
}

/** Structural view of an entry of the AIDP upload response `success_list`. */
export interface AidpUploadedFileView {
  file_ino_no?: string | number | null;
}

/**
 * Collect the identities of the files AIDP accepted in an upload response.
 *
 * Entries without a usable `file_ino_no` are skipped rather than coerced into
 * the literal string `"undefined"`, which would never match a listed document
 * and would therefore keep the watch alive until it times out.
 */
export const collectUploadedFileIds = (
  successList?: readonly AidpUploadedFileView[]
): string[] => {
  const ids: string[] = [];
  for (const item of successList ?? []) {
    const raw = item?.file_ino_no;
    if (raw === undefined || raw === null || raw === "") continue;
    ids.push(String(raw));
  }
  return ids;
};

/**
 * Which of the uploaded files are still unresolved.
 *
 * A file counts as resolved only once it appears in the list with a terminal
 * status. A file that is not listed at all stays pending deliberately: right
 * after an upload AIDP may not report it yet, and treating "not listed" as done
 * would stop the refresh exactly when the list is still stale — the case where
 * the user cannot tell whether the upload worked.
 */
export const findPendingUploadIds = (
  uploadedIds: readonly string[],
  documents: readonly AidpDocumentStatusView[]
): string[] => {
  if (uploadedIds.length === 0) return [];
  const resolved = new Set(
    documents
      .filter((doc) => isAidpDocTerminal(doc.status))
      .map((doc) => String(doc.file_ino_no))
  );
  return uploadedIds.filter((id) => !resolved.has(String(id)));
};
