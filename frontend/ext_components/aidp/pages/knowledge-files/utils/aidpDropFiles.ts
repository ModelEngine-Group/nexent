// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/**
 * Browser drag-and-drop only exposes a directory as `DataTransferItem`s. The
 * `File` list flattens every file to its base name, which would lose the
 * folder hierarchy the upload contract needs. This walks the entry tree and
 * returns each file with its path relative to the dropped root.
 */

export interface AidpDroppedFile {
  file: File;
  /** Path including the dropped folder name, e.g. `合同/2026/a.pdf`. */
  relativePath: string;
}

interface LegacyFileSystemEntry {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
  file?: (
    success: (file: File) => void,
    error: (error: unknown) => void
  ) => void;
  createReader?: () => {
    readEntries: (
      success: (entries: LegacyFileSystemEntry[]) => void,
      error: (error: unknown) => void
    ) => void;
  };
}

const readDirectoryEntries = (
  reader: NonNullable<
    ReturnType<NonNullable<LegacyFileSystemEntry["createReader"]>>
  >
): Promise<LegacyFileSystemEntry[]> =>
  new Promise((resolve, reject) => {
    const collected: LegacyFileSystemEntry[] = [];
    const readBatch = () => {
      reader.readEntries((entries) => {
        if (entries.length === 0) {
          resolve(collected);
          return;
        }
        collected.push(...entries);
        readBatch();
      }, reject);
    };
    readBatch();
  });

const DROP_TRAVERSAL_CONCURRENCY = 8;

/** Map entries with a fixed worker count so a deep tree cannot flood the browser. */
const mapWithConcurrency = async <T, R>(
  items: T[],
  mapper: (item: T) => Promise<R>,
  limit = DROP_TRAVERSAL_CONCURRENCY
): Promise<R[]> => {
  const results = new Array<R>(items.length);
  let nextIndex = 0;
  const workers = Array.from(
    { length: Math.min(limit, items.length) },
    async () => {
      while (nextIndex < items.length) {
        const index = nextIndex;
        nextIndex += 1;
        results[index] = await mapper(items[index]);
      }
    }
  );
  await Promise.all(workers);
  return results;
};

const walkEntry = async (
  entry: LegacyFileSystemEntry,
  parentPath: string
): Promise<AidpDroppedFile[]> => {
  const entryPath = parentPath ? `${parentPath}/${entry.name}` : entry.name;
  if (entry.isFile && entry.file) {
    const file = await new Promise<File>((resolve, reject) =>
      entry.file!(resolve, reject)
    );
    return [{ file, relativePath: entryPath }];
  }
  if (entry.isDirectory && entry.createReader) {
    const reader = entry.createReader();
    const children = await readDirectoryEntries(reader);
    const nested = await mapWithConcurrency(children, (child) =>
      walkEntry(child, entryPath)
    );
    return nested.flat();
  }
  return [];
};

/** Collect dropped files, preserving subdirectories when the browser allows it. */
export const collectDroppedFiles = async (
  dataTransfer: DataTransfer
): Promise<AidpDroppedFile[]> => {
  const items = Array.from(dataTransfer.items ?? []);
  const entries = items
    .map((item) => {
      const getAsEntry = (
        item as DataTransferItem & {
          webkitGetAsEntry?: () => LegacyFileSystemEntry | null;
        }
      ).webkitGetAsEntry;
      return typeof getAsEntry === "function" ? getAsEntry.call(item) : null;
    })
    .filter((entry): entry is LegacyFileSystemEntry => Boolean(entry));

  if (entries.length > 0) {
    const collected = (
      await mapWithConcurrency(entries, (entry) => walkEntry(entry, ""))
    ).flat();
    if (collected.length > 0) return collected;
  }

  return Array.from(dataTransfer.files ?? []).map((file) => ({
    file,
    relativePath: file.name,
  }));
};

/** Read a folder-picker selection, which already carries `webkitRelativePath`. */
export const filesFromPicker = (files: FileList | File[]): AidpDroppedFile[] =>
  Array.from(files).map((file) => ({
    file,
    relativePath: file.webkitRelativePath || file.name,
  }));
