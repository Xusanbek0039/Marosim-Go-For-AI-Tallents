"use client";

import { CameraIcon, HeartIcon, ShieldCheckIcon, ShirtIcon, SparklesIcon } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useState } from "react";

import { PageTitle } from "@/components/shell";
import { Badge, Button, Card, cn, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { formatMoney } from "@/lib/format";
import { type Garment, useGarmentCategories, useGarments, useToggleFavorite } from "@/lib/tryon";

// The camera engine (MediaPipe + WebGL) is only downloaded when the camera is opened.
const TryOnCamera = dynamic(() => import("@/features/tryon/tryon-camera").then((m) => m.TryOnCamera), { ssr: false });

export default function VirtualTryOnPage() {
  const categories = useGarmentCategories();
  const [picked, setPicked] = useState<string | null>(null);
  const category = picked ?? categories.data?.[0]?.slug ?? null;
  const garments = useGarments(category);
  const favorite = useToggleFavorite();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [camera, setCamera] = useState(false);

  const list = garments.data?.results ?? [];
  const selected = list.find((g) => g.id === selectedId) ?? null;

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PageTitle title="Virtual kiyib ko'rish" subtitle="Kiyimni tanlang va jonli kamerada o'zingizda ko'ring" />
        <Link href="/ai-studio">
          <Button>
            <SparklesIcon /> AI Fashion Studio (real kiyib ko&apos;rish)
          </Button>
        </Link>
      </div>

      {categories.error ? (
        <Card>
          <ErrorState error={categories.error} onRetry={() => categories.refetch()} />
        </Card>
      ) : (
        <div role="tablist" aria-label="Kiyim kategoriyalari" className="glass flex gap-1 overflow-x-auto rounded-2xl p-1 [scrollbar-width:none]">
          {categories.isPending
            ? [0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-9 w-36 shrink-0 rounded-xl" />)
            : categories.data.map((c) => (
                <button
                  key={c.slug}
                  type="button"
                  role="tab"
                  aria-selected={c.slug === category}
                  onClick={() => {
                    setPicked(c.slug);
                    setSelectedId(null);
                  }}
                  className={cn(
                    "shrink-0 rounded-xl px-3.5 py-2 text-sm font-semibold whitespace-nowrap transition",
                    c.slug === category ? "brand-gradient text-white" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {c.name}
                  <span className={cn("ml-1.5 text-xs", c.slug === category ? "text-white/80" : "text-muted-foreground")}>{c.garment_count}</span>
                </button>
              ))}
        </div>
      )}

      {garments.isPending && category ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="aspect-[3/4] rounded-3xl" />
          ))}
        </div>
      ) : garments.error ? (
        <Card>
          <ErrorState error={garments.error} onRetry={() => garments.refetch()} />
        </Card>
      ) : list.length === 0 ? (
        <Card>
          <EmptyState title="Bu bo'limda hozircha kiyim yo'q" description="Tez orada yangi liboslar qo'shiladi." />
        </Card>
      ) : (
        <ul className={cn("grid grid-cols-2 gap-3 sm:grid-cols-3", garments.isPlaceholderData && "opacity-60")}>
          {list.map((g) => (
            <li key={g.id}>
              <GarmentCard
                garment={g}
                selected={g.id === selectedId}
                onSelect={() => setSelectedId(g.id === selectedId ? null : g.id)}
                onFavorite={() => favorite.mutate({ garment: g.id, favorite: !g.is_favorite })}
              />
            </li>
          ))}
        </ul>
      )}

      <Card className="flex items-start gap-3 p-4 sm:p-4">
        <ShieldCheckIcon className="mt-0.5 size-5 shrink-0 text-success" />
        <p className="text-sm text-muted-foreground">
          Kamera faqat &quot;Kamerada kiyib ko&apos;rish&quot; tugmasini bosganingizda yoqiladi. Tasvir telefoningiz yoki kompyuteringizda qayta
          ishlanadi va serverga yuborilmaydi. Rasm faqat o&apos;zingiz tushirsangiz va yuklab olsangiz saqlanadi.
        </p>
      </Card>

      {/* Bottom action bar: the one selected product. */}
      <AnimatePresence>
        {selected && !camera && (
          <motion.div
            initial={{ y: 80, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 80, opacity: 0 }}
            className="glass-strong fixed inset-x-3 bottom-3 z-40 mx-auto flex max-w-xl items-center gap-3 rounded-2xl p-2.5 pb-[max(0.625rem,env(safe-area-inset-bottom))] shadow-2xl sm:inset-x-6"
          >
            <Thumb garment={selected} className="size-14 rounded-xl" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-bold">{selected.name}</p>
              <p className="text-xs text-muted-foreground">{formatMoney(selected.price)}</p>
            </div>
            {selected.ai_ready && !selected.tryon_ready ? (
              <Link href="/ai-studio">
                <Button>
                  <SparklesIcon /> AI bilan kiyib ko&apos;rish
                </Button>
              </Link>
            ) : (
              <Button onClick={() => setCamera(true)} disabled={!selected.tryon_ready} title={selected.tryon_ready ? undefined : "Bu kiyimning AR qatlami hali yo'q"}>
                <CameraIcon /> Kamerada kiyib ko&apos;rish
              </Button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
      {selected && <div className="h-20" aria-hidden />}

      <AnimatePresence>
        {camera && selected && category && (
          <TryOnCamera
            initialCategory={category}
            initialGarment={selected}
            onClose={({ category: c, garment }) => {
              setCamera(false);
              setPicked(c);
              setSelectedId(garment?.id ?? null);
            }}
          />
        )}
      </AnimatePresence>
    </>
  );
}

function Thumb({ garment, className }: { garment: Garment; className?: string }) {
  return (
    <span
      className={cn(
        "relative block shrink-0 overflow-hidden",
        // Covers are transparent cut-outs: a soft studio backdrop that works in both themes.
        "bg-[radial-gradient(120%_80%_at_50%_15%,rgb(37_99_235/0.14),transparent_60%),radial-gradient(90%_60%_at_50%_100%,rgb(6_182_212/0.12),transparent_70%)]",
        className,
      )}
    >
      {garment.cover_image ? (
        // eslint-disable-next-line @next/next/no-img-element -- media from the API
        <img
          src={garment.cover_image}
          alt=""
          className="size-full object-contain p-3 drop-shadow-[0_14px_18px_rgb(15_23_42/0.28)] transition-transform duration-500 group-hover:scale-[1.04]"
          loading="lazy"
        />
      ) : (
        <ShirtIcon className="absolute inset-0 m-auto size-6 text-muted-foreground" />
      )}
    </span>
  );
}

function GarmentCard({
  garment,
  selected,
  onSelect,
  onFavorite,
}: {
  garment: Garment;
  selected: boolean;
  onSelect: () => void;
  onFavorite: () => void;
}) {
  return (
    <div
      className={cn(
        "glass group relative overflow-hidden rounded-3xl ring-2 transition hover:-translate-y-0.5",
        selected ? "ring-brand shadow-[0_18px_40px_-20px_rgb(37_99_235/0.8)]" : "ring-transparent",
      )}
    >
      <button type="button" onClick={onSelect} aria-pressed={selected} className="block w-full text-left">
        <Thumb garment={garment} className="aspect-[3/4] w-full" />
        <span className="flex flex-col gap-1 p-3">
          <span className="truncate text-sm font-bold">{garment.name}</span>
          <span className="text-sm text-muted-foreground">{formatMoney(garment.price)}</span>
        </span>
      </button>
      <div className="pointer-events-none absolute top-2.5 left-2.5 flex gap-1">
        {garment.ai_ready && (
          <Badge tone="brand">
            <SparklesIcon className="size-3" /> AI
          </Badge>
        )}
        {garment.tryon_ready ? (
          <Badge tone="brand">
            <SparklesIcon className="size-3" /> AR
          </Badge>
        ) : !garment.ai_ready ? (
          <Badge>AR tez orada</Badge>
        ) : null}
      </div>
      <button
        type="button"
        onClick={onFavorite}
        aria-label={garment.is_favorite ? "Sevimlilardan olib tashlash" : "Sevimlilarga qo'shish"}
        aria-pressed={garment.is_favorite}
        className="glass-strong absolute top-2 right-2 grid size-9 place-items-center rounded-full"
      >
        <HeartIcon className={cn("size-4", garment.is_favorite && "fill-red-500 text-red-500")} />
      </button>
    </div>
  );
}
