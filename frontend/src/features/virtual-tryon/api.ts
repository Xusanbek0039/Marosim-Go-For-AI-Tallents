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
  brand: string;
  material: string;
  stock_quantity: number;
  delivery_days: number;
  care_instructions: string;
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

export interface AdminGarmentOrder {
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
    brand: string;
    material: string;
    category_name: string;
    cover_image: string | null;
  };
  look: string | null;
  look_image: string | null;
  look_drive_url: string;
  size: string;
  color: string;
  quantity: number;
  unit_price: string;
  total_price: string;
  currency: string;
  customer_name: string;
  customer_phone: string;
  delivery_type: "DELIVERY" | "PICKUP";
  delivery_type_label: string;
  delivery_address: string;
  payment_method: "CASH" | "CARD";
  payment_method_label: string;
  notes: string;
  status: "NEW" | "CONFIRMED" | "PREPARING" | "SHIPPED" | "DELIVERED" | "CANCELLED";
  status_label: string;
  created_at: string;
}

interface Page<T> {
  count: number;
  results: T[];
}

export const tryonKeys = {
  looks: (q?: string) => ["admin-tryon", "looks", q ?? ""] as const,
  garments: (q?: string) => ["admin-tryon", "garments", q ?? ""] as const,
  orders: (status?: string, q?: string) => ["admin-tryon", "orders", status ?? "", q ?? ""] as const,
  categories: ["admin-tryon", "categories"] as const,
};

export function useAdminOrders(status?: string, q?: string) {
  return useQuery({
    queryKey: tryonKeys.orders(status, q),
    queryFn: ({ signal }) =>
      api.get<Page<AdminGarmentOrder>>(
        "/admin/virtual-tryon/orders/",
        { status: status || undefined, q: q || undefined, page_size: 60 },
        signal,
      ),
  });
}

export function useUpdateOrderStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: AdminGarmentOrder["status"] }) =>
      api.patch<AdminGarmentOrder>(`/admin/virtual-tryon/orders/${id}/`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-tryon", "orders"] }),
  });
}

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
  brand: string;
  material: string;
  sizes: string[];
  colors: { name: string }[];
  stock_quantity: number;
  delivery_days: number;
  care_instructions: string;
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
        brand: input.brand,
        material: input.material,
        sizes: input.sizes,
        colors: input.colors,
        stock_quantity: input.stock_quantity,
        delivery_days: input.delivery_days,
        care_instructions: input.care_instructions,
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
