"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { fetchLeads, fetchStats, type Lead } from "@/lib/api";
import { leadKeys } from "@/lib/query-keys";
import { subscribeToEvents } from "@/lib/sse";

export function useLeads() {
  const queryClient = useQueryClient();

  const leadsQuery = useQuery({
    queryKey: leadKeys.all,
    queryFn: fetchLeads,
  });

  const statsQuery = useQuery({
    queryKey: leadKeys.stats,
    queryFn: fetchStats,
    refetchInterval: 10000,
  });

  useEffect(() => {
    return subscribeToEvents((event) => {
      if (event.type === "lead_updated" && event.data) {
        queryClient.setQueryData(leadKeys.all, (old: { leads: Lead[] } | undefined) => {
          if (!old) return old;
          const updated = event.data as unknown as Lead;
          const leads = old.leads.map((l) => (l.id === updated.id ? { ...l, ...updated } : l));
          if (!leads.find((l) => l.id === updated.id)) {
            leads.unshift(updated);
          }
          return { ...old, leads };
        });
        queryClient.invalidateQueries({ queryKey: leadKeys.stats });
      }
      if (event.type === "stats_updated" || event.type === "job_updated" || event.type === "upload_started") {
        queryClient.invalidateQueries({ queryKey: leadKeys.all });
        queryClient.invalidateQueries({ queryKey: leadKeys.stats });
      }
    });
  }, [queryClient]);

  return { leadsQuery, statsQuery };
}
