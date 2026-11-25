"use client";

import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";
import type { BookingEventType, Region } from "./venues";

/** Backend: apps/event_planner (views.py). Every number below is computed by the server. */
const BASE = "/ai-planner";

// -------------------------------------------------------------------- types
export type EventType = "TOY" | "NIKOH" | "SUNNAT" | "BIRTHDAY" | "ANNIVERSARY" | "CORPORATE" | "OTHER";
export type PlanStyle = "ECONOMY" | "STANDARD" | "PREMIUM" | "CUSTOM";
export type BudgetFlexibility = "FIXED" | "FLEXIBLE";
export type PlanStatus = "DRAFT" | "ACTIVE" | "COMPLETED" | "ARCHIVED";
export type Category =
  | "VENUE"
  | "FOOD"
  | "PHOTO_VIDEO"
  | "HOST_DJ"
  | "ARTISTS"
  | "DECOR"
  | "CAKE_EXTRAS"
  | "TRANSPORT"
  | "INVITATIONS_OTHER"
  | "CONTINGENCY";
export type ItemCategory = Exclude<Category, "CONTINGENCY">;
export type Unit = "EVENT" | "PERSON" | "PIECE" | "HOUR" | "SET" | "SERVICE";
export type SourceType = "PLATFORM_SERVICE" | "USER_INPUT" | "AI_ESTIMATE" | "MANUAL";
export type SourceKind = "" | "VENUE_HALL" | "STUDIO";
export type PriceStatus = "VERIFIED" | "ESTIMATED" | "PENDING";
export type BudgetState = "NO_ITEMS" | "NO_BUDGET" | "WITHIN" | "AT_RISK" | "OVER";

export interface Plan {
  id: string;
  title: string;
  event_type: EventType;
  event_date: string | null;
  date_is_approximate: boolean;
  approximate_date: string;
  region: Region | "";
  district: string;
  guest_count: number | null;
  total_budget: string | null;
  currency: "UZS";
  budget_flexibility: BudgetFlexibility;
  style: PlanStyle;
  priorities: ItemCategory[];
  wishes: string;
  notes: string;
  status: PlanStatus;
  reserve_percent: string;
  source: "MANUAL" | "AI_CONFIRMED";
  item_count: number;
  totals: { total_min: string; total_max: string; status: BudgetState };
  created_at: string;
  updated_at: string;
}

export type PlanInput = Partial<
  Omit<Plan, "id" | "currency" | "source" | "item_count" | "totals" | "created_at" | "updated_at">
> & { client_request_id?: string };

export interface BudgetItem {
  id: string;
  category: ItemCategory;
  title: string;
  quantity: string;
  unit: Unit;
  per_guest: boolean;
  unit_price: string;
  unit_price_max: string | null;
  total_price: string;
  total_price_max: string;
  currency: "UZS";
  source_type: SourceType;
  source_kind: SourceKind;
  source_reference: string;
  price_status: PriceStatus;
  price_checked_at: string | null;
  notes: string;
  is_included_in_package: boolean;
  package_includes: ItemCategory[];
  actual_amount: string | null;
  is_active: boolean;
  position: number;
  created_at: string;
  updated_at: string;
}

export type ItemInput = Partial<
  Pick<
    BudgetItem,
    | "category"
    | "title"
    | "quantity"
    | "unit"
    | "per_guest"
    | "unit_price"
    | "unit_price_max"
    | "source_kind"
    | "source_reference"
    | "notes"
    | "is_included_in_package"
    | "package_includes"
    | "actual_amount"
    | "is_active"
  >
> & { source_type?: Exclude<SourceType, "AI_ESTIMATE">; price_status?: "ESTIMATED" | "PENDING"; client_request_id?: string };

export interface Warning {
  code: string;
  message: string;
  overrun_min?: string;
  overrun_max?: string;
}

export interface CategoryTotal {
  category: Category;
  label: string;
  min: string;
  max: string;
  verified: string;
  estimated: string;
  pending: string;
  actual: string;
  count: number;
}

export interface Summary {
  currency: "UZS";
  guest_count: number | null;
  total_budget: string | null;
  subtotal_min: string;
  subtotal_max: string;
  reserve_percent: string;
  reserve_recommended: [string, string];
  reserve_min: string;
  reserve_max: string;
  total_min: string;
  total_max: string;
  is_range: boolean;
  remaining_min: string | null;
  remaining_max: string | null;
  status: BudgetState;
  overrun_min: string;
  overrun_max: string;
  by_category: CategoryTotal[];
  by_price_status: { verified: string; estimated: string; pending: string };
  actual_total: string | null;
  biggest_items: { id: string | null; title: string; category: Category; min: string; max: string }[];
  cut_suggestions: { code: string; message: string; item_id?: string | null; saving_min: string }[];
  warnings: Warning[];
}

export interface FreeSession {
  id: string;
  name: string;
  starts_at: string;
  ends_at: string;
}

/** A real hall or studio row, read from the platform database (never written by the AI). */
export interface ServiceRow {
  kind: "VENUE_HALL" | "STUDIO";
  id: string;
  name: string;
  venue_id?: string;
  venue_name?: string;
  hall_name?: string;
  region?: Region;
  region_label?: string;
  district?: string;
  address: string;
  capacity?: number;
  price: string | null;
  price_note: string;
  price_source: "platform" | null;
  price_checked_at: string | null;
  currency: "UZS";
  rating_avg: number | null;
  rating_count: number;
  availability: {
    checked: boolean;
    date: string | null;
    free_sessions?: FreeSession[];
    state?: "UNKNOWN" | "OFF" | "BUSY" | "HAS_EVENTS" | "FREE_ON_CALENDAR";
    events_that_day?: number;
  };
  url: string;
  in_plan?: boolean;
  over_budget?: boolean;
}

export interface Recommendations {
  category: Category;
  results: ServiceRow[];
  date_known: boolean;
  booking_handoff: boolean;
  booking_event_type: BookingEventType;
  note: string | null;
}

export interface Conversation {
  id: string;
  title: string;
  status: "ACTIVE" | "ARCHIVED";
  event_plan: string | null;
  event_plan_title: string | null;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProposedItem {
  category: ItemCategory;
  title: string;
  quantity: string;
  unit: Unit;
  per_guest: boolean;
  unit_price?: string;
  unit_price_max?: string | null;
  service_id: string | null;
  service_kind?: "VENUE_HALL" | "STUDIO";
  is_included_in_package: boolean;
  notes: string;
}

export interface StructuredReply {
  intent?: string;
  language?: string;
  missing_information?: string[];
  next_question?: string | null;
  event_plan?: Partial<Plan> | null;
  budget_items?: ProposedItem[];
  recommendations?: { service_id: string; kind: string; reason: string }[];
  recommended_services?: ServiceRow[];
  budget_preview?: Summary;
  booking_handoff_enabled?: boolean;
  warnings?: string[];
  validation_notes?: string[];
  sensitive_data_removed?: boolean;
  confirmed_plan_id?: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  structured_data: StructuredReply;
  status: "OK" | "FAILED" | "FALLBACK" | "BLOCKED";
  error_code: string;
  feedback: "" | "UP" | "DOWN";
  reply_to: string | null;
  model_name: string;
  token_usage: { input_tokens?: number; output_tokens?: number };
  /** The sender's idempotency key: a failed send keeps the user message, and a retry reuses it. */
  client_request_id: string | null;
  created_at: string;
}

export interface PlannerStatus {
  available: boolean;
  reason: string | null;
  message: string | null;
  features: { chat: boolean; recommendations: boolean; booking_handoff: boolean };
  messages_today: number;
  daily_limit: number | null;
  max_input_chars: number;
}

interface Page<T> {
  count: number;
  page: number;
  total_pages: number;
  next: string | null;
  results: T[];
}

// ------------------------------------------------------------------- queries
export const plannerKeys = {
  all: ["ai-planner"] as const,
  status: ["ai-planner", "status"] as const,
  plans: (status?: string) => ["ai-planner", "plans", status ?? "all"] as const,
  plan: (id: string) => ["ai-planner", "plan", id] as const,
  items: (id: string) => ["ai-planner", "plan", id, "items"] as const,
  summary: (id: string) => ["ai-planner", "plan", id, "summary"] as const,
  recommendations: (id: string, category: string, sort: string) =>
    ["ai-planner", "plan", id, "recommendations", category, sort] as const,
  conversations: ["ai-planner", "conversations"] as const,
  messages: (id: string) => ["ai-planner", "conversation", id, "messages"] as const,
};

export function usePlannerStatus() {
  return useQuery({ queryKey: plannerKeys.status, queryFn: () => api.get<PlannerStatus>(`${BASE}/status/`), staleTime: 0 });
}

export function usePlans(status?: PlanStatus) {
  return useQuery({
    queryKey: plannerKeys.plans(status),
    queryFn: ({ signal }) => api.get<Page<Plan>>(`${BASE}/plans/`, { status, page_size: 50 }, signal),
    placeholderData: keepPreviousData,
  });
}

export function usePlan(id: string) {
  return useQuery({ queryKey: plannerKeys.plan(id), queryFn: () => api.get<Plan>(`${BASE}/plans/${id}/`), enabled: Boolean(id) });
}

export function useItems(planId: string) {
  return useQuery({
    queryKey: plannerKeys.items(planId),
    queryFn: () => api.get<BudgetItem[]>(`${BASE}/plans/${planId}/items/`),
    enabled: Boolean(planId),
  });
}

export function useSummary(planId: string) {
  return useQuery({
    queryKey: plannerKeys.summary(planId),
    queryFn: () => api.get<Summary>(`${BASE}/plans/${planId}/summary/`),
    enabled: Boolean(planId),
  });
}

export function useRecommendations(planId: string, category: "VENUE" | "PHOTO_VIDEO", sort: string) {
  return useQuery({
    queryKey: plannerKeys.recommendations(planId, category, sort),
    queryFn: ({ signal }) =>
      api.get<Recommendations>(`${BASE}/plans/${planId}/recommendations/`, { category, sort }, signal),
    enabled: Boolean(planId),
    placeholderData: keepPreviousData,
  });
}

export function useConversations() {
  return useQuery({
    queryKey: plannerKeys.conversations,
    queryFn: () => api.get<Page<Conversation>>(`${BASE}/conversations/`, { page_size: 50 }),
  });
}

/** Newest page first from the API; the chat shows them oldest → newest. */
export function useMessages(conversationId: string | null) {
  return useInfiniteQuery({
    queryKey: plannerKeys.messages(conversationId ?? ""),
    queryFn: ({ pageParam }) =>
      api.get<Page<Message>>(`${BASE}/conversations/${conversationId}/messages/`, { page: pageParam, page_size: 30 }),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.next ? last.page + 1 : undefined),
    enabled: Boolean(conversationId),
  });
}

/** Invalidate everything that depends on one plan (items, totals, recommendations, lists). */
function useInvalidatePlan() {
  const qc = useQueryClient();
  return (planId?: string) => {
    if (planId) qc.invalidateQueries({ queryKey: plannerKeys.plan(planId) });
    qc.invalidateQueries({ queryKey: ["ai-planner", "plans"] });
  };
}

export function useCreatePlan() {
  const invalidate = useInvalidatePlan();
  return useMutation({
    mutationFn: (body: PlanInput) => api.post<Plan>(`${BASE}/plans/`, body),
    onSuccess: () => invalidate(),
  });
}

export function useUpdatePlan(id: string) {
  const invalidate = useInvalidatePlan();
  return useMutation({
    mutationFn: (body: PlanInput) => api.patch<Plan>(`${BASE}/plans/${id}/`, body),
    onSuccess: () => invalidate(id),
  });
}

export function usePlanAction() {
  const invalidate = useInvalidatePlan();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "archive" | "unarchive" | "duplicate" | "delete" }): Promise<unknown> =>
      action === "delete" ? api.delete(`${BASE}/plans/${id}/`) : api.post<Plan>(`${BASE}/plans/${id}/${action}/`),
    onSuccess: (_data, { id }) => invalidate(id),
  });
}

export function useSaveItem(planId: string) {
  const invalidate = useInvalidatePlan();
  return useMutation({
    mutationFn: ({ id, body }: { id?: string; body: ItemInput }) =>
      id
        ? api.patch<BudgetItem>(`${BASE}/plans/${planId}/items/${id}/`, body)
        : api.post<BudgetItem>(`${BASE}/plans/${planId}/items/`, body),
    onSuccess: () => invalidate(planId),
  });
}

export function useDeleteItem(planId: string) {
  const invalidate = useInvalidatePlan();
  return useMutation({
    mutationFn: (id: string) => api.delete(`${BASE}/plans/${planId}/items/${id}/`),
    onSuccess: () => invalidate(planId),
  });
}

export function useCreateConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title?: string; event_plan?: string | null }) => api.post<Conversation>(`${BASE}/conversations/`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: plannerKeys.conversations }),
  });
}

export function useConversationAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "archive" | "unarchive" | "delete" }): Promise<unknown> =>
      action === "delete" ? api.delete(`${BASE}/conversations/${id}/`) : api.post<Conversation>(`${BASE}/conversations/${id}/${action}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: plannerKeys.conversations }),
  });
}

export interface SendResult {
  user_message: Message;
  assistant_message: Message;
  replayed: boolean;
}

export function useSendMessage(conversationId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { content: string; client_request_id: string }) =>
      api.post<SendResult>(`${BASE}/conversations/${conversationId}/messages/`, body),
    // Awaited, so the sent message disappears from the "pending" slot only once the server copy is shown.
    onSettled: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: plannerKeys.messages(conversationId) }),
        qc.invalidateQueries({ queryKey: plannerKeys.status }),
        qc.invalidateQueries({ queryKey: plannerKeys.conversations }),
      ]),
  });
}

export function useConfirmPlan(conversationId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (message: string) =>
      api.post<{ plan: Plan; created: boolean; notes: string[] }>(`${BASE}/conversations/${conversationId}/confirm-plan/`, { message }),
    onSuccess: () => qc.invalidateQueries({ queryKey: plannerKeys.all }),
  });
}

export function useMessageFeedback(conversationId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, value }: { id: string; value: "" | "UP" | "DOWN" }) => api.post<Message>(`${BASE}/messages/${id}/feedback/`, { value }),
    onSuccess: () => qc.invalidateQueries({ queryKey: plannerKeys.messages(conversationId) }),
  });
}

export function useReportMessage() {
  return useMutation({
    mutationFn: ({ id, reason, description }: { id: string; reason: string; description: string }) =>
      api.post(`${BASE}/messages/${id}/report/`, { reason, description }),
  });
}

export const plannerApi = {
  exportData: () => api.get<unknown>(`${BASE}/export/`),
  deleteData: () => api.post<{ deleted: Record<string, number> }>(`${BASE}/delete-data/`, { confirm: "DELETE" }),
};
