const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface CrmSyncStatus {
  id?: number;
  status: string;
  notion_page_id: string | null;
  error_message: string | null;
}

export interface Lead {
  id: number;
  name: string;
  company: string;
  email: string;
  status: string;
  icp_score: number | null;
  top_buying_signal: string | null;
  retry_count?: number;
  error_message?: string | null;
  crm_status?: string | null;
  crm_sync_status: CrmSyncStatus | null;
}

export interface LeadsResponse {
  leads: Lead[];
  page: number;
  page_size: number;
  total: number;
}

export interface Stats {
  total: number;
  queued: number;
  running: number;
  completed: number;
  failed: number;
  success_pct: number;
  eta_seconds: number | null;
}

export interface EnrichmentField {
  id: number;
  field_name: string;
  value: string;
  confidence: string;
  source: string;
}

export interface BuyingSignal {
  id: number;
  signal: string;
  source: string;
  evidence: string;
}

export interface OutreachDraft {
  id: number;
  tone: string;
  subject: string;
  body: string;
  cta: string;
}

export interface IcpCriterion {
  criterion: string;
  score: number;
  reasoning: string;
}

export interface LeadDetail {
  id: number;
  name: string;
  company: string;
  email: string;
  status: string;
  icp_score: number | null;
  icp_criteria: IcpCriterion[];
  retry_count?: number;
  error_message?: string | null;
  processing_time_ms?: number | null;
  crm_status?: string | null;
  notion_page_id?: string | null;
  enrichment_fields: EnrichmentField[];
  buying_signals: BuyingSignal[];
  outreach_drafts: OutreachDraft[];
  crm_sync_status: CrmSyncStatus | null;
}

export interface UploadResult {
  upload_id: string;
  job_id: string;
  records_count: number;
  message: string;
}

async function parseError(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => null);
  const detail = body?.detail;
  return typeof detail === "string" ? detail : fallback;
}

export async function fetchLeads(): Promise<LeadsResponse> {
  const res = await fetch(`${API_URL}/leads`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch leads");
  return res.json();
}

export async function fetchStats(): Promise<Stats> {
  const res = await fetch(`${API_URL}/stats`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch stats");
  return res.json();
}

export async function fetchLead(id: string): Promise<LeadDetail> {
  const res = await fetch(`${API_URL}/leads/${id}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch lead");
  return res.json();
}

export async function uploadCsv(file: File): Promise<UploadResult> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_URL}/upload`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) throw new Error(await parseError(res, "Failed to upload CSV"));
  return res.json();
}

export async function enrichLead(id: number): Promise<{ job_id: string }> {
  const res = await fetch(`${API_URL}/enrich/${id}`, { method: "POST" });
  if (!res.ok) throw new Error(await parseError(res, `Failed to enrich lead ${id}`));
  return res.json();
}

export async function retryLead(id: number): Promise<{ job_id: string }> {
  const res = await fetch(`${API_URL}/leads/${id}/retry`, { method: "POST" });
  if (!res.ok) throw new Error(await parseError(res, `Failed to retry lead ${id}`));
  return res.json();
}

export async function retryFailed(): Promise<{ retried: number }> {
  const res = await fetch(`${API_URL}/retry-failed`, { method: "POST" });
  if (!res.ok) throw new Error(await parseError(res, "Failed to retry failed leads"));
  return res.json();
}

export async function crmSyncLead(id: number): Promise<{ job_id: string }> {
  const res = await fetch(`${API_URL}/crm-sync/${id}`, { method: "POST" });
  if (!res.ok) throw new Error(await parseError(res, `Failed to sync lead ${id}`));
  return res.json();
}

export async function fetchHealth(): Promise<{ notion: { valid: boolean; error?: string } }> {
  const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
  if (!res.ok) throw new Error("API unreachable");
  return res.json();
}
