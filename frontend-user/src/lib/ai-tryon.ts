"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, apiRequest } from "./api";
import type { Garment } from "./tryon";

/** Backend: apps/virtual_tryon (AiStatusView, AiSessionViewSet, SavedLookViewSet). */
const BASE = "/virtual-tryon";

export interface AiStatus {
  /** The server has a Decart or OpenAI key; false = the feature is honestly unavailable. */
  enabled: boolean;
  /** realtime = Decart WebRTC live video; snapshot = OpenAI camera snapshot try-on. */
  mode?: "realtime" | "snapshot";
  model: string;
  /** True = active Premium subscription (clean download); false = download with MarosimGo logo watermark. */
  is_premium?: boolean;
  /** This month's AI try-on quota: video is Premium only, photos are 3 a month for free. */
  quota?: { video_limit: number; video_left: number; photo_limit: number; photo_left: number };
  max_session_seconds: number;
  seconds_left_today: number;
  sessions_left_today: number;
  active_session: string | null;
}

export interface AiRenderResult {
  image: string;
  width: number;
  height: number;
  model: string;
  latency_ms: number;
  garment: string;
  look_id?: string;
  drive_file_id?: string;
  drive_web_url?: string;
}

const VIDEO_JOB_POLL_MS = 3000;
const VIDEO_JOB_MAX_WAIT_MS = 15 * 60 * 1000;

export type AiVideoJobStatus = "PENDING" | "FINALIZING" | "DONE" | "FAILED";

/** Background video try-on as the server reports it; the result fields are filled once DONE. */
export interface AiRenderVideoJob extends Partial<Omit<AiRenderVideoResult, "status">> {
  job_id: string;
  status: AiVideoJobStatus;
  /** fast pipeline: PHOTO (dressing one frame) → VIDEO (animating it). */
  stage?: "PHOTO" | "VIDEO" | "";
  /** The dressed photo, available while the video is still rendering. */
  preview_url?: string;
  error?: { code: string; message: string };
}

export interface AiRenderVideoResult {
  status?: "DONE";
  job_id?: string;
  look_id: string;
  video_url: string;
  poster_url: string;
  download_url: string;
  width: number;
  height: number;
  frames: number;
  model: string;
  latency_ms: number;
  garment: string;
  drive_file_id?: string;
  drive_web_url?: string;
}

export interface GarmentOrderPayload {
  garment: string;
  look?: string | null;
  size: string;
  color?: string;
  quantity: number;
  customer_name: string;
  customer_phone: string;
  delivery_type: "DELIVERY" | "PICKUP";
  delivery_address?: string;
  payment_method: "CASH" | "CARD";
  notes?: string;
}

export interface GarmentOrder {
  id: string;
  size: string;
  color: string;
  quantity: number;
  unit_price: string;
  total_price: string;
  status: string;
  status_label: string;
  created_at: string;
}

export type AiEndReason =
  | "USER"
  | "EXPIRED"
  | "PAGE_HIDDEN"
  | "CAMERA_ERROR"
  | "NETWORK_ERROR"
  | "PROVIDER_ERROR"
  | "SESSION_LIMIT"
  | "MODERATION"
  | "INSUFFICIENT_CREDITS"
  | "OTHER";

export interface AiSession {
  id: string;
  status: "ACTIVE" | "FINISHED" | "EXPIRED";
  provider_model: string;
  started_at: string;
  expires_at: string;
  seconds_left: number;
  ended_at: string | null;
  end_reason: AiEndReason | "";
  token_count: number;
}

export interface AiToken {
  /** Short-lived Decart client token (ek_...), never the permanent key. */
  api_key: string;
  expires_at: string;
  model: string;
  session_expires_at: string;
}

/** Measured in the browser; numbers only (no frames). Bounds mirror AiMetricsSerializer. */
export interface AiMetrics {
  connect_ms?: number;
  first_frame_ms?: number;
  glass_to_glass_ms?: number;
  fps?: number;
  interruptions?: number;
  generation_seconds?: number;
  garments_tried?: number;
}

export interface SavedLook {
  id: string;
  garment: { id: string; name: string } | null;
  /** Owner-only, permission-checked URL (not under /media/). */
  image: string;
  video?: string | null;
  width: number;
  height: number;
  created_at: string;
}

interface Page<T> {
  count: number;
  results: T[];
}

export const aiApi = {
  status: () => api.get<AiStatus>(`${BASE}/ai/status/`),
  start: () => api.post<AiSession>(`${BASE}/ai-sessions/`, { consent: true }),
  token: (id: string) => api.post<AiToken>(`${BASE}/ai-sessions/${id}/token/`),
  finish: (id: string, reason: AiEndReason, metrics: AiMetrics) =>
    api.post<AiSession>(`${BASE}/ai-sessions/${id}/finish/`, { reason, metrics }),
  saveLook: (image: Blob, garment: string | null, session: string | null) => {
    const form = new FormData();
    form.append("image", image, "look.jpg");
    if (garment) form.append("garment", garment);
    if (session) form.append("session", session);
    return apiRequest<SavedLook>(`${BASE}/looks/`, { method: "POST", body: form });
  },
  render: (photo: Blob, garment: string) => {
    const form = new FormData();
    form.append("photo", photo, "camera.jpg");
    form.append("garment", garment);
    return apiRequest<AiRenderResult>(`${BASE}/ai/render/`, { method: "POST", body: form });
  },
  /**
   * Uploads the clip and resolves with the finished video. With fal.ai the server answers at once
   * with a background job (the render takes minutes); this polls it until it is DONE or FAILED.
   * A dropped poll is retried, never resubmitted, so one try-on is billed only once.
   */
  renderVideo: async (
    video: Blob,
    garment: string,
    onProgress?: (job: AiRenderVideoJob) => void,
  ): Promise<AiRenderVideoResult> => {
    const form = new FormData();
    const ext = video.type.includes("mp4") ? "mp4" : "webm";
    form.append("video", video, `camera.${ext}`);
    form.append("garment", garment);
    let job = await apiRequest<AiRenderVideoJob>(`${BASE}/ai/render-video/`, { method: "POST", body: form });
    const deadline = Date.now() + VIDEO_JOB_MAX_WAIT_MS;
    onProgress?.(job);
    while (job.status !== "DONE") {
      if (job.status === "FAILED") {
        throw new ApiError(502, job.error?.code ?? "provider_unavailable", job.error?.message ?? "AI video tayyorlanmadi.");
      }
      if (Date.now() > deadline) {
        throw new ApiError(
          504,
          "provider_timeout",
          "Video hali tayyorlanmoqda. U tayyor bo'lgach \"Saqlangan obrazlar\" bo'limida paydo bo'ladi.",
        );
      }
      await new Promise((r) => setTimeout(r, VIDEO_JOB_POLL_MS));
      try {
        job = await apiRequest<AiRenderVideoJob>(`${BASE}/ai/render-video/${job.job_id}/`);
        onProgress?.(job);
      } catch (err) {
        if (err instanceof ApiError && err.status === 0) continue; // network blip: keep polling
        throw err;
      }
    }
    return job as unknown as AiRenderVideoResult;
  },
  downloadUrl: (lookId: string) => `/api/v1${BASE}/looks/${lookId}/download/`,
  createOrder: (payload: GarmentOrderPayload) => api.post<GarmentOrder>(`${BASE}/orders/`, payload),
};

export function useAiStatus() {
  return useQuery({ queryKey: ["tryon", "ai", "status"] as const, queryFn: aiApi.status, staleTime: 0 });
}

/** Garments that have a validated AI reference image, optionally per audience / category. */
export function useAiGarments(category: string | null) {
  return useQuery({
    queryKey: ["tryon", "ai-garments", category] as const,
    queryFn: ({ signal }) =>
      api.get<Page<Garment>>(`${BASE}/garments/`, { ai: 1, category: category ?? undefined, page_size: 100 }, signal),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useSavedLooks() {
  return useQuery({
    queryKey: ["tryon", "looks"] as const,
    queryFn: ({ signal }) => api.get<Page<SavedLook>>(`${BASE}/looks/`, { page_size: 50 }, signal),
  });
}

export function useSaveLook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ image, garment, session }: { image: Blob; garment: string | null; session: string | null }) =>
      aiApi.saveLook(image, garment, session),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tryon", "looks"] }),
  });
}

export function useDeleteLook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`${BASE}/looks/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tryon", "looks"] }),
  });
}

export function useCreateGarmentOrder() {
  return useMutation({
    mutationFn: (payload: GarmentOrderPayload) => aiApi.createOrder(payload),
  });
}
