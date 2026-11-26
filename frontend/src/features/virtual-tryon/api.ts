"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";

export interface AdminTryOnCategory {
  id: string;
  name: string;
  slug: string;
  audience: "MEN" | "WOMEN" | "UNISEX";
}

export interface AdminGarment {
  id: string;
  category: AdminTryOnCategory;
  name: string;
  description: string;
  price: string;
  currency: string;
  sizes: string[];
  colors: { name: string; hex?: string }[];
  cover_image_url: string | null;
  ai_reference_image_url: string | null;
  ai_prompt: string;
  ai_ready: boolean;
  tryon_ready: boolean;
  is_active: boolean;
  approval_status: "DRAFT" | "PENDING" | "APPROVED" | "REJECTED";
  rejection_reason: string;
  created_at: string;
  updated_at: string;
}

export interface AdminSavedLook {
  id: string;
  user: {
    id: string;
    full_name: string;
    phone_number: string | null;
    email: string | null;
  };
  garment: {
    id: string;
    name: string;
    category_name: string;
    cover_image: string | null;
  } | null;
  image: string;
  width: number;
  height: number;
  drive_file_id: string;
  drive_web_url: string;
  created_at: string;
}

interface Page<T> {
  count: number;
  results: T[];
}

export const tryonKeys = {
  looks: (q?: string) => ["admin-tryon", "looks", q ?? ""] as const,
  garments: (q?: string) => ["admin-tryon", "garments", q ?? ""] as const,
  categories: ["admin-tryon", "categories"] as const,
};

export function useAdminLooks(q?: string) {
  return useQuery({
    queryKey: tryonKeys.looks(q),
    queryFn: ({ signal }) =>
      api.get<Page<AdminSavedLook>>("/admin/virtual-tryon/looks/", { q: q || undefined, page_size: 60 }, signal),
  });
}

export function useSyncLookToDrive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<AdminSavedLook>(`/admin/virtual-tryon/looks/${id}/sync-drive/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-tryon", "looks"] }),
  });
}

export function useAdminGarments(q?: string) {
  return useQuery({
    queryKey: tryonKeys.garments(q),
    queryFn: ({ signal }) =>
      api.get<Page<AdminGarment>>("/admin/virtual-tryon/garments/", { q: q || undefined, page_size: 100 }, signal),
  });
}

export function useAdminCategories() {
  return useQuery({
    queryKey: tryonKeys.categories,
    queryFn: ({ signal }) => api.get<AdminTryOnCategory[]>("/admin/virtual-tryon/categories/", undefined, signal),
    staleTime: 5 * 60_000,
  });
}

export interface CreateGarmentInput {
  name: string;
  category_id: string;
  price: string;
  description: string;
  ai_prompt: string;
  photo: File;
  autoApprove: boolean;
}

export function useCreateGarmentWithPhoto() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: CreateGarmentInput) => {
      const created = await api.post<AdminGarment>("/admin/virtual-tryon/garments/", {
        name: input.name,
        category_id: input.category_id,
        price: input.price || "0",
        description: input.description,
        is_tryon_enabled: true,
        is_active: true,
      });
      const form = new FormData();
      form.append("image", input.photo);
      if (input.ai_prompt.trim()) {
        form.append("prompt", input.ai_prompt.trim());
      }
      let updated = await api.post<AdminGarment>(`/admin/virtual-tryon/garments/${created.id}/ai-reference/`, form);
      if (input.autoApprove) {
        updated = await api.post<AdminGarment>(`/admin/virtual-tryon/garments/${created.id}/approve/`);
      }
      return updated;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-tryon", "garments"] }),
  });
}

export function useApproveGarment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<AdminGarment>(`/admin/virtual-tryon/garments/${id}/approve/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-tryon", "garments"] }),
  });
}

export function useDeleteGarment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/admin/virtual-tryon/garments/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-tryon", "garments"] }),
  });
}
