import assert from "node:assert/strict";
import test from "node:test";

import {
  AIDP_DOCUMENT_STATUS,
  collectUploadedFileIds,
  findPendingUploadIds,
  isAidpDocProcessing,
  isAidpDocTerminal,
  normalizeAidpDocStatus,
  // @ts-expect-error -- Node requires the extension for this standalone test.
} from "../lib/aidpDocumentStatus.ts";

test("normalizes status casing and surrounding whitespace", () => {
  assert.equal(normalizeAidpDocStatus(" processing "), "PROCESSING");
  assert.equal(normalizeAidpDocStatus("Completed"), "COMPLETED");
  assert.equal(normalizeAidpDocStatus(undefined), "");
  assert.equal(normalizeAidpDocStatus("   "), "");
});

test("treats only PROCESSING as non-terminal", () => {
  assert.equal(isAidpDocProcessing("PROCESSING"), true);
  assert.equal(isAidpDocProcessing("processing"), true);
  assert.equal(isAidpDocProcessing(AIDP_DOCUMENT_STATUS.COMPLETED), false);
  assert.equal(isAidpDocProcessing(undefined), false);

  assert.equal(isAidpDocTerminal("COMPLETED"), true);
  assert.equal(isAidpDocTerminal("failed"), true);
  assert.equal(isAidpDocTerminal("PROCESSING"), false);
  // An unknown status is not terminal: polling must not stop on a status the
  // UI does not understand.
  assert.equal(isAidpDocTerminal("QUEUED"), false);
  assert.equal(isAidpDocTerminal(undefined), false);
});

test("keeps an upload pending while AIDP has not listed it yet", () => {
  // The reported bug: right after an upload the file is not in the list at all,
  // so the refresh must keep running instead of stopping immediately.
  assert.deepEqual(findPendingUploadIds(["file-1"], []), ["file-1"]);
});

test("keeps an upload pending while it is still processing", () => {
  const documents = [{ file_ino_no: "file-1", status: "PROCESSING" }];
  assert.deepEqual(findPendingUploadIds(["file-1"], documents), ["file-1"]);
});

test("settles an upload once it reaches a terminal status", () => {
  assert.deepEqual(
    findPendingUploadIds(
      ["file-1"],
      [{ file_ino_no: "file-1", status: "COMPLETED" }]
    ),
    []
  );
  assert.deepEqual(
    findPendingUploadIds(
      ["file-1"],
      [{ file_ino_no: "file-1", status: "FAILED" }]
    ),
    []
  );
});

test("matches numeric upload ids against string document ids", () => {
  // AIDP returns numbers from the upload endpoint and strings from the history
  // listing, so a strict comparison would never settle the watch. The ids are
  // read back through the same helper the components use.
  const uploadedIds = collectUploadedFileIds([{ file_ino_no: 17001 }]);
  assert.deepEqual(uploadedIds, ["17001"]);
  assert.deepEqual(
    findPendingUploadIds(uploadedIds, [
      { file_ino_no: "17001", status: "COMPLETED" },
    ]),
    []
  );
});

test("reports only the uploads that are still unresolved", () => {
  const documents = [
    { file_ino_no: "file-1", status: "COMPLETED" },
    { file_ino_no: "file-2", status: "PROCESSING" },
    { file_ino_no: "file-other", status: "FAILED" },
  ];
  assert.deepEqual(
    findPendingUploadIds(["file-1", "file-2", "file-3"], documents),
    ["file-2", "file-3"]
  );
});

test("returns nothing to wait for when there was no upload", () => {
  assert.deepEqual(findPendingUploadIds([], [{ file_ino_no: "file-1" }]), []);
});

test("collects uploaded file ids from the upload response", () => {
  assert.deepEqual(
    collectUploadedFileIds([{ file_ino_no: 17001 }, { file_ino_no: "17002" }]),
    ["17001", "17002"]
  );
});

test("skips upload entries without a usable id", () => {
  // A missing id must not become the literal string "undefined", which would
  // never match a listed document and would keep the watch alive until timeout.
  assert.deepEqual(
    collectUploadedFileIds([
      {},
      { file_ino_no: undefined },
      { file_ino_no: "" },
      { file_ino_no: null },
      { file_ino_no: 17003 },
    ]),
    ["17003"]
  );
  assert.deepEqual(collectUploadedFileIds(undefined), []);
  assert.deepEqual(collectUploadedFileIds([]), []);
});
