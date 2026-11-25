"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  CameraIcon,
  DownloadIcon,
  HeartIcon,
  InfoIcon,
  Loader2Icon,
  RefreshCwIcon,
  ShirtIcon,
  SwitchCameraIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { toast } from "sonner";

import { cn } from "@/components/ui";
import { formatMoney } from "@/lib/format";
import {
  fetchGarmentAssets,
  type Garment,
  tryonSessions,
  useGarmentCategories,
  useGarments,
  useToggleFavorite,
} from "@/lib/tryon";

import { type EngineStatus, prefetchGarment, TryOnEngine } from "./engine";

const assetsKey = (id: string) => ["tryon", "assets", id] as const;

interface Props {
  initialCategory: string;
  initialGarment: Garment;
  onClose: (last: { category: string; garment: Garment | null }) => void;
}

/** Full-screen live camera try-on. The camera stays open while garments and categories change. */
export function TryOnCamera({ initialCategory, initialGarment, onClose }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<TryOnEngine | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const qc = useQueryClient();
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const [category, setCategory] = useState(initialCategory);
  const [selected, setSelected] = useState<Garment>(initialGarment);
  const [details, setDetails] = useState(false);
  const [shot, setShot] = useState<{ url: string; name: string } | null>(null);
  const [capturing, setCapturing] = useState(false);

  const categories = useGarmentCategories();
  const garments = useGarments(category);
  const favorite = useToggleFavorite();
  const list = useMemo(() => garments.data?.results ?? [], [garments.data]);
  const current = list.find((g) => g.id === selected.id) ?? selected;

  const assetsFor = useCallback(
    (id: string) => qc.fetchQuery({ queryKey: assetsKey(id), queryFn: ({ signal }) => fetchGarmentAssets(id, signal), staleTime: 10 * 60_000 }),
    [qc],
  );

  // ---------------------------------------------------- engine lifecycle
  useEffect(() => {
    const engine = new TryOnEngine(videoRef.current!, stageRef.current!, setStatus);
    engineRef.current = engine;
    engine.start("user");
    return () => {
      engine.stop();
      engineRef.current = null;
    };
  }, [attempt]);

  // Wear the selected garment (camera untouched). Re-applied after a retry.
  const wear = useCallback(
    async (garment: Garment) => {
      const engine = engineRef.current;
      if (!engine) return;
      try {
        const assets = await assetsFor(garment.id);
        if (engineRef.current !== engine) return;
        await engine.setGarment({ id: garment.id, assets });
      } catch {
        toast.error("Bu kiyimning AR qatlamini yuklab bo'lmadi.");
      }
    },
    [assetsFor],
  );

  const running = status?.phase === "running";
  useEffect(() => {
    if (running) wear(selected);
  }, [running, selected, wear]);

  // Decode the neighbours in the carousel ahead of time: switching then feels instant.
  useEffect(() => {
    const i = list.findIndex((g) => g.id === selected.id);
    for (const g of [list[i - 1], list[i + 1]]) {
      if (!g?.tryon_ready) continue;
      assetsFor(g.id)
        .then((assets) => prefetchGarment({ id: g.id, assets }))
        .catch(() => undefined);
    }
  }, [list, selected.id, assetsFor]);

  // Try-on statistics: one session per garment actually shown on the body.
  const shownId = status?.garmentId ?? null;
  useEffect(() => {
    if (!shownId) return;
    let sessionId: string | null = null;
    let done = false;
    tryonSessions
      .start(shownId)
      .then((s) => {
        sessionId = s.id;
        if (done) tryonSessions.finish(s.id).catch(() => undefined);
      })
      .catch(() => undefined);
    return () => {
      done = true;
      if (sessionId) tryonSessions.finish(sessionId).catch(() => undefined);
    };
  }, [shownId]);

  // ------------------------------------------------------------ page chrome
  const close = useCallback(() => {
    engineRef.current?.stop();
    onClose({ category, garment: selected });
  }, [category, selected, onClose]);

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || document.querySelector("[data-tryon-sheet]")) return;
      close();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [close]);

  useEffect(() => () => {
    if (shot) URL.revokeObjectURL(shot.url);
  }, [shot]);

  const select = (g: Garment) => {
    if (!g.tryon_ready) {
      toast.message("Bu kiyimni hozircha kamerada kiyib bo'lmaydi.");
      return;
    }
    setSelected(g);
  };

  const capture = async () => {
    const engine = engineRef.current;
    if (!engine || capturing) return;
    setCapturing(true);
    const blob = await engine.capture();
    setCapturing(false);
    if (!blob) return toast.error("Rasmga olib bo'lmadi.");
    setShot({ url: URL.createObjectURL(blob), name: `marosimgo-kiyib-korish-${Date.now()}.jpg` });
  };

  const discardShot = () => {
    if (shot) URL.revokeObjectURL(shot.url);
    setShot(null);
  };

  const mirrored = (status?.facing ?? "user") === "user";
  const error = status?.phase === "error" ? status.error : null;
  const starting = !status || status.phase === "starting";

  if (typeof document === "undefined") return null;
  return createPortal(
    <motion.div
      role="dialog"
      aria-modal="true"
      aria-label="Kamerada kiyib ko'rish"
      className="fixed inset-0 z-[60] flex flex-col overflow-hidden bg-slate-950 text-white"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      {/* Camera frames are only read by the engine; never uploaded. */}
      <video ref={videoRef} className="pointer-events-none absolute size-px opacity-0" playsInline muted autoPlay aria-hidden />
      {/* The engine puts its own <canvas> in here (mirrored for the front camera). */}
      <div
        ref={stageRef}
        role="img"
        aria-label={current ? `Kamera tasviri: ${current.name}` : "Kamera tasviri"}
        className="absolute inset-0"
        style={{ transform: mirrored ? "scaleX(-1)" : undefined }}
      />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-slate-950/70 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-72 bg-gradient-to-t from-slate-950/90 via-slate-950/55 to-transparent" />

      {/* TOP */}
      <header className="relative z-10 flex items-center gap-2 px-3 pt-[max(0.75rem,env(safe-area-inset-top))]">
        <RoundButton ref={closeRef} label="Yopish" onClick={close}>
          <XIcon className="size-5" />
        </RoundButton>
        <StatusPill status={status} />
        <RoundButton label="Kamerani almashtirish" onClick={() => engineRef.current?.switchCamera()} disabled={!running} className="ml-auto">
          <SwitchCameraIcon className="size-5" />
        </RoundButton>
      </header>

      {/* CENTER overlays */}
      <div className="relative z-10 flex flex-1 items-center justify-center px-6">
        {starting && !error && (
          <div className="flex flex-col items-center gap-3 rounded-3xl bg-slate-950/60 px-6 py-5 text-center backdrop-blur-md">
            <Loader2Icon className="size-7 animate-spin text-accent" />
            <p className="text-sm font-semibold">Kamera va tana kuzatuvi ishga tushirilmoqda…</p>
            <p className="max-w-64 text-xs text-slate-300">Brauzer so&apos;rasa, kameraga ruxsat bering. Tasvir qurilmangizdan chiqmaydi.</p>
          </div>
        )}
        {error && (
          <div role="alert" className="flex max-w-sm flex-col items-center gap-4 rounded-3xl bg-slate-950/80 px-6 py-6 text-center backdrop-blur-md">
            <CameraIcon className="size-8 text-red-300" />
            <p className="text-sm font-semibold leading-relaxed">{error.message}</p>
            <div className="flex gap-2">
              {!["insecure", "unsupported", "webgl"].includes(error.code) && (
                <button type="button" onClick={() => setAttempt((n) => n + 1)} className="brand-gradient inline-flex h-10 items-center gap-2 rounded-xl px-4 text-sm font-semibold">
                  <RefreshCwIcon className="size-4" /> Qayta urinish
                </button>
              )}
              <button type="button" onClick={close} className="h-10 rounded-xl bg-white/10 px-4 text-sm font-semibold hover:bg-white/20">
                Yopish
              </button>
            </div>
          </div>
        )}
      </div>

      <AnimatePresence>
        {running && status?.hint && (
          <motion.p
            key={status.hint}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            role="status"
            className="relative z-10 mx-auto mb-3 max-w-sm rounded-2xl bg-slate-950/70 px-4 py-2 text-center text-[13px] font-medium backdrop-blur-md"
          >
            {status.hint}
          </motion.p>
        )}
      </AnimatePresence>

      {/* BOTTOM */}
      <section aria-label="Kiyimlar" className="relative z-10 flex flex-col gap-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
        <div className="flex gap-2 overflow-x-auto px-3 [scrollbar-width:none]" role="tablist" aria-label="Kategoriyalar">
          {(categories.data ?? []).map((c) => (
            <button
              key={c.slug}
              role="tab"
              aria-selected={c.slug === category}
              type="button"
              onClick={() => setCategory(c.slug)}
              className={cn(
                "shrink-0 rounded-full px-3.5 py-1.5 text-[13px] font-semibold whitespace-nowrap transition",
                c.slug === category ? "brand-gradient text-white" : "bg-white/10 text-slate-200 hover:bg-white/20",
              )}
            >
              {c.name}
            </button>
          ))}
        </div>

        <ul className="flex snap-x gap-2.5 overflow-x-auto px-3 pb-1 [scrollbar-width:none]" aria-label="Kiyimlar ro'yxati">
          {garments.isPending && [0, 1, 2, 3].map((i) => <li key={i} className="h-36 w-28 shrink-0 animate-pulse rounded-2xl bg-white/10" />)}
          {!garments.isPending && list.length === 0 && <li className="px-1 py-6 text-sm text-slate-300">Bu bo&apos;limda hozircha kiyim yo&apos;q.</li>}
          {list.map((g) => {
            const active = g.id === selected.id;
            const loading = status?.loadingGarmentId === g.id;
            return (
              <li key={g.id} className="snap-start">
                <button
                  type="button"
                  onClick={() => select(g)}
                  aria-pressed={active}
                  className={cn(
                    "relative flex w-28 shrink-0 flex-col overflow-hidden rounded-2xl bg-white/10 text-left ring-2 backdrop-blur-md transition",
                    active ? "ring-accent" : "ring-transparent hover:bg-white/15",
                    !g.tryon_ready && "opacity-50",
                  )}
                >
                  <span className="relative block aspect-[3/4] w-full bg-[radial-gradient(100%_70%_at_50%_20%,rgb(255_255_255/0.16),transparent_70%)]">
                    {g.cover_image ? (
                      // eslint-disable-next-line @next/next/no-img-element -- user media from the API
                      <img src={g.cover_image} alt="" className="size-full object-contain p-1.5 drop-shadow-[0_8px_10px_rgb(0_0_0/0.45)]" loading="lazy" />
                    ) : (
                      <ShirtIcon className="absolute inset-0 m-auto size-8 text-slate-400" />
                    )}
                    {loading && (
                      <span className="absolute inset-0 grid place-items-center bg-slate-950/50">
                        <Loader2Icon className="size-5 animate-spin" />
                      </span>
                    )}
                  </span>
                  <span className="truncate px-2 pt-1.5 text-[12px] font-semibold">{g.name}</span>
                  <span className="px-2 pb-2 text-[11px] text-slate-300">{formatMoney(g.price)}</span>
                </button>
              </li>
            );
          })}
        </ul>

        <div className="flex items-center justify-between px-6">
          <RoundButton
            label={current.is_favorite ? "Sevimlilardan olib tashlash" : "Sevimlilarga qo'shish"}
            onClick={() => favorite.mutate({ garment: current.id, favorite: !current.is_favorite })}
          >
            <HeartIcon className={cn("size-5", current.is_favorite && "fill-red-500 text-red-500")} />
          </RoundButton>
          <button
            type="button"
            onClick={capture}
            disabled={!running || capturing}
            aria-label="Rasmga olish"
            className="grid size-[72px] place-items-center rounded-full border-4 border-white/80 transition active:scale-95 disabled:opacity-40"
          >
            <span className="size-14 rounded-full bg-white" />
          </button>
          <RoundButton label="Kiyim tafsilotlari" onClick={() => setDetails(true)}>
            <InfoIcon className="size-5" />
          </RoundButton>
        </div>
        <p className="truncate px-6 text-center text-sm font-semibold">
          {current.name} <span className="font-normal text-slate-300">· {formatMoney(current.price)}</span>
        </p>
      </section>

      <Sheet open={details} onClose={() => setDetails(false)} title={current.name}>
        <p className="text-lg font-bold">{formatMoney(current.price)}</p>
        {current.studio_name && <p className="text-sm text-slate-300">{current.studio_name}</p>}
        {current.description && <p className="text-sm leading-relaxed text-slate-200">{current.description}</p>}
        {current.sizes.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-semibold text-slate-400 uppercase">O&apos;lchamlar</p>
            <div className="flex flex-wrap gap-1.5">
              {current.sizes.map((s) => (
                <span key={s} className="rounded-lg bg-white/10 px-2.5 py-1 text-xs font-semibold">{s}</span>
              ))}
            </div>
          </div>
        )}
        {current.colors.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-semibold text-slate-400 uppercase">Ranglar</p>
            <div className="flex flex-wrap gap-2">
              {current.colors.map((c) => (
                <span key={c.name} className="inline-flex items-center gap-1.5 rounded-lg bg-white/10 px-2.5 py-1 text-xs font-semibold">
                  {c.hex && <span className="size-3 rounded-full ring-1 ring-white/40" style={{ background: c.hex }} />}
                  {c.name}
                </span>
              ))}
            </div>
          </div>
        )}
        <p className="text-xs text-slate-400">
          Kiyim tanangiz harakatiga moslashtirilgan 2D qatlam sifatida ko&apos;rsatiladi. Aniq o&apos;lcham uchun do&apos;kon bilan bog&apos;laning.
        </p>
      </Sheet>

      <Sheet open={Boolean(shot)} onClose={discardShot} title="Rasm">
        {shot && (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element -- local blob preview */}
            <img src={shot.url} alt={`${current.name} kiyib ko'rilgan rasm`} className="max-h-[50dvh] w-full rounded-2xl object-contain" />
            <p className="text-xs text-slate-400">Rasm hech qayerga yuborilmaydi — faqat siz yuklab olsangiz qurilmangizda saqlanadi.</p>
            <div className="flex gap-2">
              <a
                href={shot.url}
                download={shot.name}
                className="brand-gradient inline-flex h-11 flex-1 items-center justify-center gap-2 rounded-xl text-sm font-semibold"
              >
                <DownloadIcon className="size-4" /> Yuklab olish
              </a>
              <button type="button" onClick={discardShot} className="inline-flex h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-white/10 text-sm font-semibold hover:bg-white/20">
                <Trash2Icon className="size-4" /> O&apos;chirish
              </button>
            </div>
          </>
        )}
      </Sheet>
    </motion.div>,
    document.body,
  );
}

function RoundButton({
  label,
  className,
  children,
  ref,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string; ref?: React.Ref<HTMLButtonElement> }) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        "grid size-11 place-items-center rounded-full bg-slate-950/50 text-white backdrop-blur-md transition hover:bg-slate-950/70 focus-visible:ring-4 focus-visible:ring-accent/50 focus-visible:outline-none disabled:opacity-40",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

function StatusPill({ status }: { status: EngineStatus | null }) {
  let label = "Ishga tushmoqda";
  let tone = "bg-amber-400";
  if (status?.phase === "error") {
    label = "Xatolik";
    tone = "bg-red-500";
  } else if (status?.phase === "running") {
    if (status.tracking === "tracking") {
      label = "Tana kuzatilmoqda";
      tone = "bg-emerald-400";
    } else {
      label = status.tracking === "lost" ? "Tana yo'qoldi" : "Tana qidirilmoqda";
      tone = "bg-amber-400";
    }
  }
  return (
    <div role="status" aria-live="polite" className="flex min-w-0 items-center gap-2 rounded-full bg-slate-950/50 px-3 py-2 text-xs font-semibold backdrop-blur-md">
      <span className={cn("size-2 shrink-0 rounded-full", tone, status?.phase === "running" && status.tracking === "tracking" && "animate-pulse")} />
      <span className="truncate">{label}</span>
      {status?.phase === "running" && status.fps > 0 && <span className="text-slate-400 tabular-nums">{status.fps} FPS</span>}
      {status?.economy && <span className="text-slate-400">· tejamkor</span>}
    </div>
  );
}

function Sheet({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="absolute inset-0 z-20 flex items-end justify-center bg-slate-950/50 sm:items-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        >
          <motion.div
            role="dialog"
            aria-label={title}
            data-tryon-sheet
            className="flex max-h-[85dvh] w-full max-w-md flex-col gap-4 overflow-y-auto rounded-t-3xl bg-slate-900/95 p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] backdrop-blur-xl sm:rounded-3xl"
            initial={{ y: 40 }}
            animate={{ y: 0, transition: { type: "spring", stiffness: 380, damping: 34 } }}
            exit={{ y: 30, opacity: 0 }}
          >
            <div className="flex items-center justify-between gap-3">
              <h2 className="truncate text-base font-bold">{title}</h2>
              <button type="button" onClick={onClose} aria-label="Yopish" className="rounded-lg p-1.5 text-slate-300 hover:bg-white/10">
                <XIcon className="size-5" />
              </button>
            </div>
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
