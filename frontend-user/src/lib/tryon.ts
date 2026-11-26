"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";

export type Audience = "MEN" | "WOMEN" | "UNISEX";

export interface GarmentCategory {
  id: string;
  name: string;
  slug: string;
  audience: Audience;
  sort_order: number;
  garment_count: number;
}

export interface Garment {
  id: string;
  category: { id: string; name: string; slug: string; audience: Audience };
  name: string;
  description: string;
  price: string;
  currency: string;
  sizes: string[];
  colors: { name: string; hex?: string }[];
  brand?: string;
  material?: string;
  stock_quantity?: number;
  delivery_days?: number;
  care_instructions?: string;
  cover_image: string | null;
  asset_type: "LAYERED_2D" | "MODEL_3D";
  /** Can be worn on camera (enabled + has the BODY_FRONT layer). */
  tryon_ready: boolean;
  /** Has a validated reference image for the AI (Decart) try-on. */
  ai_ready: boolean;
  ai_reference_image: string | null;
  ai_prompt: string;
  is_favorite: boolean;
  studio_name: string | null;
  updated_at: string;
}

export type AssetKind =
  | "BODY_FRONT"
  | "BODY_BACK"
  | "LOWER_BODY"
  | "RIGHT_UPPER_ARM"
  | "RIGHT_FOREARM"
  | "LEFT_UPPER_ARM"
  | "LEFT_FOREARM"
  | "MODEL_GLB";

export interface GarmentAsset {
  id: string;
  kind: AssetKind;
  url: string;
  width: number;
  height: number;
  size_bytes: number;
  anchors: Record<string, unknown>;
  updated_at: string;
}

interface Page<T> {
  count: number;
  page: number;
  total_pages: number;
  results: T[];
}

export interface Favorite {
  id: string;
  garment: Garment;
  created_at: string;
}

const BASE = "/virtual-tryon";

export function useGarmentCategories() {
  return useQuery({
    queryKey: ["tryon", "categories"] as const,
    queryFn: ({ signal }) => api.get<GarmentCategory[]>(`${BASE}/categories/`, undefined, signal),
    staleTime: 5 * 60_000,
  });
}

export function useGarments(category: string | null) {
  return useQuery({
    queryKey: ["tryon", "garments", category] as const,
    queryFn: ({ signal }) =>
      api.get<Page<Garment>>(`${BASE}/garments/`, { category: category ?? undefined, page_size: 100 }, signal),
    enabled: category !== null,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

/** The layers the camera renderer needs. Cached for the session: assets change only on re-upload. */
export function fetchGarmentAssets(id: string, signal?: AbortSignal) {
  return api.get<GarmentAsset[]>(`${BASE}/garments/${id}/assets/`, undefined, signal);
}

export function useFavorites() {
  return useQuery({
    queryKey: ["tryon", "favorites"] as const,
    queryFn: ({ signal }) => api.get<Page<Favorite>>(`${BASE}/favorites/`, { page_size: 100 }, signal),
  });
}

export function useToggleFavorite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ garment, favorite }: { garment: string; favorite: boolean }): Promise<void> => {
      if (favorite) await api.post<Favorite>(`${BASE}/favorites/`, { garment });
      else await api.delete(`${BASE}/favorites/${garment}/`);
    },
    onMutate: async ({ garment, favorite }) => {
      // Optimistic: flip the heart in every cached garment list right away.
      await qc.cancelQueries({ queryKey: ["tryon", "garments"] });
      qc.setQueriesData<Page<Garment>>({ queryKey: ["tryon", "garments"] }, (old) =>
        old ? { ...old, results: old.results.map((g) => (g.id === garment ? { ...g, is_favorite: favorite } : g)) } : old,
      );
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["tryon", "garments"] });
      qc.invalidateQueries({ queryKey: ["tryon", "favorites"] });
    },
  });
}

interface Session {
  id: string;
}

/** Try-on statistics only (which garment, how long). Never carries camera data. */
export const tryonSessions = {
  start: (garment: string) => api.post<Session>(`${BASE}/sessions/`, { garment }),
  finish: (id: string) => api.post<Session>(`${BASE}/sessions/${id}/finish/`),
};
