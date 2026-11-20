// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  buildUploadBatches,
  summarizeUploadFiles,
} from "@/lib/uploadCenter/batching";
import type {
  UploadBatchRecord,
  UploadBatchFile,
  UploadBatchResult,
  UploadCenterSnapshot,
  UploadEnqueueInput,
  UploadFileRecord,
  UploadJobRecord,
  UploadTransport,
} from "@/types/uploadCenter";

const EMPTY_SNAPSHOT: UploadCenterSnapshot = {
  files: {},
  fileOrder: [],
  jobs: {},
  batches: {},
  cancelling: false,
};

const PROGRESS_NOTIFY_INTERVAL_MS = 100;

/**
 * Framework-agnostic upload queue.
 *
 * One store lives for the whole browser session. Files are the persisted unit
 * of the UI, while batches are the unit sent to the backend. The provider
 * subscribes with useSyncExternalStore so progress updates do not re-render
 * the whole application tree.
 */
export class UploadCenterStore {
  private snapshot: UploadCenterSnapshot = EMPTY_SNAPSHOT;
  private listeners = new Set<() => void>();
  private queue: string[] = [];
  private activeBatches = new Set<string>();
  private controllers = new Map<string, AbortController>();
  private transports = new Map<string, UploadTransport>();
  private callbacks = new Map<string, () => void>();
  private completedCallbacks = new Set<string>();
  private draining = false;
  private idCounter = 0;
  private lastProgressNotify = 0;
  private readonly concurrency = 2;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = (): UploadCenterSnapshot => this.snapshot;

  getSummary() {
    return summarizeUploadFiles(
      this.snapshot.files,
      this.snapshot.fileOrder,
      this.snapshot.batches
    );
  }

  isActive(): boolean {
    return this.getSummary().active > 0;
  }

  canClose(): boolean {
    return this.getSummary().canClose;
  }

  private makeId(prefix: string): string {
    this.idCounter += 1;
    return `${prefix}-${Date.now()}-${this.idCounter}`;
  }

  private notify(): void {
    this.snapshot = { ...this.snapshot };
    this.listeners.forEach((listener) => listener());
  }

  enqueue(input: UploadEnqueueInput): void {
    const jobId = this.makeId("upload-job");
    const records: UploadFileRecord[] = input.files.map(
      ({ file, relativePath }) => ({
        id: this.makeId("upload-file"),
        jobId,
        file,
        name: file.name,
        size: file.size,
        relativePath: relativePath || file.name,
        context: input.context,
        status: "queued",
      })
    );
    if (records.length === 0) return;

    let failures: Record<
      string,
      { reasonKey: string; reasonParams?: Record<string, string | number> }
    > = {};
    try {
      const result = input.transport.validateFiles(
        records.map((record) => ({
          id: record.id,
          file: record.file,
          relativePath: record.relativePath,
        })),
        input.context
      );
      failures = Object.fromEntries(
        result.failures.map((failure) => [
          failure.fileId,
          {
            reasonKey: failure.reasonKey,
            reasonParams: failure.reasonParams,
          },
        ])
      );
    } catch {
      failures = Object.fromEntries(
        records.map((record) => [
          record.id,
          { reasonKey: "uploadCenter.validation.generic" },
        ])
      );
    }

    for (const record of records) {
      const failure = failures[record.id];
      if (failure) {
        record.status = "validation_failed";
        record.errorKey = failure.reasonKey;
        record.errorParams = failure.reasonParams;
        record.retryable = false;
      }
    }

    const validFiles = records.filter((record) => record.status === "queued");
    const batches: UploadBatchRecord[] = buildUploadBatches(
      validFiles,
      input.transport.capabilities
    ).map((plan) => ({
      id: this.makeId("upload-batch"),
      jobId,
      fileIds: plan.fileIds,
      status: "pending",
      totalBytes: plan.totalBytes,
      loadedBytes: 0,
    }));

    const job: UploadJobRecord = {
      id: jobId,
      context: input.context,
      sourceLabel: input.sourceLabel,
      fileIds: records.map((record) => record.id),
      batchIds: batches.map((batch) => batch.id),
      status: batches.length > 0 ? "queued" : "completed",
    };

    const files = { ...this.snapshot.files };
    for (const record of records) files[record.id] = record;
    const jobs = { ...this.snapshot.jobs, [jobId]: job };
    const batchMap = { ...this.snapshot.batches };
    for (const batch of batches) batchMap[batch.id] = batch;

    this.snapshot = {
      files,
      fileOrder: [
        ...this.snapshot.fileOrder,
        ...records.map((record) => record.id),
      ],
      jobs,
      batches: batchMap,
      cancelling: this.snapshot.cancelling,
    };
    this.transports.set(jobId, input.transport);
    if (input.onComplete) this.callbacks.set(jobId, input.onComplete);
    if (batches.length > 0) {
      this.queue.push(...batches.map((batch) => batch.id));
    } else {
      this.finalizeJob(jobId);
    }
    this.notify();
    void this.drain();
  }

  retryFailed(fileIds?: string[]): void {
    const only = fileIds ? new Set(fileIds) : null;
    const retryIdsByJob = new Map<string, string[]>();
    for (const [jobId, job] of Object.entries(this.snapshot.jobs)) {
      const retryIds = job.fileIds.filter((fileId) => {
        const file = this.snapshot.files[fileId];
        return (
          (!only || only.has(fileId)) &&
          (file?.status === "upload_failed" || file?.status === "cancelled") &&
          file.retryable !== false
        );
      });
      if (retryIds.length > 0) retryIdsByJob.set(jobId, retryIds);
    }
    if (retryIdsByJob.size === 0) return;

    const files = { ...this.snapshot.files };
    const jobs = { ...this.snapshot.jobs };
    const batches = { ...this.snapshot.batches };
    const newBatchIds: string[] = [];

    for (const [jobId, fileIds] of retryIdsByJob) {
      const job = jobs[jobId];
      const transport = this.transports.get(jobId);
      if (!job || !transport) continue;
      for (const fileId of fileIds) {
        files[fileId] = {
          ...files[fileId],
          status: "queued",
          error: undefined,
          errorKey: undefined,
          errorParams: undefined,
          retryable: undefined,
        };
      }
      const retryFiles = fileIds.map((fileId) => files[fileId]);
      const retryBatches = buildUploadBatches(
        retryFiles,
        transport.capabilities
      ).map((plan) => ({
        id: this.makeId("upload-batch"),
        jobId,
        fileIds: plan.fileIds,
        status: "pending" as const,
        totalBytes: plan.totalBytes,
        loadedBytes: 0,
      }));
      for (const batch of retryBatches) {
        batches[batch.id] = batch;
        newBatchIds.push(batch.id);
      }
      jobs[jobId] = {
        ...job,
        batchIds: [...job.batchIds, ...retryBatches.map((batch) => batch.id)],
        status: "queued",
      };
      this.completedCallbacks.delete(jobId);
    }

    this.snapshot = {
      ...this.snapshot,
      files,
      jobs,
      batches,
      cancelling: false,
    };
    this.queue.unshift(...newBatchIds);
    this.notify();
    void this.drain();
  }

  cancelAll(): boolean {
    if (!this.isActive()) return false;

    const files = { ...this.snapshot.files };
    const batches = { ...this.snapshot.batches };
    for (const batchId of this.queue) {
      const batch = batches[batchId];
      if (!batch || batch.status !== "pending") continue;
      batches[batchId] = { ...batch, status: "cancelled" };
      for (const fileId of batch.fileIds) {
        const file = files[fileId];
        if (!file) continue;
        files[fileId] = {
          ...file,
          status: "cancelled",
          error: undefined,
          errorKey: "uploadCenter.statusCancelled",
          errorParams: undefined,
          retryable: true,
        };
      }
    }
    this.queue = [];

    const activeBatchIds = Array.from(this.activeBatches);
    this.snapshot = {
      ...this.snapshot,
      files,
      batches,
      cancelling: activeBatchIds.length > 0,
    };
    for (const batchId of activeBatchIds) {
      const controller = this.controllers.get(batchId);
      if (!controller) continue;
      try {
        controller.abort();
      } catch {
        // The request already settled; runBatch applies the real outcome.
      }
    }

    for (const jobId of Object.keys(this.snapshot.jobs)) {
      this.finalizeJob(jobId);
    }
    this.notify();
    return true;
  }

  close(): boolean {
    if (!this.canClose()) return false;
    this.snapshot = EMPTY_SNAPSHOT;
    this.queue = [];
    this.activeBatches.clear();
    this.controllers.forEach((controller) => controller.abort());
    this.controllers.clear();
    this.transports.clear();
    this.callbacks.clear();
    this.completedCallbacks.clear();
    this.notify();
    return true;
  }

  private targetKeyForBatch(batchId: string): string {
    const batch = this.snapshot.batches[batchId];
    const job = batch ? this.snapshot.jobs[batch.jobId] : undefined;
    return `${job?.context.knowledgeBaseId ?? ""}\u0000${
      job?.context.targetFolder ?? ""
    }`;
  }

  private drain(): void {
    if (this.draining) return;
    this.draining = true;
    try {
      while (this.activeBatches.size < this.concurrency) {
        const activeTargets = new Set(
          Array.from(this.activeBatches).map((id) => this.targetKeyForBatch(id))
        );
        const index = this.queue.findIndex((batchId) => {
          const batch = this.snapshot.batches[batchId];
          return (
            batch?.status === "pending" &&
            !activeTargets.has(this.targetKeyForBatch(batchId))
          );
        });
        if (index === -1) break;
        const [batchId] = this.queue.splice(index, 1);
        void this.runBatch(batchId);
      }
    } finally {
      this.draining = false;
    }
  }

  private async runBatch(batchId: string): Promise<void> {
    const batch = this.snapshot.batches[batchId];
    if (!batch || batch.status !== "pending") return;
    const job = this.snapshot.jobs[batch.jobId];
    const transport = this.transports.get(batch.jobId);
    if (!job || !transport) return;

    this.activeBatches.add(batchId);
    this.updateBatch(batchId, {
      status: "uploading",
      loadedBytes: 0,
    });
    this.updateFiles(batch.fileIds, { status: "uploading" });
    this.notify();

    const controller = new AbortController();
    this.controllers.set(batchId, controller);
    const batchFiles: UploadBatchFile[] = batch.fileIds
      .map((fileId) => this.snapshot.files[fileId])
      .filter((file): file is UploadFileRecord => Boolean(file))
      .map((file) => ({
        id: file.id,
        file: file.file,
        relativePath: file.relativePath,
      }));

    try {
      const result = await transport.uploadBatch(
        batchFiles,
        job.context,
        controller.signal,
        (loaded, total) => this.updateBatchProgress(batchId, loaded, total)
      );
      this.applyBatchResult(batchId, result);
    } catch (error) {
      const aborted =
        controller.signal.aborted ||
        (error instanceof DOMException && error.name === "AbortError");
      if (aborted) {
        this.applyCancelledBatch(batchId);
      } else {
        const reason =
          error instanceof Error && error.message
            ? error.message
            : "uploadCenter.error.unknown";
        this.applyBatchResult(batchId, {
          successFileIds: [],
          failed: batch.fileIds.map((fileId) => ({
            fileId,
            reason,
            retryable: true,
          })),
        });
      }
    } finally {
      this.activeBatches.delete(batchId);
      this.controllers.delete(batchId);
      this.updateBatch(batchId, (current) => ({
        ...current,
        loadedBytes:
          current.status === "success"
            ? current.totalBytes
            : current.loadedBytes,
      }));
      if (this.snapshot.cancelling && this.activeBatches.size === 0) {
        this.snapshot = { ...this.snapshot, cancelling: false };
      }
      this.finalizeJob(batch.jobId);
      this.notify();
      this.drain();
    }
  }

  private updateBatchProgress(
    batchId: string,
    loadedBytes: number,
    totalBytes: number
  ): void {
    const batch = this.snapshot.batches[batchId];
    if (!batch) return;
    this.updateBatch(batchId, (current) => ({
      ...current,
      loadedBytes,
      totalBytes: totalBytes > 0 ? totalBytes : current.totalBytes,
    }));
    const now = Date.now();
    if (now - this.lastProgressNotify >= PROGRESS_NOTIFY_INTERVAL_MS) {
      this.lastProgressNotify = now;
      this.notify();
    }
  }

  private applyBatchResult(batchId: string, result: UploadBatchResult): void {
    const batch = this.snapshot.batches[batchId];
    if (!batch) return;
    const success = new Set(result.successFileIds);
    const failed = new Map(
      result.failed.map((failure) => [failure.fileId, failure])
    );
    const updates: Record<string, Partial<UploadFileRecord>> = {};
    for (const fileId of batch.fileIds) {
      if (success.has(fileId)) {
        updates[fileId] = {
          status: "success",
          error: undefined,
          errorKey: undefined,
          errorParams: undefined,
          retryable: undefined,
        };
        continue;
      }
      const failure = failed.get(fileId);
      updates[fileId] = {
        status: "upload_failed",
        error: failure?.reason ?? "uploadCenter.error.unknown",
        errorKey: undefined,
        errorParams: undefined,
        retryable: failure?.retryable !== false,
      };
    }
    this.updateFiles(
      batch.fileIds,
      (fileId) => updates[fileId] ?? { status: "upload_failed" }
    );
    this.updateBatch(batchId, {
      status: batch.fileIds.every((fileId) => success.has(fileId))
        ? "success"
        : "failed",
      loadedBytes: batch.totalBytes,
    });
  }

  private applyCancelledBatch(batchId: string): void {
    const batch = this.snapshot.batches[batchId];
    if (!batch) return;
    this.updateFiles(batch.fileIds, {
      status: "cancelled",
      error: undefined,
      errorKey: "uploadCenter.statusCancelled",
      errorParams: undefined,
      retryable: true,
    });
    this.updateBatch(batchId, { status: "cancelled" });
  }

  private finalizeJob(jobId: string): void {
    const job = this.snapshot.jobs[jobId];
    if (!job) return;
    const hasActiveFile = job.fileIds.some((fileId) => {
      const file = this.snapshot.files[fileId];
      return file?.status === "queued" || file?.status === "uploading";
    });
    const hasActiveBatch = job.batchIds.some((batchId) => {
      const batch = this.snapshot.batches[batchId];
      return batch?.status === "pending" || batch?.status === "uploading";
    });
    const status = hasActiveFile || hasActiveBatch ? "uploading" : "completed";
    if (job.status !== status) {
      this.snapshot = {
        ...this.snapshot,
        jobs: {
          ...this.snapshot.jobs,
          [jobId]: { ...job, status },
        },
      };
    }
    if (status === "completed" && !this.completedCallbacks.has(jobId)) {
      this.completedCallbacks.add(jobId);
      this.callbacks.get(jobId)?.();
    }
  }

  private updateFiles(
    fileIds: string[],
    update:
      | Partial<UploadFileRecord>
      | ((fileId: string) => Partial<UploadFileRecord>)
  ): void {
    const files = { ...this.snapshot.files };
    for (const fileId of fileIds) {
      const file = files[fileId];
      if (!file) continue;
      const patch = typeof update === "function" ? update(fileId) : update;
      files[fileId] = { ...file, ...patch };
    }
    this.snapshot = { ...this.snapshot, files };
  }

  private updateBatch(
    batchId: string,
    update:
      | Partial<UploadBatchRecord>
      | ((batch: UploadBatchRecord) => UploadBatchRecord)
  ): void {
    const batch = this.snapshot.batches[batchId];
    if (!batch) return;
    const next =
      typeof update === "function" ? update(batch) : { ...batch, ...update };
    this.snapshot = {
      ...this.snapshot,
      batches: { ...this.snapshot.batches, [batchId]: next },
    };
  }
}

export const createUploadCenterStore = (): UploadCenterStore =>
  new UploadCenterStore();
