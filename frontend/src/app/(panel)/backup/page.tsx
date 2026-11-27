"use client";

import {
  ArchiveIcon,
  ArchiveRestoreIcon,
  CalendarPlusIcon,
  CrownIcon,
  EyeIcon,
  FilmIcon,
  HourglassIcon,
  ImageIcon,
  RefreshCwIcon,
  SearchIcon,
  Trash2Icon,
  VideoOffIcon,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState, ErrorState, GlassCard, PageHeader, RowsSkeleton } from "@/components/common";
import { RequirePermission } from "@/components/layout/require-permission";
import { MotionDialog } from "@/components/motion/motion-dialog";
import { PageTransition } from "@/components/motion/page-transition";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCan } from "@/features/auth/hooks";
import {
  type BackupRow,
  type BackupStatus,
  mediaUrl,
  REASON,
  STATUS,
  useBackupAction,
  useBackupDetail,
  useBackupList,
  useBackupMedia,
  useBackupSummary,
  useDeleteBackupMedia,
  useSyncAll,
} from "@/features/backup/api";
import { ApiError } from "@/lib/api/client";
import { formatDate, formatPhone } from "@/lib/format";
import { cn } from "@/lib/utils";

const errorText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? ((Object.values(e.fieldErrors)[0] as string | undefined) ?? e.message) : fallback;
const bytes = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${Math.round(n / 1e6)} MB` : n ? `${Math.round(n / 1e3)} KB` : "—");
const daysLeft = (iso: string | null) => (iso ? Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000) : null);

function StatusBadge({ status }: { status: BackupStatus }) {
  return <span className={cn("inline-flex h-6 items-center rounded-full px-2.5 text-xs font-bold", STATUS[status].className)}>{STATUS[status].label}</span>;
}

// ================================================================ summary
function Summary({ onPick, active }: { onPick: (s: BackupStatus | "") => void; active: string }) {
  const { data } = useBackupSummary();
  const cards: { key: BackupStatus; label: string; icon: typeof ArchiveIcon; tone: string }[] = [
    { key: "TRIAL", label: "Bepul muddatda", icon: HourglassIcon, tone: "from-sky-500 to-cyan-500" },
    { key: "PREMIUM", label: "Premium", icon: CrownIcon, tone: "from-emerald-500 to-teal-500" },
    { key: "BACKUP", label: "Backupda", icon: ArchiveIcon, tone: "from-rose-500 to-red-600" },
    { key: "NO_VIDEO", label: "Hali video yo'q", icon: VideoOffIcon, tone: "from-slate-500 to-slate-600" },
  ];
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((c) => (
        <button key={c.key} type="button" onClick={() => onPick(active === c.key ? "" : c.key)} className="text-left">
          <GlassCard className={cn("flex items-center gap-4 p-4 transition sm:p-5", active === c.key && "ring-2 ring-primary")}>
            <span className={cn("flex size-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br text-white", c.tone)}>
              <c.icon className="size-5" aria-hidden />
            </span>
            <div>
              <p className="text-xs font-semibold text-muted-foreground">{c.label}</p>
              <p className="text-lg font-extrabold tabular-nums">{data ? data[c.key] : "—"}</p>
            </div>
          </GlassCard>
        </button>
      ))}
    </div>
  );
}

// ================================================================ dialogs
type Action = { kind: "release" | "extend-premium" | "backup"; row: BackupRow } | null;

function ActionDialog({ action, onClose }: { action: Action; onClose: () => void }) {
  const run = useBackupAction();
  const [days, setDays] = useState("90");
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const row = action?.row;
  const titles = { release: "Backupdan chiqarish", "extend-premium": "Premiumni uzaytirish", backup: "Backup rejimiga o'tkazish" };
  const submit = () => {
    if (!action) return;
    const body: Record<string, unknown> = { note };
    if (action.kind !== "backup") {
      if (date) body.until = new Date(`${date}T23:59:00`).toISOString();
      else body.days = Number(days);
    }
    run.mutate(
      { id: action.row.id, kind: action.kind, body },
      {
        onSuccess: () => {
          toast.success("Saqlandi");
          onClose();
        },
        onError: (e) => toast.error(errorText(e, "Saqlanmadi")),
      },
    );
  };
  return (
    <MotionDialog
      open={Boolean(action)}
      onOpenChange={(o) => !o && onClose()}
      title={action ? titles[action.kind] : ""}
      description={row ? `${row.full_name || "—"} · ${formatPhone(row.phone_number ?? "")}` : undefined}
      footer={
        <>
          <Button variant="outline" className="h-11" onClick={onClose}>
            Yopish
          </Button>
          <Button
            className={cn("h-11", action?.kind === "backup" && "bg-red-600 text-white hover:bg-red-700")}
            onClick={submit}
            disabled={run.isPending}
          >
            {action ? titles[action.kind] : ""}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {action?.kind === "release" && (
          <p className="text-sm text-muted-foreground">
            Foydalanuvchi marosimlarini yana ko&apos;radi. Tanlangan muddat tugaganda Premium bo&apos;lmasa, avtomatik Backupga qaytadi.
          </p>
        )}
        {action?.kind === "extend-premium" && (
          <p className="text-sm text-muted-foreground">
            Joriy Premium obunaning tugash sanasi o&apos;zgaradi
            {row?.premium_until ? ` (hozir: ${formatDate(row.premium_until)})` : ""}. Muddatlar shu kundan boshlab hisoblanadi.
          </p>
        )}
        {action?.kind === "backup" && (
          <p className="text-sm text-muted-foreground">
            Foydalanuvchi va u ulashgan odamlar marosimlarni ko&apos;ra olmaydi. Fayllar o&apos;chirilmaydi, ularni faqat Admin va Super Admin ko&apos;radi. Foydalanuvchiga bildirishnoma boradi.
          </p>
        )}
        {action?.kind !== "backup" && (
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="b-days">Bugundan necha kun</Label>
              <Input id="b-days" inputMode="numeric" value={days} disabled={Boolean(date)} onChange={(e) => setDays(e.target.value.replace(/[^\d]/g, ""))} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="b-date">yoki aniq sana</Label>
              <Input id="b-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </div>
          </div>
        )}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="b-note">Izoh (foydalanuvchiga bildirishnomada ko&apos;rinadi)</Label>
          <Input id="b-note" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
      </div>
    </MotionDialog>
  );
}

function MediaGrid({ ceremonyId }: { ceremonyId: string }) {
  const can = useCan();
  const media = useBackupMedia(ceremonyId);
  const remove = useDeleteBackupMedia(ceremonyId);
  const [playing, setPlaying] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  if (media.isPending) return <RowsSkeleton rows={2} />;
  if (media.error) return <ErrorState error={media.error} onRetry={() => media.refetch()} />;
  if (media.data.length === 0) return <p className="text-sm text-muted-foreground">Bu marosimda fayl yo&apos;q.</p>;
  return (
    <div className="flex flex-col gap-3">
      {playing && (
        <video key={playing} src={mediaUrl(ceremonyId, playing, "stream")} controls autoPlay className="max-h-[50vh] w-full rounded-2xl bg-black" />
      )}
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        {media.data.map((m) => (
          <div key={m.id} className="group relative overflow-hidden rounded-2xl border border-border bg-muted">
            <button
              type="button"
              className="block aspect-square w-full"
              onClick={() => (m.kind === "VIDEO" ? setPlaying(m.id) : window.open(mediaUrl(ceremonyId, m.id, "stream"), "_blank"))}
              aria-label={m.kind === "VIDEO" ? "Videoni ko'rish" : "Rasmni ochish"}
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- private, cookie-authenticated API image */}
              <img src={mediaUrl(ceremonyId, m.id, "thumbnail")} alt="" loading="lazy" className="size-full object-cover" />
              <span className="absolute top-2 left-2 inline-flex items-center gap-1 rounded-full bg-black/60 px-2 py-0.5 text-[11px] font-semibold text-white">
                {m.kind === "VIDEO" ? <FilmIcon className="size-3" /> : <ImageIcon className="size-3" />} {bytes(m.size_bytes)}
              </span>
            </button>
            {can("backup.manage") && (
              <Button
                size="sm"
                variant={confirm === m.id ? "destructive" : "ghost"}
                className="absolute right-2 bottom-2 bg-black/55 text-white hover:bg-black/75"
                disabled={remove.isPending}
                onClick={() => {
                  if (confirm !== m.id) return setConfirm(m.id);
                  remove.mutate(m.id, { onSuccess: () => toast.success("Fayl o'chirildi (Drive savatchasida 30 kun turadi)") });
                }}
              >
                <Trash2Icon /> {confirm === m.id ? "Tasdiqlang" : ""}
              </Button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function DetailDialog({ id, onClose }: { id: string | null; onClose: () => void }) {
  const detail = useBackupDetail(id);
  const [ceremony, setCeremony] = useState<string | null>(null);
  const d = detail.data;
  const facts: [string, string][] = d
    ? [
        ["Holat", STATUS[d.status].label],
        ["Birinchi video", formatDate(d.first_video_at)],
        ["Bepul muddat", d.grace_ends_at ? `${formatDate(d.grace_started_at)} — ${formatDate(d.grace_ends_at)} (${REASON[d.grace_reason] ?? "—"})` : "—"],
        ["Premium", d.premium_until ? `${formatDate(d.premium_until)} gacha` : "yo'q"],
        ["Backupda", d.backup_since ? `${formatDate(d.backup_since)} dan` : "—"],
        ["Hajm", `${d.videos} video · ${bytes(d.media_bytes)}`],
      ]
    : [];
  return (
    <MotionDialog
      open={Boolean(id)}
      onOpenChange={(o) => {
        if (!o) {
          setCeremony(null);
          onClose();
        }
      }}
      size="lg"
      title={d ? d.full_name || "Foydalanuvchi" : "Yuklanmoqda…"}
      description={d ? formatPhone(d.phone_number ?? "") : undefined}
    >
      {detail.isPending ? (
        <RowsSkeleton rows={3} />
      ) : detail.error ? (
        <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
      ) : (
        <div className="flex flex-col gap-5">
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            {facts.map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3 border-b border-border/60 py-1.5">
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="text-right font-semibold">{v}</dd>
              </div>
            ))}
          </dl>
          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-bold">Marosimlar</h3>
            {d!.ceremony_list.length === 0 && <p className="text-sm text-muted-foreground">Marosim yo&apos;q.</p>}
            <div className="flex flex-wrap gap-2">
              {d!.ceremony_list.map((c) => (
                <Button key={c.id} variant={ceremony === c.id ? "default" : "outline"} className="h-10" onClick={() => setCeremony(c.id)}>
                  {c.title} · {c.video_count} video, {c.media_count - c.video_count} rasm
                </Button>
              ))}
            </div>
          </div>
          {ceremony && <MediaGrid ceremonyId={ceremony} />}
        </div>
      )}
    </MotionDialog>
  );
}

// ================================================================ page
const FILTERS: { key: BackupStatus | ""; label: string }[] = [
  { key: "", label: "Hammasi" },
  { key: "TRIAL", label: "Bepul muddatda" },
  { key: "PREMIUM", label: "Premium" },
  { key: "BACKUP", label: "Backupda" },
  { key: "NO_VIDEO", label: "Video yo'q" },
];

function BackupContent() {
  const can = useCan();
  const manage = can("backup.manage");
  const [status, setStatus] = useState<BackupStatus | "">("");
  const [search, setSearch] = useState("");
  const [action, setAction] = useState<Action>(null);
  const [detail, setDetail] = useState<string | null>(null);
  const list = useBackupList({ status: status || undefined, search: search.trim() || undefined });
  const syncAll = useSyncAll();

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Backup"
        crumb="Bepul muddat va Premium tugagan foydalanuvchilar"
        actions={
          manage && (
            <Button
              variant="outline"
              className="h-11"
              disabled={syncAll.isPending}
              onClick={() => syncAll.mutate(undefined, { onSuccess: () => toast.success("Barcha holatlar qayta hisoblandi") })}
            >
              <RefreshCwIcon className={cn(syncAll.isPending && "animate-spin")} /> Hozir yangilash
            </Button>
          )
        }
      />
      <Summary active={status} onPick={setStatus} />
      <GlassCard className="flex flex-wrap items-center gap-3 p-3">
        <div className="flex flex-wrap gap-1.5">
          {FILTERS.map((f) => (
            <Button key={f.key || "all"} size="sm" variant={status === f.key ? "default" : "ghost"} className="h-9" onClick={() => setStatus(f.key)}>
              {f.label}
            </Button>
          ))}
        </div>
        <div className="relative ml-auto w-full sm:w-72">
          <SearchIcon className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input className="h-10 pl-9" placeholder="Ism yoki telefon" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Qidirish" />
        </div>
      </GlassCard>
      <GlassCard className="p-0 sm:p-0">
        {list.isPending ? (
          <div className="p-5">
            <RowsSkeleton />
          </div>
        ) : list.error ? (
          <ErrorState error={list.error} onRetry={() => list.refetch()} />
        ) : list.data.results.length === 0 ? (
          <EmptyState
            title="Foydalanuvchi topilmadi"
            description="Bu ro'yxatga marosimiga video joylangan foydalanuvchilar tushadi. Bepul muddat birinchi video joylangan kundan 3 oy."
          />
        ) : (
          <ul className="divide-y divide-border/70">
            {list.data.results.map((r) => {
              const left = daysLeft(r.grace_ends_at);
              return (
                <li key={r.id} className="flex flex-wrap items-center gap-x-5 gap-y-2 px-5 py-4">
                  <div className="min-w-48 flex-1">
                    <p className="font-semibold">{r.full_name || "—"}</p>
                    <p className="text-sm text-muted-foreground tabular-nums">{formatPhone(r.phone_number ?? "")}</p>
                  </div>
                  <div className="w-44 text-sm">
                    <StatusBadge status={r.status} />
                    <p className="mt-1 text-xs text-muted-foreground">
                      {r.status === "BACKUP"
                        ? `${formatDate(r.backup_since)} dan beri`
                        : r.status === "PREMIUM"
                          ? `${formatDate(r.premium_until)} gacha`
                          : r.grace_ends_at
                            ? `${formatDate(r.grace_ends_at)} gacha${left !== null && left >= 0 ? ` · ${left} kun` : ""}`
                            : "muddat boshlanmagan"}
                    </p>
                  </div>
                  <div className="w-44 text-xs text-muted-foreground">
                    <p>1-video: {formatDate(r.first_video_at)}</p>
                    <p>
                      {r.ceremonies} marosim · {r.videos} video · {bytes(r.media_bytes)}
                    </p>
                  </div>
                  <div className="ml-auto flex flex-wrap gap-2">
                    <Button variant="outline" className="h-10" onClick={() => setDetail(r.id)}>
                      <EyeIcon /> Ko&apos;rish
                    </Button>
                    {manage && r.status === "BACKUP" && (
                      <Button className="h-10" onClick={() => setAction({ kind: "release", row: r })}>
                        <ArchiveRestoreIcon /> Backupdan chiqarish
                      </Button>
                    )}
                    {manage && r.status === "TRIAL" && (
                      <>
                        <Button variant="outline" className="h-10" onClick={() => setAction({ kind: "release", row: r })}>
                          <CalendarPlusIcon /> Muddatni uzaytirish
                        </Button>
                        <Button variant="destructive" className="h-10" onClick={() => setAction({ kind: "backup", row: r })}>
                          <ArchiveIcon /> Backupga
                        </Button>
                      </>
                    )}
                    {manage && r.status === "PREMIUM" && (
                      <Button variant="outline" className="h-10" onClick={() => setAction({ kind: "extend-premium", row: r })}>
                        <CrownIcon /> Premiumni uzaytirish
                      </Button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </GlassCard>
      <ActionDialog key={action ? `${action.kind}-${action.row.id}` : "none"} action={action} onClose={() => setAction(null)} />
      <DetailDialog id={detail} onClose={() => setDetail(null)} />
    </div>
  );
}

export default function BackupPage() {
  return (
    <RequirePermission requires="backup.view">
      <PageTransition>
        <BackupContent />
      </PageTransition>
    </RequirePermission>
  );
}
