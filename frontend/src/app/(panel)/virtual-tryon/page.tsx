"use client";

import {
  CheckCircle2Icon,
  CloudIcon,
  DownloadIcon,
  ExternalLinkIcon,
  ImagesIcon,
  Loader2Icon,
  PlayIcon,
  PlusIcon,
  SearchIcon,
  ShirtIcon,
  ShoppingBagIcon,
  SparklesIcon,
  Trash2Icon,
  UploadCloudIcon,
  UserIcon,
  VideoIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { toast } from "sonner";

import { EmptyState, ErrorState, GlassCard, PageHeader, RowsSkeleton } from "@/components/common";
import { RequirePermission } from "@/components/layout/require-permission";
import { PageTransition } from "@/components/motion/page-transition";
import { Button } from "@/components/ui/button";
import { useCan, useMe } from "@/features/auth/hooks";
import {
  type AdminGarmentOrder,
  type AdminSavedLook,
  useAdminCategories,
  useAdminGarments,
  useAdminLooks,
  useAdminOrders,
  useApproveGarment,
  useCreateGarmentWithPhoto,
  useDeleteGarment,
  useSyncLookToDrive,
  useUpdateOrderStatus,
} from "@/features/virtual-tryon/api";
import { MarosimVideoPlayer } from "@/features/virtual-tryon/video-player";
import { ApiError } from "@/lib/api/client";
import { formatDateTime, formatPhone } from "@/lib/format";
import { cn } from "@/lib/utils";

type Tab = "looks" | "orders" | "garments";

const SIZE_PRESETS = ["XS", "S", "M", "L", "XL", "XXL", "44", "46", "48", "50", "52", "54"];
const ORDER_STATUSES: { value: AdminGarmentOrder["status"]; label: string }[] = [
  { value: "NEW", label: "Yangi" },
  { value: "CONFIRMED", label: "Tasdiqlangan" },
  { value: "PREPARING", label: "Tayyorlanmoqda" },
  { value: "SHIPPED", label: "Yo'lda" },
  { value: "DELIVERED", label: "Yetkazildi" },
  { value: "CANCELLED", label: "Bekor qilindi" },
];

function formatMoney(raw: string) {
  const n = Number(raw || 0);
  if (!Number.isFinite(n) || n <= 0) return "Narx belgilanmagan";
  return `${Math.round(n).toLocaleString("uz-UZ")} so'm`;
}

function LooksTab() {
  const [search, setSearch] = useState("");
  const [mediaFilter, setMediaFilter] = useState<"all" | "photo" | "video">("all");
  const [preview, setPreview] = useState<AdminSavedLook | null>(null);
  const looks = useAdminLooks(search.trim());
  const syncDrive = useSyncLookToDrive();
  const can = useCan();
  const { data: me } = useMe();
  const canSync = me?.role === "SUPER_ADMIN" || can("tryon.update");

  useEffect(() => {
    if (!preview) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPreview(null);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [preview]);

  const allRows = looks.data?.results ?? [];
  const rows =
    mediaFilter === "all"
      ? allRows
      : mediaFilter === "video"
        ? allRows.filter((r) => Boolean(r.video))
        : allRows.filter((r) => !r.video);

  return (
    <div className="flex flex-col gap-4">
      <GlassCard className="flex flex-wrap items-center justify-between gap-3 p-4">
        <div className="relative min-w-60 flex-1">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Foydalanuvchi ismi, telefoni yoki kiyim nomi..."
            className="h-10 w-full rounded-xl border border-glass-border bg-background/60 pr-3 pl-10 text-sm outline-none focus:border-brand"
          />
        </div>
        <div className="flex items-center gap-1.5">
          {(
            [
              ["all", "Barchasi"],
              ["photo", "Rasmlar"],
              ["video", "Videolar"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setMediaFilter(key)}
              className={cn(
                "rounded-xl px-3 py-1.5 text-xs font-semibold transition",
                mediaFilter === key
                  ? "bg-brand text-white"
                  : "border border-glass-border bg-background/60 text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="text-xs font-semibold text-muted-foreground">
          Jami: {rows.length} ta kiyib ko&apos;rilgan obraz
        </span>
      </GlassCard>

      {looks.isPending ? (
        <GlassCard className="p-4">
          <RowsSkeleton />
        </GlassCard>
      ) : looks.error ? (
        <GlassCard className="p-4">
          <ErrorState error={looks.error} onRetry={() => looks.refetch()} />
        </GlassCard>
      ) : rows.length === 0 ? (
        <GlassCard className="p-6">
          <EmptyState
            title="Hali kiyib ko'rilgan obrazlar yo'q"
            description="Foydalanuvchilar AI Fashion Studio'da kiyim kiyib ko'rganida natijalar avtomatik shu yerda va Google Drive'da ko'rinadi."
          />
        </GlassCard>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {rows.map((look) => (
            <GlassCard key={look.id} className="flex flex-col overflow-hidden p-0">
              <button
                type="button"
                onClick={() => setPreview(look)}
                className="group relative aspect-[3/4] w-full overflow-hidden bg-neutral-950"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={look.image}
                  alt={look.garment?.name ?? "Kiyib ko'rilgan obraz"}
                  loading="lazy"
                  className="h-full w-full object-cover transition duration-300 group-hover:scale-105"
                />
                {look.video && (
                  <>
                    <span className="absolute top-2.5 left-2.5 inline-flex items-center gap-1 rounded-full bg-brand/90 px-2.5 py-1 text-[11px] font-semibold text-white backdrop-blur-md">
                      <VideoIcon className="size-3.5" />
                      Video
                    </span>
                    <span className="pointer-events-none absolute inset-0 flex items-center justify-center">
                      <span className="flex size-12 items-center justify-center rounded-full bg-black/55 text-white backdrop-blur-md transition group-hover:scale-110">
                        <PlayIcon className="ml-0.5 size-5 fill-current" />
                      </span>
                    </span>
                  </>
                )}
                <span className="absolute top-2.5 right-2.5 inline-flex items-center gap-1 rounded-full bg-black/60 px-2.5 py-1 text-[11px] font-semibold text-white backdrop-blur-md">
                  <CloudIcon className="size-3.5" />
                  {look.drive_file_id ? "Google Drive" : "Faqat server"}
                </span>
              </button>

              <div className="flex flex-1 flex-col gap-2.5 p-4">
                <div className="flex items-start gap-2.5">
                  <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-xl bg-brand/10 text-brand">
                    <UserIcon className="size-4" />
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-bold">{look.user.full_name}</p>
                    <p className="truncate text-xs text-muted-foreground tabular-nums">
                      {look.user.phone_number ? formatPhone(look.user.phone_number) : look.user.email || "—"}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2 rounded-xl bg-muted/50 p-2">
                  {look.garment?.cover_image ? (
                    /* eslint-disable-next-line @next/next/no-img-element */
                    <img
                      src={look.garment.cover_image}
                      alt={look.garment.name}
                      className="size-10 shrink-0 rounded-lg bg-white object-contain"
                    />
                  ) : (
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted">
                      <ShirtIcon className="size-4 text-muted-foreground" />
                    </span>
                  )}
                  <div className="min-w-0">
                    <p className="truncate text-xs font-bold">{look.garment?.name ?? "O'chirilgan kiyim"}</p>
                    <p className="truncate text-[11px] text-muted-foreground">
                      {look.garment?.category_name || "—"} · {formatDateTime(look.created_at)}
                    </p>
                  </div>
                </div>

                <div className="mt-auto flex items-center justify-between gap-2 pt-1">
                  {look.drive_web_url ? (
                    <a
                      href={look.drive_web_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-600 hover:underline dark:text-emerald-400"
                    >
                      <CheckCircle2Icon className="size-3.5" />
                      Google Drive&apos;da ochish
                      <ExternalLinkIcon className="size-3" />
                    </a>
                  ) : canSync ? (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={syncDrive.isPending && syncDrive.variables === look.id}
                      onClick={() =>
                        syncDrive.mutate(look.id, {
                          onSuccess: (updated) => {
                            if (updated.drive_file_id) toast.success("Google Drive'ga yuklandi");
                            else toast.error("Google Drive ulanmagan — avval Google Drive bo'limidan ulang.");
                          },
                          onError: (e) => toast.error(e instanceof ApiError ? e.message : "Yuklab bo'lmadi"),
                        })
                      }
                    >
                      {syncDrive.isPending && syncDrive.variables === look.id ? (
                        <Loader2Icon className="size-3.5 animate-spin" />
                      ) : (
                        <UploadCloudIcon className="size-3.5" />
                      )}
                      Drive&apos;ga yuklash
                    </Button>
                  ) : (
                    <span className="text-xs text-muted-foreground">Drive&apos;ga yuklanmagan</span>
                  )}
                </div>
              </div>
            </GlassCard>
          ))}
        </div>
      )}

      {preview &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            className="fixed inset-0 z-[100] flex h-dvh w-screen items-center justify-center bg-black/80 p-3 backdrop-blur-md sm:p-6"
            onClick={() => setPreview(null)}
          >
            <div
              className="glass relative flex max-h-[92dvh] w-full max-w-2xl flex-col overflow-hidden rounded-3xl border border-white/15 bg-neutral-950 text-white shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                type="button"
                onClick={() => setPreview(null)}
                aria-label="Yopish"
                className="absolute top-3 right-3 z-20 inline-flex size-9 items-center justify-center rounded-full bg-black/60 text-white backdrop-blur-md hover:bg-black/85"
              >
                <XIcon className="size-4" />
              </button>
              {preview.video ? (
                <MarosimVideoPlayer
                  src={preview.video}
                  poster={preview.image}
                  title={`${preview.user.full_name} — ${preview.garment?.name ?? ""}`}
                  className="w-full"
                />
              ) : (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img
                  src={preview.image}
                  alt={preview.garment?.name ?? "Obraz"}
                  className="max-h-[72dvh] w-full bg-black object-contain"
                />
              )}
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/10 bg-neutral-950/95 p-4">
                <div>
                  <p className="text-sm font-bold text-white">
                    {preview.user.full_name} — {preview.garment?.name ?? "—"}
                  </p>
                  <p className="text-xs text-white/60">{formatDateTime(preview.created_at)}</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <a
                    href={preview.video ?? preview.image}
                    download={`marosimgo-tryon-${preview.id.slice(0, 8)}.${preview.video ? "mp4" : "jpg"}`}
                    className="brand-gradient inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 text-xs font-semibold text-white shadow hover:brightness-110"
                  >
                    <DownloadIcon className="size-3.5" /> {preview.video ? "Videoni yuklab olish" : "Rasmni yuklab olish"}
                  </a>
                  {preview.drive_web_url && (
                    <a
                      href={preview.drive_web_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-full bg-emerald-600 px-3.5 py-2 text-xs font-semibold text-white hover:bg-emerald-700"
                    >
                      <CloudIcon className="size-3.5" /> Google Drive&apos;da ko&apos;rish
                    </a>
                  )}
                </div>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}

function GarmentsTab() {
  const can = useCan();
  const { data: me } = useMe();
  const isSuper = me?.role === "SUPER_ADMIN";
  const canCreate = isSuper || can("tryon.create");
  const canApprove = isSuper || can("tryon.approve");
  const canDelete = isSuper || can("tryon.delete");

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [brand, setBrand] = useState("");
  const [material, setMaterial] = useState("");
  const [price, setPrice] = useState("");
  const [sizes, setSizes] = useState<string[]>(["S", "M", "L", "XL"]);
  const [colorsText, setColorsText] = useState("");
  const [stockQuantity, setStockQuantity] = useState("10");
  const [deliveryDays, setDeliveryDays] = useState("2");
  const [careInstructions, setCareInstructions] = useState("");
  const [description, setDescription] = useState("");
  const [aiPrompt, setAiPrompt] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);

  const toggleSize = (s: string) =>
    setSizes((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));

  const garments = useAdminGarments();
  const categories = useAdminCategories();
  const createGarment = useCreateGarmentWithPhoto();
  const approveGarment = useApproveGarment();
  const deleteGarment = useDeleteGarment();

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !categoryId || !photo) {
      toast.error("Kiyim nomi, kategoriya va rasm majburiy.");
      return;
    }
    const parsedColors = colorsText
      .split(",")
      .map((c) => c.trim())
      .filter(Boolean)
      .map((c) => ({ name: c }));
    createGarment.mutate(
      {
        name: name.trim(),
        category_id: categoryId,
        price: price.trim() || "0",
        brand: brand.trim(),
        material: material.trim(),
        sizes,
        colors: parsedColors,
        stock_quantity: Math.max(0, Number(stockQuantity) || 0),
        delivery_days: Math.max(1, Number(deliveryDays) || 2),
        care_instructions: careInstructions.trim(),
        description: description.trim(),
        ai_prompt: aiPrompt.trim(),
        photo,
        autoApprove: canApprove,
      },
      {
        onSuccess: () => {
          toast.success(canApprove ? "Kiyim qo'shildi va tasdiqlandi!" : "Kiyim qo'shildi (tasdiqlash kutilmoqda).");
          setName("");
          setBrand("");
          setMaterial("");
          setPrice("");
          setColorsText("");
          setStockQuantity("10");
          setDeliveryDays("2");
          setCareInstructions("");
          setDescription("");
          setAiPrompt("");
          setPhoto(null);
          setShowForm(false);
        },
        onError: (err) => toast.error(err instanceof ApiError ? err.message : "Kiyimni qo'shib bo'lmadi"),
      },
    );
  };

  const rows = garments.data?.results ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Katalogdagi barcha kiyimlar: <strong>{garments.data?.count ?? 0}</strong> ta
        </p>
        {canCreate && (
          <Button onClick={() => setShowForm((v) => !v)}>
            {showForm ? <XIcon className="size-4" /> : <PlusIcon className="size-4" />}
            {showForm ? "Formani yopish" : "Yangi kiyim qo'shish"}
          </Button>
        )}
      </div>

      {showForm && canCreate && (
        <GlassCard className="p-5">
          <form onSubmit={onSubmit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold">Kiyim nomi *</label>
              <input
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Masalan: Oq atlas kelinlik libosi"
                className="h-10 rounded-xl border border-glass-border bg-background/60 px-3 text-sm outline-none focus:border-brand"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold">Kategoriya *</label>
              <select
                required
                value={categoryId}
                onChange={(e) => setCategoryId(e.target.value)}
                className="h-10 rounded-xl border border-glass-border bg-background/60 px-3 text-sm outline-none focus:border-brand"
              >
                <option value="">Kategoriyani tanlang</option>
                {(categories.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold">Brend / Atelye</label>
              <input
                type="text"
                value={brand}
                onChange={(e) => setBrand(e.target.value)}
                placeholder="Masalan: MarosimGo Atelier"
                className="h-10 rounded-xl border border-glass-border bg-background/60 px-3 text-sm outline-none focus:border-brand"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold">Mato turi (material)</label>
              <input
                type="text"
                value={material}
                onChange={(e) => setMaterial(e.target.value)}
                placeholder="Masalan: 100% tabiiy atlas / Italiya jun matosi"
                className="h-10 rounded-xl border border-glass-border bg-background/60 px-3 text-sm outline-none focus:border-brand"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold">Narxi (so&apos;m) *</label>
              <input
                type="number"
                required
                min="0"
                step="1000"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="4500000"
                className="h-10 rounded-xl border border-glass-border bg-background/60 px-3 text-sm outline-none focus:border-brand"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold">Ranglar (vergul bilan)</label>
              <input
                type="text"
                value={colorsText}
                onChange={(e) => setColorsText(e.target.value)}
                placeholder="Masalan: Oq, Qora, To'q ko'k"
                className="h-10 rounded-xl border border-glass-border bg-background/60 px-3 text-sm outline-none focus:border-brand"
              />
            </div>

            <div className="flex flex-col gap-1.5 sm:col-span-2">
              <label className="text-xs font-bold">Mavjud razmerlar</label>
              <div className="flex flex-wrap gap-1.5">
                {SIZE_PRESETS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => toggleSize(s)}
                    className={cn(
                      "rounded-lg px-2.5 py-1 text-xs font-bold transition",
                      sizes.includes(s)
                        ? "bg-blue-600 text-white"
                        : "border border-glass-border bg-background/60 text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold">Ombordagi soni (dona)</label>
              <input
                type="number"
                min="0"
                value={stockQuantity}
                onChange={(e) => setStockQuantity(e.target.value)}
                className="h-10 rounded-xl border border-glass-border bg-background/60 px-3 text-sm outline-none focus:border-brand"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold">Yetkazib berish muddati (kun)</label>
              <input
                type="number"
                min="1"
                value={deliveryDays}
                onChange={(e) => setDeliveryDays(e.target.value)}
                className="h-10 rounded-xl border border-glass-border bg-background/60 px-3 text-sm outline-none focus:border-brand"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold">Parvarishlash yo&apos;riqnomasi</label>
              <input
                type="text"
                value={careInstructions}
                onChange={(e) => setCareInstructions(e.target.value)}
                placeholder="Masalan: Faqat quruq tozalash (ximchistka)"
                className="h-10 rounded-xl border border-glass-border bg-background/60 px-3 text-sm outline-none focus:border-brand"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold">Kiyim rasmi (oq/tekis fonda, odamsiz, ≥512px) *</label>
              <input
                type="file"
                required
                accept="image/jpeg,image/png,image/webp"
                onChange={(e) => setPhoto(e.target.files?.[0] ?? null)}
                className="h-10 rounded-xl border border-glass-border bg-background/60 px-3 py-1.5 text-sm"
              />
            </div>

            <div className="flex flex-col gap-1.5 sm:col-span-2">
              <label className="text-xs font-bold">Tavsif</label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Kiyim haqida qisqacha ma'lumot..."
                className="h-10 rounded-xl border border-glass-border bg-background/60 px-3 text-sm outline-none focus:border-brand"
              />
            </div>

            <div className="flex flex-col gap-1.5 sm:col-span-2">
              <label className="text-xs font-bold">AI tavsifi (ixtiyoriy, inglizcha bo&apos;lsa yanada aniqroq)</label>
              <input
                type="text"
                value={aiPrompt}
                onChange={(e) => setAiPrompt(e.target.value)}
                placeholder="Masalan: a tailored navy blue men's wedding suit jacket and trousers with white shirt"
                className="h-10 rounded-xl border border-glass-border bg-background/60 px-3 text-sm outline-none focus:border-brand"
              />
            </div>

            <div className="flex justify-end gap-2 sm:col-span-2">
              <Button type="button" variant="ghost" onClick={() => setShowForm(false)}>
                Bekor qilish
              </Button>
              <Button type="submit" disabled={createGarment.isPending}>
                {createGarment.isPending && <Loader2Icon className="size-4 animate-spin" />}
                Saqlash va joylash
              </Button>
            </div>
          </form>
        </GlassCard>
      )}

      {garments.isPending ? (
        <GlassCard className="p-4">
          <RowsSkeleton />
        </GlassCard>
      ) : garments.error ? (
        <GlassCard className="p-4">
          <ErrorState error={garments.error} onRetry={() => garments.refetch()} />
        </GlassCard>
      ) : rows.length === 0 ? (
        <GlassCard className="p-6">
          <EmptyState
            title="Hozircha kiyimlar yo'q"
            description="Yuqoridagi «Yangi kiyim qo'shish» tugmasi orqali real kiyim rasmlarini qo'shing."
          />
        </GlassCard>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {rows.map((g) => (
            <GlassCard key={g.id} className="flex flex-col overflow-hidden p-0">
              <div className="relative aspect-[3/4] w-full bg-white">
                {g.cover_image_url || g.ai_reference_image_url ? (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img
                    src={g.cover_image_url ?? g.ai_reference_image_url ?? ""}
                    alt={g.name}
                    loading="lazy"
                    className="h-full w-full object-contain p-3"
                  />
                ) : (
                  <div className="flex h-full items-center justify-center text-muted-foreground">
                    <ShirtIcon className="size-8" />
                  </div>
                )}
                <span
                  className={cn(
                    "absolute top-2 left-2 rounded-full px-2.5 py-0.5 text-[11px] font-bold",
                    g.approval_status === "APPROVED"
                      ? "bg-emerald-500/90 text-white"
                      : g.approval_status === "REJECTED"
                        ? "bg-rose-500/90 text-white"
                        : "bg-amber-500/90 text-white",
                  )}
                >
                  {g.approval_status}
                </span>
                {g.ai_ready && (
                  <span className="absolute top-2 right-2 inline-flex items-center gap-1 rounded-full bg-blue-600/90 px-2 py-0.5 text-[11px] font-bold text-white">
                    <SparklesIcon className="size-3" /> AI
                  </span>
                )}
              </div>
              <div className="flex flex-1 flex-col gap-1.5 p-3.5">
                <p className="line-clamp-1 text-sm font-bold">{g.name}</p>
                <p className="text-xs text-muted-foreground">{g.category?.name}</p>
                <p className="text-xs font-semibold">{formatMoney(g.price)}</p>
                <div className="mt-auto flex items-center justify-end gap-1.5 pt-2">
                  {canApprove && g.approval_status !== "APPROVED" && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={approveGarment.isPending}
                      onClick={() =>
                        approveGarment.mutate(g.id, {
                          onSuccess: () => toast.success("Kiyim tasdiqlandi"),
                          onError: (e) => toast.error(e instanceof ApiError ? e.message : "Tasdiqlab bo'lmadi"),
                        })
                      }
                    >
                      <CheckCircle2Icon className="size-3.5" /> Tasdiqlash
                    </Button>
                  )}
                  {canDelete && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={deleteGarment.isPending}
                      onClick={() =>
                        deleteGarment.mutate(g.id, {
                          onSuccess: () => toast.success("Kiyim o'chirildi"),
                          onError: (e) => toast.error(e instanceof ApiError ? e.message : "O'chirib bo'lmadi"),
                        })
                      }
                    >
                      <Trash2Icon className="size-3.5 text-rose-500" />
                    </Button>
                  )}
                </div>
              </div>
            </GlassCard>
          ))}
        </div>
      )}
    </div>
  );
}

function OrdersTab() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const orders = useAdminOrders(statusFilter, search.trim());
  const updateStatus = useUpdateOrderStatus();
  const can = useCan();
  const { data: me } = useMe();
  const canUpdate = me?.role === "SUPER_ADMIN" || can("tryon.update");

  const rows = orders.data?.results ?? [];

  return (
    <div className="flex flex-col gap-4">
      <GlassCard className="flex flex-wrap items-center gap-3 p-4">
        <div className="relative min-w-56 flex-1">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Mijoz ismi, telefoni, kiyim nomi yoki manzil..."
            className="h-10 w-full rounded-xl border border-glass-border bg-background/60 pr-3 pl-10 text-sm outline-none focus:border-brand"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="h-10 rounded-xl border border-glass-border bg-background/60 px-3 text-sm"
        >
          <option value="">Barcha holatlar</option>
          {ORDER_STATUSES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        <span className="text-xs font-semibold text-muted-foreground">Jami: {orders.data?.count ?? 0} ta buyurtma</span>
      </GlassCard>

      {orders.isPending ? (
        <GlassCard className="p-4">
          <RowsSkeleton />
        </GlassCard>
      ) : orders.error ? (
        <GlassCard className="p-4">
          <ErrorState error={orders.error} onRetry={() => orders.refetch()} />
        </GlassCard>
      ) : rows.length === 0 ? (
        <GlassCard className="p-6">
          <EmptyState
            title="Hali kiyim buyurtmalari yo'q"
            description="Foydalanuvchilar kiyib ko'rganidan so'ng «Sotib olish» orqali buyurtma berganda shu yerda ko'rinadi."
          />
        </GlassCard>
      ) : (
        <div className="flex flex-col gap-3">
          {rows.map((order) => (
            <GlassCard key={order.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start">
              <div className="flex shrink-0 gap-2">
                {order.garment.cover_image && (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img
                    src={order.garment.cover_image}
                    alt={order.garment.name}
                    className="size-20 rounded-2xl bg-white object-contain p-1"
                  />
                )}
                {order.look_image && (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img
                    src={order.look_image}
                    alt="Kiyib ko'rilgan rasm"
                    className="size-20 rounded-2xl bg-black object-cover"
                  />
                )}
              </div>

              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-extrabold">
                    {order.garment.name} · <span className="text-brand">{formatMoney(order.total_price)}</span>
                  </p>
                  <span className="text-xs text-muted-foreground">{formatDateTime(order.created_at)}</span>
                </div>
                <p className="text-xs">
                  <strong>Razmer:</strong> {order.size}
                  {order.color ? ` · Rang: ${order.color}` : ""} · <strong>Soni:</strong> {order.quantity} dona
                </p>
                <p className="text-xs text-muted-foreground">
                  <strong>Mijoz:</strong> {order.customer_name} ({formatPhone(order.customer_phone)}) ·{" "}
                  <strong>To&apos;lov:</strong> {order.payment_method_label}
                </p>
                <p className="text-xs text-muted-foreground">
                  <strong>Yetkazib berish:</strong> {order.delivery_type_label}
                  {order.delivery_address ? ` — ${order.delivery_address}` : ""}
                </p>
                {order.notes && <p className="text-xs text-muted-foreground">Izoh: {order.notes}</p>}
              </div>

              <div className="flex shrink-0 flex-col items-end gap-2">
                {canUpdate ? (
                  <select
                    value={order.status}
                    disabled={updateStatus.isPending}
                    onChange={(e) =>
                      updateStatus.mutate(
                        { id: order.id, status: e.target.value as AdminGarmentOrder["status"] },
                        {
                          onSuccess: () => toast.success("Buyurtma holati yangilandi"),
                          onError: (err) =>
                            toast.error(err instanceof ApiError ? err.message : "Holatni yangilab bo'lmadi"),
                        },
                      )
                    }
                    className="h-9 rounded-xl border border-glass-border bg-background px-2.5 text-xs font-bold"
                  >
                    {ORDER_STATUSES.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-bold">{order.status_label}</span>
                )}
                {order.look_drive_url && (
                  <a
                    href={order.look_drive_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600 hover:underline"
                  >
                    <CloudIcon className="size-3" /> Drive rasmi
                  </a>
                )}
              </div>
            </GlassCard>
          ))}
        </div>
      )}
    </div>
  );
}

function VirtualTryOnContent() {
  const [tab, setTab] = useState<Tab>("looks");
  return (
    <>
      <PageHeader
        title="Virtual kiyib ko'rish"
        crumb="Boshqaruv / Virtual kiyib ko'rish"
      />

      <div className="flex flex-wrap gap-2">
        <Button variant={tab === "looks" ? "default" : "outline"} onClick={() => setTab("looks")}>
          <ImagesIcon className="size-4" /> Kiyib ko&apos;rganlar (Google Drive)
        </Button>
        <Button variant={tab === "orders" ? "default" : "outline"} onClick={() => setTab("orders")}>
          <ShoppingBagIcon className="size-4" /> Buyurtmalar (Sotib olinganlar)
        </Button>
        <Button variant={tab === "garments" ? "default" : "outline"} onClick={() => setTab("garments")}>
          <ShirtIcon className="size-4" /> Kiyimlar katalogi
        </Button>
      </div>

      {tab === "looks" ? <LooksTab /> : tab === "orders" ? <OrdersTab /> : <GarmentsTab />}
    </>
  );
}

export default function AdminVirtualTryOnPage() {
  return (
    <RequirePermission requires={["tryon.view", "tryon.create", "tryon.update", "tryon.approve"]}>
      <PageTransition>
        <div className="flex flex-col gap-5">
          <VirtualTryOnContent />
        </div>
      </PageTransition>
    </RequirePermission>
  );
}
