"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import Toast from "@/components/Toast";
import { enrichLead, retryFailed, uploadCsv } from "@/lib/api";
import { leadKeys } from "@/lib/query-keys";

interface DashboardActionsProps {
  pendingLeadIds: number[];
  failedCount: number;
}

export default function DashboardActions({
  pendingLeadIds,
  failedCount,
}: DashboardActionsProps) {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [enriching, setEnriching] = useState(false);
  const [retryingAll, setRetryingAll] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" | "info" } | null>(null);

  async function handleRefresh() {
    setRefreshing(true);
    await queryClient.invalidateQueries({ queryKey: leadKeys.all });
    await queryClient.invalidateQueries({ queryKey: leadKeys.stats });
    setRefreshing(false);
    setToast({ message: "Table refreshed", type: "info" });
  }

  async function handleUpload(file: File) {
    setUploading(true);
    setToast(null);
    try {
      const result = await uploadCsv(file);
      setToast({
        message: `Queued ${result.records_count} leads for processing`,
        type: "success",
      });
      await queryClient.invalidateQueries({ queryKey: leadKeys.all });
      await queryClient.invalidateQueries({ queryKey: leadKeys.stats });
    } catch (err) {
      setToast({
        message: err instanceof Error ? err.message : "Upload failed",
        type: "error",
      });
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function handleEnrichAll() {
    if (pendingLeadIds.length === 0) {
      setToast({ message: "No pending leads to enrich", type: "info" });
      return;
    }
    setEnriching(true);
    try {
      for (const id of pendingLeadIds) {
        await enrichLead(id);
      }
      setToast({
        message: `Queued ${pendingLeadIds.length} leads for enrichment`,
        type: "success",
      });
      await queryClient.invalidateQueries({ queryKey: leadKeys.stats });
    } catch (err) {
      setToast({
        message: err instanceof Error ? err.message : "Enrichment failed",
        type: "error",
      });
    } finally {
      setEnriching(false);
    }
  }

  async function handleRetryAllFailed() {
    setRetryingAll(true);
    try {
      const result = await retryFailed();
      setToast({
        message: `Retrying ${result.retried} failed leads`,
        type: "success",
      });
    } catch (err) {
      setToast({
        message: err instanceof Error ? err.message : "Retry failed",
        type: "error",
      });
    } finally {
      setRetryingAll(false);
    }
  }

  const busy = uploading || enriching || retryingAll;

  return (
    <>
      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-gray-900">Lead actions</h2>
              <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-green-500" />
                Live
              </span>
            </div>
            <p className="mt-1 text-sm text-gray-500">
              Upload CSV (<code className="text-xs">name</code>,{" "}
              <code className="text-xs">company</code>) — processing starts immediately.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleRefresh}
              disabled={refreshing}
              title="Refresh table"
              className="rounded-md border border-gray-300 bg-white p-2 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              <svg
                className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                />
              </svg>
            </button>
            <input
              ref={inputRef}
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleUpload(file);
              }}
              disabled={busy}
              className="hidden"
              id="csv-upload"
            />
            <label
              htmlFor="csv-upload"
              className={`cursor-pointer rounded-md px-4 py-2 text-sm font-medium text-white ${
                busy ? "cursor-not-allowed bg-blue-400" : "bg-blue-600 hover:bg-blue-700"
              }`}
            >
              {uploading ? "Uploading…" : "Upload CSV"}
            </label>
            <button
              type="button"
              onClick={handleEnrichAll}
              disabled={busy || pendingLeadIds.length === 0}
              className="flex items-center gap-2 rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {enriching && (
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-gray-700" />
              )}
              {enriching ? "Queuing…" : `Enrich All (${pendingLeadIds.length})`}
            </button>
            {failedCount > 0 && (
              <button
                type="button"
                onClick={handleRetryAllFailed}
                disabled={busy}
                className="rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100 disabled:opacity-50"
              >
                {retryingAll ? "Retrying…" : `Retry All Failed (${failedCount})`}
              </button>
            )}
          </div>
        </div>
      </div>
      <Toast message={toast?.message ?? null} type={toast?.type} />
    </>
  );
}
