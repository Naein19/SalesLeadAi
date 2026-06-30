"use client";

import DashboardActions from "@/components/DashboardActions";
import LeadsTable from "@/components/LeadsTable";
import ProgressBar from "@/components/ProgressBar";
import { useLeads } from "@/hooks/useLeads";

export default function DashboardContent() {
  const { leadsQuery, statsQuery } = useLeads();

  const leads = leadsQuery.data?.leads ?? [];
  const stats = statsQuery.data;
  const error = leadsQuery.error ? "Could not reach the API. Make sure apps/api is running on port 8000." : null;

  const pendingLeadIds = leads
    .filter((lead) => ["pending", "queued"].includes(lead.status))
    .map((lead) => lead.id);

  const failedCount = leads.filter((lead) => lead.status === "failed").length;

  const completed = stats?.completed ?? 0;
  const total = stats?.total ?? 0;
  const running = stats?.running ?? 0;

  return (
    <>
      {stats && total > 0 && (
        <div className="mb-6 space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {[
              { label: "Total", value: stats.total },
              { label: "Queued", value: stats.queued },
              { label: "Running", value: stats.running },
              { label: "Completed", value: stats.completed },
              { label: "Failed", value: stats.failed },
              { label: "Success", value: `${stats.success_pct}%` },
            ].map((item) => (
              <div
                key={item.label}
                className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-center shadow-sm"
              >
                <p className="text-xs text-gray-500">{item.label}</p>
                <p className="text-lg font-semibold text-gray-900">{item.value}</p>
              </div>
            ))}
          </div>
          {(running > 0 || stats.queued > 0) && (
            <ProgressBar
              completed={completed}
              total={total}
              label={running > 0 ? "Processing leads…" : "Queued"}
            />
          )}
        </div>
      )}

      <div className="mb-6">
        <DashboardActions pendingLeadIds={pendingLeadIds} failedCount={failedCount} />
      </div>

      {leadsQuery.isLoading ? (
        <div className="animate-pulse rounded-lg border border-gray-200 bg-white p-8 text-center text-sm text-gray-500">
          Loading leads…
        </div>
      ) : error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-red-700">
          {error}
        </div>
      ) : (
        <LeadsTable leads={leads} />
      )}
    </>
  );
}
