"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { StatusBadge } from "@/components/Badge";
import ScoreBar from "@/components/ScoreBar";
import { crmSyncLead, retryLead, type Lead } from "@/lib/api";
import { leadKeys } from "@/lib/query-keys";

interface LeadsTableProps {
  leads: Lead[];
}

const RUNNING_STATUSES = new Set([
  "queued",
  "parsing",
  "searching",
  "enriching",
  "icp_scoring",
  "generating_signals",
  "syncing_crm",
  "retrying",
  "pending",
]);

export default function LeadsTable({ leads }: LeadsTableProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [retryingIds, setRetryingIds] = useState<Set<number>>(new Set());
  const [syncingIds, setSyncingIds] = useState<Set<number>>(new Set());

  async function handleRetry(e: React.MouseEvent, leadId: number) {
    e.stopPropagation();
    setRetryingIds((prev) => new Set(prev).add(leadId));
    try {
      await retryLead(leadId);
    } finally {
      setRetryingIds((prev) => {
        const next = new Set(prev);
        next.delete(leadId);
        return next;
      });
    }
  }

  async function handleCrmRetry(e: React.MouseEvent, leadId: number) {
    e.stopPropagation();
    setSyncingIds((prev) => new Set(prev).add(leadId));
    try {
      await crmSyncLead(leadId);
      await queryClient.invalidateQueries({ queryKey: leadKeys.all });
    } finally {
      setSyncingIds((prev) => {
        const next = new Set(prev);
        next.delete(leadId);
        return next;
      });
    }
  }

  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
              Name
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
              Company
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
              ICP Score
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
              Top Signal
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
              Enrichment
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
              CRM Sync
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
              Actions
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {leads.length === 0 ? (
            <tr>
              <td colSpan={7} className="px-4 py-10 text-center text-sm text-gray-500">
                No leads yet. Upload a CSV to get started.
              </td>
            </tr>
          ) : (
            leads.map((lead) => {
              const isRunning = RUNNING_STATUSES.has(lead.status) && lead.status !== "pending" && lead.status !== "queued";
              const isFailed = lead.status === "failed";
              const crmFailed = lead.crm_sync_status?.status === "failed" || lead.crm_status === "failed";
              const isRetrying = retryingIds.has(lead.id);

              return (
                <tr
                  key={lead.id}
                  onClick={() => router.push(`/leads/${lead.id}`)}
                  className="cursor-pointer hover:bg-gray-50"
                >
                  <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">
                    <div className="flex items-center gap-2">
                      {isRunning && (
                        <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-blue-300 border-t-blue-600" />
                      )}
                      {lead.name}
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                    {lead.company}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <ScoreBar score={lead.icp_score} />
                  </td>
                  <td className="max-w-[180px] truncate px-4 py-3 text-sm text-gray-600">
                    {lead.top_buying_signal ?? "—"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <StatusBadge label={lead.status} />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    {lead.crm_sync_status || lead.crm_status ? (
                      <StatusBadge
                        label={lead.crm_sync_status?.status ?? lead.crm_status ?? "pending"}
                      />
                    ) : (
                      <span className="text-xs text-gray-400">—</span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                      {(isFailed || lead.status === "completed") && (
                        <button
                          type="button"
                          title="Retry enrichment"
                          disabled={isRetrying}
                          onClick={(e) => handleRetry(e, lead.id)}
                          className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-blue-600 disabled:opacity-50"
                        >
                          {isRetrying ? (
                            <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-gray-700" />
                          ) : (
                            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                            </svg>
                          )}
                        </button>
                      )}
                      {crmFailed && (
                        <button
                          type="button"
                          title="Retry CRM sync"
                          disabled={syncingIds.has(lead.id)}
                          onClick={(e) => handleCrmRetry(e, lead.id)}
                          className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-green-600 disabled:opacity-50"
                        >
                          {syncingIds.has(lead.id) ? (
                            <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-green-600" />
                          ) : (
                            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
                            </svg>
                          )}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
