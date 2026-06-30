"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { ConfidenceBadge, StatusBadge } from "@/components/Badge";
import CopyButton from "@/components/CopyButton";
import ScoreBar, { scoreColor } from "@/components/ScoreBar";
import { fetchLead } from "@/lib/api";
import { leadKeys } from "@/lib/query-keys";

interface LeadDetailContentProps {
  id: string;
}

export default function LeadDetailContent({ id }: LeadDetailContentProps) {
  const { data: lead, isLoading, isError } = useQuery({
    queryKey: leadKeys.detail(id),
    queryFn: () => fetchLead(id),
  });

  if (isLoading) {
    return (
      <div className="animate-pulse rounded-lg border border-gray-200 bg-white p-8 text-center text-sm text-gray-500">
        Loading lead details…
      </div>
    );
  }

  if (isError || !lead) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-red-700">
        Could not load lead details.
      </div>
    );
  }

  return (
    <>
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight text-gray-900">
          {lead.name}
        </h1>
        <p className="mt-1 text-lg text-gray-600">{lead.company}</p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <StatusBadge label={lead.status} />
          {lead.email && (
            <span className="text-sm text-gray-500">{lead.email}</span>
          )}
        </div>
      </div>

      <section className="mb-8 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-lg font-semibold text-gray-900">ICP Score</h2>
        <ScoreBar score={lead.icp_score} />
        {lead.icp_criteria.length > 0 ? (
          <div className="mt-6 space-y-4">
            {lead.icp_criteria.map((criterion) => (
              <div
                key={criterion.criterion}
                className="rounded-md border border-gray-100 bg-gray-50 p-4"
              >
                <div className="flex items-center justify-between gap-4">
                  <h3 className="text-sm font-medium capitalize text-gray-900">
                    {criterion.criterion.replace(/_/g, " ")}
                  </h3>
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-24 overflow-hidden rounded-full bg-gray-200">
                      <div
                        className={`h-full rounded-full ${scoreColor(criterion.score)}`}
                        style={{ width: `${Math.min(100, criterion.score)}%` }}
                      />
                    </div>
                    <span className="text-xs font-medium text-gray-600">
                      {criterion.score}
                    </span>
                  </div>
                </div>
                <p className="mt-2 text-sm text-gray-600">{criterion.reasoning}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-4 text-sm text-gray-500">No ICP breakdown available yet.</p>
        )}
      </section>

      <section className="mb-8 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-lg font-semibold text-gray-900">Enriched Profile</h2>
        {lead.enrichment_fields.length > 0 ? (
          <ul className="divide-y divide-gray-100">
            {lead.enrichment_fields.map((field) => (
              <li key={field.id} className="flex items-start justify-between gap-4 py-3">
                <div>
                  <p className="text-sm font-medium capitalize text-gray-900">
                    {field.field_name.replace(/_/g, " ")}
                  </p>
                  <p className="mt-1 text-sm text-gray-600">{field.value}</p>
                  <p className="mt-1 text-xs text-gray-400">Source: {field.source}</p>
                </div>
                <ConfidenceBadge confidence={field.confidence} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-gray-500">No enrichment data yet.</p>
        )}
      </section>

      <section className="mb-8 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-lg font-semibold text-gray-900">Buying Signals</h2>
        {lead.buying_signals.length > 0 ? (
          <div className="space-y-4">
            {lead.buying_signals.map((signal) => (
              <div
                key={signal.id}
                className="rounded-md border border-gray-100 bg-gray-50 p-4"
              >
                <p className="text-sm font-medium text-gray-900">{signal.signal}</p>
                <p className="mt-1 text-sm text-gray-600">{signal.evidence}</p>
                <p className="mt-1 text-xs text-gray-400">Source: {signal.source}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-500">No buying signals detected.</p>
        )}
      </section>

      <section className="mb-8 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-lg font-semibold text-gray-900">Outreach Drafts</h2>
        {lead.outreach_drafts.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2">
            {lead.outreach_drafts.map((draft) => {
              const fullText = `Subject: ${draft.subject}\n\n${draft.body}\n\n${draft.cta}`;
              return (
                <div key={draft.id} className="rounded-md border border-gray-200 p-4">
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <span className="text-xs font-medium capitalize text-gray-500">
                      {draft.tone}
                    </span>
                    <CopyButton text={fullText} />
                  </div>
                  <p className="text-sm font-semibold text-gray-900">{draft.subject}</p>
                  <p className="mt-3 whitespace-pre-wrap text-sm text-gray-600">
                    {draft.body}
                  </p>
                  <p className="mt-3 text-sm font-medium text-blue-700">{draft.cta}</p>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-gray-500">
            No drafts generated. Lead may not have qualified (ICP score &gt; threshold).
          </p>
        )}
      </section>

      <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-lg font-semibold text-gray-900">CRM Sync</h2>
        {lead.crm_sync_status || lead.crm_status ? (
          <div className="space-y-2">
            <StatusBadge
              label={lead.crm_sync_status?.status ?? lead.crm_status ?? "pending"}
            />
            {(lead.notion_page_id || lead.crm_sync_status?.notion_page_id) && (
              <p className="text-sm text-gray-600">
                Notion page:{" "}
                <code className="text-xs">
                  {lead.notion_page_id ?? lead.crm_sync_status?.notion_page_id}
                </code>
              </p>
            )}
            {lead.crm_sync_status?.error_message && (
              <p className="text-sm text-red-600">{lead.crm_sync_status.error_message}</p>
            )}
          </div>
        ) : (
          <p className="text-sm text-gray-500">Not synced to Notion yet.</p>
        )}
      </section>
    </>
  );
}
