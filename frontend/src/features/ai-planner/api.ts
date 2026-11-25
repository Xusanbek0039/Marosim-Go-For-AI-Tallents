"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { Paginated } from "@/lib/api/types";

/** Backend: apps/event_planner/admin_views.py (`/api/v1/admin/ai-planner/…`). */
const BASE = "/admin/ai-planner";

export interface Bucket {
  period?: string;
  requests: number;
  success: number;
  fallback: number;
  errors: number;
  blocked: number;
  /** null = the provider reported no usage for this period (never estimated). */
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost_usd: string | null;
}

export interface AiDashboard {
  status: {
    enabled: boolean;
    maintenance_mode: boolean;
    provider: string;
    model_name: string;
    provider_configured: boolean;
    features: Record<string, boolean>;
  };
  today: Bucket & { users: number; active_conversations: number; plans_created: number; estimates_created: number };
  totals: { plans: number; conversations: number; open_reports: number };
  daily: Bucket[];
  weekly: Bucket[];
  monthly: Bucket[];
  top_errors: { error_code: string; n: number }[];
}

export interface UsageLog {
  id: number;
  provider: string;
  model_name: string;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost_usd: string | null;
  latency_ms: number | null;
  status: "SUCCESS" | "FALLBACK" | "ERROR" | "BLOCKED";
  error_code: string;
  created_at: string;
}

export interface MaskedUser {
  id: string;
  label: string;
  phone_masked: string | null;
}

export type ReportStatus = "OPEN" | "IN_REVIEW" | "RESOLVED" | "REJECTED";

export interface AiReport {
  id: string;
  reporter: MaskedUser | null;
  message: string;
  conversation: string;
  message_excerpt: string;
  reason: string;
  description: string;
  status: ReportStatus;
  assigned_admin: string | null;
  assigned_admin_label: string | null;
  resolution: string;
  resolved_at: string | null;
  created_at: string;
}

export interface AdminConversation {
  id: string;
  user: MaskedUser | null;
  title: string;
  status: string;
  message_count: number;
  last_message_at: string | null;
  created_at: string;
}

export interface AdminMessage {
  id: string;
  role: string;
  content: string;
  status: string;
  error_code: string;
  feedback: string;
  model_name: string;
  token_usage: Record<string, number>;
  validation_notes: string[];
  created_at: string;
}

export interface AiConfig {
  provider: "anthropic";
  model_name: string;
  enabled: boolean;
  maintenance_mode: boolean;
  maintenance_message: string;
  effort: "low" | "medium" | "high";
  temperature: string | null;
  max_tokens: number;
  history_limit: number;
  max_input_chars: number;
  daily_messages_per_user: number;
  daily_messages_global: number;
  monthly_token_budget: number;
  feature_flags: Record<"chat" | "recommendations" | "booking_handoff", boolean>;
  version: number;
  provider_configured: boolean;
  key_source: string;
  updated_by_label: string | null;
  updated_at: string;
}

export interface PromptVersion {
  id: string;
  number: number;
  title: string;
  system_prompt: string;
  status: "DRAFT" | "TESTED" | "ACTIVE" | "ARCHIVED";
  notes: string;
  created_by_label: string | null;
  tested_at: string | null;
  test_result: { ok?: boolean; live?: boolean; code?: string | null; sample_reply?: string; checked_at?: string };
  activated_by_label: string | null;
  activated_at: string | null;
  created_at: string;
}

export interface AuditEntry {
  id: string;
  actor_label: string;
  action: string;
  target_type: string;
  target_id: string;
  target_label: string;
  changes: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
}

const keys = {
  all: ["admin-ai"] as const,
  dashboard: (days: number) => ["admin-ai", "dashboard", days] as const,
  list: (name: string, params: object) => ["admin-ai", name, params] as const,
  conversation: (id: string) => ["admin-ai", "conversation", id] as const,
  config: ["admin-ai", "config"] as const,
};

export function useAiDashboard(days: number) {
  return useQuery({ queryKey: keys.dashboard(days), queryFn: () => api.get<AiDashboard>(`${BASE}/dashboard/`, { days }) });
}

function useList<T>(name: string, params: Record<string, string | number | undefined>, enabled = true) {
  return useQuery({
    queryKey: keys.list(name, params),
    queryFn: ({ signal }) => api.get<Paginated<T>>(`${BASE}/${name}/`, params, signal),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export const useUsageLogs = (p: Record<string, string | number | undefined>) => useList<UsageLog>("usage", p);
export const useAiReports = (p: Record<string, string | number | undefined>) => useList<AiReport>("reports", p);
export const useAdminConversations = (p: Record<string, string | number | undefined>) => useList<AdminConversation>("conversations", p);
export const usePrompts = () => useList<PromptVersion>("prompts", { page_size: 50 });
export const useAiAudit = (p: Record<string, string | number | undefined>) => useList<AuditEntry>("audit", p);

/** Every open of a conversation is written to the audit log by the server. */
export function useAdminConversation(id: string | null) {
  return useQuery({
    queryKey: keys.conversation(id ?? ""),
    queryFn: () => api.get<AdminConversation & { messages: AdminMessage[] }>(`${BASE}/conversations/${id}/`),
    enabled: Boolean(id),
    staleTime: Infinity,
  });
}

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: keys.all });
}

export function useUpdateReport() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: { status?: ReportStatus; resolution?: string; assign_to_me?: boolean } }) =>
      api.patch<AiReport>(`${BASE}/reports/${id}/`, body),
    onSuccess: invalidate,
  });
}

export function useDisableAi() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { scope: string; reason: string }) => api.post<AiConfig>(`${BASE}/disable/`, { ...body, confirm: true }),
    onSuccess: invalidate,
  });
}

export function useAiConfig(enabled: boolean) {
  return useQuery({ queryKey: keys.config, queryFn: () => api.get<AiConfig>(`${BASE}/config/`), enabled });
}

export function useUpdateAiConfig() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: Partial<AiConfig> & { expected_version: number; confirm?: boolean }) => api.patch<AiConfig>(`${BASE}/config/`, body),
    onSuccess: invalidate,
  });
}

export function useValidateAiConfig() {
  return useMutation({
    mutationFn: () => api.post<{ ok: boolean; code: string | null; message: string; model_name: string }>(`${BASE}/config/validate/`),
  });
}

export function useSavePrompt() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, body }: { id?: string; body: { title: string; system_prompt: string; notes: string } }) =>
      id ? api.patch<PromptVersion>(`${BASE}/prompts/${id}/`, body) : api.post<PromptVersion>(`${BASE}/prompts/`, body),
    onSuccess: invalidate,
  });
}

export function usePromptAction() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, action, sample }: { id: string; action: "test" | "activate"; sample?: string }) =>
      api.post<PromptVersion>(
        `${BASE}/prompts/${id}/${action}/`,
        action === "activate" ? { confirm: true } : sample ? { sample_message: sample } : {},
      ),
    onSuccess: invalidate,
  });
}
