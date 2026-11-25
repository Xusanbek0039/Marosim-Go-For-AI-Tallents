"use client";

import { CalendarCheck2Icon, ExternalLinkIcon, MapPinIcon, PlusIcon, StarIcon, UsersIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { type BookingTarget, BookingModal } from "@/components/booking-modal";
import { Badge, Button, Card, cn, EmptyState, ErrorState, Select, Skeleton } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { type Plan, type ServiceRow, useRecommendations, useSaveItem } from "@/lib/ai-planner";
import { formatDateTime, formatEventDate } from "@/lib/format";

import { formatSum } from "./budget";

const SORTS = [
  { value: "price", label: "Arzonroq avval" },
  { value: "-price", label: "Qimmatroq avval" },
  { value: "rating", label: "Reyting bo'yicha" },
  { value: "capacity", label: "Sig'im bo'yicha" },
];

const STUDIO_STATE: Record<string, { label: string; tone: "success" | "warning" | "danger" | "neutral" }> = {
  FREE_ON_CALENDAR: { label: "Kalendarda bo'sh", tone: "success" },
  HAS_EVENTS: { label: "Shu kuni marosimi bor", tone: "warning" },
  BUSY: { label: "Band", tone: "danger" },
  OFF: { label: "Dam olish kuni", tone: "neutral" },
  UNKNOWN: { label: "Sana kiritilmagan", tone: "neutral" },
};

/** Real platform services for this plan. Booking = the existing request form, opened by the user's own click. */
export function Recommendations({ plan }: { plan: Plan }) {
  const [category, setCategory] = useState<"VENUE" | "PHOTO_VIDEO">("VENUE");
  const [sort, setSort] = useState("price");
  const { data, error, isPending, refetch, isFetching } = useRecommendations(plan.id, category, sort);
  const save = useSaveItem(plan.id);
  const [target, setTarget] = useState<BookingTarget | null>(null);

  const addToPlan = (row: ServiceRow) =>
    save.mutate(
      { body: { source_type: "PLATFORM_SERVICE", source_kind: row.kind, source_reference: row.id } },
      {
        onSuccess: () => toast.success("Rejaga qo'shildi"),
        onError: (e) => toast.error(e instanceof ApiError ? e.message : "Qo'shib bo'lmadi"),
      },
    );

  return (
    <div className="flex flex-col gap-3">
      <Card className="flex flex-wrap items-center gap-2 p-3 sm:p-4">
        <div role="tablist" aria-label="Xizmat turi" className="flex gap-1 rounded-xl bg-muted p-1">
          {(["VENUE", "PHOTO_VIDEO"] as const).map((c) => (
            <button
              key={c}
              role="tab"
              aria-selected={category === c}
              onClick={() => setCategory(c)}
              className={cn("rounded-lg px-3 py-1.5 text-sm font-semibold", category === c ? "brand-gradient text-white" : "text-muted-foreground")}
            >
              {c === "VENUE" ? "To'yxonalar" : "Foto-video studiyalar"}
            </button>
          ))}
        </div>
        {category === "VENUE" && (
          <Select aria-label="Saralash" className="h-9 w-auto" value={sort} onChange={(e) => setSort(e.target.value)}>
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </Select>
        )}
        <p className="w-full text-xs text-muted-foreground">
          Faqat MarosimGo platformasidagi tasdiqlangan xizmatlar. Narx va bandlik platforma bazasidan olinadi
          {plan.region ? "" : " — aniqroq natija uchun viloyatni kiriting"}.
        </p>
      </Card>

      {isPending ? (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton className="h-32 rounded-3xl" />
          <Skeleton className="h-32 rounded-3xl" />
        </div>
      ) : error ? (
        <Card>
          <ErrorState error={error} onRetry={() => refetch()} />
        </Card>
      ) : data.results.length === 0 ? (
        <Card>
          <EmptyState title="Mos xizmat topilmadi" description={data.note ?? "Shartlarni o'zgartirib ko'ring (viloyat, mehmonlar soni)."} />
        </Card>
      ) : (
        <ul className={cn("flex flex-col gap-3 transition-opacity", isFetching && "opacity-60")}>
          {data.results.map((row) => (
            <ServiceCard
              key={row.id}
              row={row}
              plan={plan}
              dateKnown={data.date_known}
              handoff={data.booking_handoff}
              adding={save.isPending && save.variables?.body.source_reference === row.id}
              onAdd={() => addToPlan(row)}
              onBook={setTarget}
            />
          ))}
        </ul>
      )}

      <BookingModal
        target={target}
        onClose={() => setTarget(null)}
        defaults={{ eventType: data?.booking_event_type, guests: plan.guest_count, note: "MarosimGo AI rejasi orqali" }}
      />
    </div>
  );
}

function ServiceCard({
  row,
  plan,
  dateKnown,
  handoff,
  adding,
  onAdd,
  onBook,
}: {
  row: ServiceRow;
  plan: Plan;
  dateKnown: boolean;
  handoff: boolean;
  adding: boolean;
  onAdd: () => void;
  onBook: (t: BookingTarget) => void;
}) {
  const free = row.availability.free_sessions ?? [];
  const studioState = STUDIO_STATE[row.availability.state ?? "UNKNOWN"];
  return (
    <Card className="flex flex-col gap-3 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-base font-bold">{row.name}</p>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <MapPinIcon className="size-3.5" aria-hidden /> {[row.region_label, row.district].filter(Boolean).join(", ") || row.address}
            </span>
            {row.capacity && (
              <span className="flex items-center gap-1">
                <UsersIcon className="size-3.5" aria-hidden /> {row.capacity} kishigacha
              </span>
            )}
            <span className="flex items-center gap-1">
              <StarIcon className="size-3.5 text-amber-400" aria-hidden />
              {row.rating_avg !== null ? `${row.rating_avg} (${row.rating_count})` : "Hali baho yo'q"}
            </span>
          </p>
        </div>
        <div className="text-right">
          <p className="font-extrabold tabular-nums">{row.price ? `${formatSum(row.price)} dan` : "Narx ko'rsatilmagan"}</p>
          <p className="max-w-56 text-[11px] text-muted-foreground">
            {row.price_note}
            {row.price_checked_at && <> · {formatDateTime(row.price_checked_at)}</>}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        {row.in_plan && <Badge tone="brand">Rejada bor</Badge>}
        {row.over_budget && <Badge tone="warning">Byudjetdan qimmat</Badge>}
        {row.kind === "VENUE_HALL" ? (
          !row.availability.checked ? (
            <span className="text-muted-foreground">{dateKnown ? "Sana bron oralig'idan tashqarida" : "Bandlikni ko'rish uchun aniq sanani kiriting"}</span>
          ) : free.length === 0 ? (
            <Badge tone="danger">{formatEventDate(row.availability.date)} — bo&apos;sh smena yo&apos;q</Badge>
          ) : (
            <span className="flex flex-wrap items-center gap-1.5">
              <CalendarCheck2Icon className="size-4 text-success" aria-hidden />
              <span className="text-muted-foreground">{formatEventDate(row.availability.date)}:</span>
              {free.map((s) =>
                handoff ? (
                  <Button
                    key={s.id}
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      onBook({
                        venueName: row.venue_name ?? row.name,
                        address: row.address,
                        hallName: row.hall_name ?? "",
                        capacity: row.capacity ?? 1,
                        price: row.price ?? "0",
                        session: s,
                        date: row.availability.date!,
                      })
                    }
                  >
                    Bron so&apos;rovi · {s.name} {s.starts_at}
                  </Button>
                ) : (
                  <Badge key={s.id} tone="success">{s.name}</Badge>
                ),
              )}
            </span>
          )
        ) : (
          <Badge tone={studioState.tone}>{studioState.label}</Badge>
        )}
      </div>
      {row.kind === "VENUE_HALL" && free.length > 0 && !handoff && (
        <p className="text-xs text-muted-foreground">Bron qilish hozircha AI bo&apos;limidan o&apos;chirilgan — to&apos;yxona sahifasidan so&apos;rov yuboring.</p>
      )}

      <div className="flex flex-wrap justify-end gap-2">
        <Link href={row.url} className="inline-flex h-9 items-center gap-1.5 rounded-xl px-3 text-[13px] font-semibold hover:bg-muted">
          <ExternalLinkIcon className="size-4" aria-hidden /> Sahifasi
        </Link>
        {!row.in_plan && (
          <Button size="sm" onClick={onAdd} loading={adding} disabled={plan.status === "ARCHIVED"}>
            <PlusIcon /> Rejaga qo&apos;shish
          </Button>
        )}
      </div>
    </Card>
  );
}
