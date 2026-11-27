"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { Paginated } from "@/lib/api/types";

export type BackupStatus = "NO_VIDEO" | "TRIAL" | "PREMIUM" | "BACKUP";

export const STATUS: Record<BackupStatus, { label: string; className: string }> = {
  TRIAL: { label: "Bepul muddatda", className: "bg-sky-500/15 text-sky-700 dark:text-sky-300" },
  PREMIUM: { label: "Premium", className: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" },
  BACKUP: { label: "Backupda", className: "bg-red-500/15 text-red-700 dark:text-red-300" },
  NO_VIDEO: { label: "Video yo'q", className: "bg-slate-500/15 text-slate-600 dark:text-slate-300" },
};

export const REASON: Record<string, string> = {
  FIRST_VIDEO: "birinchi videodan",
  PREMIUM_ENDED: "Premium tugaganidan",
  ADMIN: "admin belgilagan",
};

export interface BackupRow {
  id: string;
  full_name: string;
  phone_number: string | null;
  status: BackupStatus;
  first_video_at: string | null;
  grace_started_at: string | null;
  grace_ends_at: string | null;
  grace_reason: string;
  backup_since: string | null;
  premium_until: string | null;
  ceremonies: number;
  videos: number;
  media_bytes: number;
}

export interface BackupDetail extends BackupRow {
  ceremony_list: { id: string; title: string; event_date: string | null; media_count: number; video_count: number }[];
}

export interface BackupMedia {
  id: string;
  kind: "PHOTO" | "VIDEO";
  mime_type: string;
  size_bytes: number;
  completed_at: string | null;
}

const keys = { all: ["backup"] as const };

export function useBackupList(params: { status?: string; search?: string; page?: number }) {
  return useQuery({
    queryKey: [...keys.all, "list", params],
    queryFn: () => api.get<Paginated<BackupRow>>("/admin/backup/", { ...params, page_size: 50 }),
    refetchInterval: 30_000, // the state is always current in the panel
  });
}

export function useBackupSummary() {
  return useQuery({
    queryKey: [...keys.all, "summary"],
    queryFn: () => api.get<Record<BackupStatus, number>>("/admin/backup/summary/"),
    refetchInterval: 30_000,
  });
}

export function useBackupDetail(id: string | null) {
  return useQuery({
    queryKey: [...keys.all, "detail", id],
    queryFn: () => api.get<BackupDetail>(`/admin/backup/${id}/`),
    enabled: Boolean(id),
  });
}

export function useBackupMedia(ceremonyId: string | null) {
  return useQuery({
    queryKey: [...keys.all, "media", ceremonyId],
    queryFn: () => api.get<BackupMedia[]>(`/admin/backup/ceremonies/${ceremonyId}/media/`),
    enabled: Boolean(ceremonyId),
  });
}

export const mediaUrl = (ceremonyId: string, mediaId: string, action: "thumbnail" | "stream" | "download", size = 480) =>
  `/api/v1/admin/backup/ceremonies/${ceremonyId}/media/${mediaId}/${action}/${action === "thumbnail" ? `?size=${size}` : ""}`;

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: keys.all });
}

export function useBackupAction() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, kind, body }: { id: string; kind: "backup" | "release" | "extend-premium"; body: Record<string, unknown> }) =>
      api.post<BackupRow>(`/admin/backup/${id}/${kind}/`, body),
    onSuccess: invalidate,
  });
}

export function useSyncAll() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: () => api.post<Record<BackupStatus, number>>("/admin/backup/sync/"), onSuccess: invalidate });
}

export function useDeleteBackupMedia(ceremonyId: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (mediaId: string) => api.delete(`/admin/backup/ceremonies/${ceremonyId}/media/${mediaId}/`),
    onSuccess: invalidate,
  });
}
