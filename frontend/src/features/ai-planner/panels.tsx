"use client";

import { AlertTriangleIcon, CheckCircle2Icon, EyeIcon, PowerOffIcon, RefreshCwIcon, ShieldAlertIcon, XCircleIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState, ErrorState, GlassCard, Pagination, RowsSkeleton } from "@/components/common";
import { Field } from "@/components/common/form";
import { ConfirmDialog } from "@/components/motion/confirm-dialog";
import { MotionDrawer } from "@/components/motion/motion-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/client";
import { formatDateTime, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

import { criticalChanges } from "./access";
import {
  type AiConfig,
  type Bucket,
  type PromptVersion,
  type ReportStatus,
  useAdminConversation,
  useAdminConversations,
  useAiAudit,
  useAiConfig,
  useAiDashboard,
  useAiReports,
  useDisableAi,
  usePromptAction,
  usePrompts,
  useSavePrompt,
  useUpdateAiConfig,
  useUpdateReport,
  useUsageLogs,
  useValidateAiConfig,
} from "./api";

const nativeSelect =
  "h-10 rounded-xl border border-input bg-white/60 px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-slate-950/40";
const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Amal bajarilmadi");

const STATUS_TONE: Record<string, string> = {
  SUCCESS: "bg-emerald-500/14 text-emerald-700 dark:text-emerald-300",
  FALLBACK: "bg-amber-500/14 text-amber-700 dark:text-amber-300",
  ERROR: "bg-red-500/14 text-red-700 dark:text-red-300",
  BLOCKED: "bg-slate-500/14 text-slate-700 dark:text-slate-300",
  OPEN: "bg-amber-500/14 text-amber-700 dark:text-amber-300",
  IN_REVIEW: "bg-blue-500/14 text-blue-700 dark:text-blue-300",
  RESOLVED: "bg-emerald-500/14 text-emerald-700 dark:text-emerald-300",
  REJECTED: "bg-slate-500/14 text-slate-700 dark:text-slate-300",
  DRAFT: "bg-slate-500/14 text-slate-700 dark:text-slate-300",
  TESTED: "bg-blue-500/14 text-blue-700 dark:text-blue-300",
  ACTIVE: "bg-emerald-500/14 text-emerald-700 dark:text-emerald-300",
  ARCHIVED: "bg-slate-500/10 text-slate-600 dark:text-slate-400",
};

function Pill({ value, label }: { value: string; label?: string }) {
  return <span className={cn("inline-flex h-6 items-center rounded-full px-2.5 text-xs font-bold", STATUS_TONE[value] ?? STATUS_TONE.BLOCKED)}>{label ?? value}</span>;
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <GlassCard className="flex flex-col gap-1 p-4">
      <span className="text-xs font-semibold text-muted-foreground">{label}</span>
      <span className="text-2xl font-extrabold tabular-nums">{value}</span>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </GlassCard>
  );
}

// ------------------------------------------------------------------ dashboard
export function DashboardPanel() {
  const [period, setPeriod] = useState<"daily" | "weekly" | "monthly">("daily");
  const { data, error, isPending, refetch } = useAiDashboard(14);
  if (isPending)
    return (
      <div className="grid gap-3 sm:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-3xl" />
        ))}
      </div>
    );
  if (error)
    return (
      <GlassCard>
        <ErrorState error={error} onRetry={() => refetch()} />
      </GlassCard>
    );
  const t = data.today;
  const rows: Bucket[] = data[period];
  const max = Math.max(1, ...rows.map((r) => r.requests));
  const reported = t.input_tokens !== null;
  return (
    <div className="flex flex-col gap-4">
      <GlassCard className="flex flex-wrap items-center gap-3 p-4">
        {data.status.enabled && !data.status.maintenance_mode ? <Pill value="SUCCESS" label="Yoqilgan" /> : <Pill value="ERROR" label={data.status.maintenance_mode ? "Texnik rejim" : "O'chirilgan"} />}
        {data.status.provider_configured ? <Pill value="SUCCESS" label="Kalit sozlangan" /> : <Pill value="FALLBACK" label="Kalit yo'q (ANTHROPIC_API_KEY)" />}
        <span className="text-sm text-muted-foreground">
          {data.status.provider} · {data.status.model_name}
        </span>
        {Object.entries(data.status.features).map(([k, on]) => (
          <Badge key={k} variant={on ? "secondary" : "outline"}>
            {k}: {on ? "on" : "off"}
          </Badge>
        ))}
      </GlassCard>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Bugungi so'rovlar" value={formatNumber(t.requests)} hint={`${t.success} muvaffaqiyatli · ${t.fallback} zaxira · ${t.errors} xato`} />
        <Stat label="Foydalanuvchilar (bugun)" value={formatNumber(t.users)} hint={`${t.blocked} ta limit / o'chirilgan sabab rad`} />
        <Stat label="Faol suhbatlar (24 soat)" value={formatNumber(t.active_conversations)} hint={`Jami suhbatlar: ${formatNumber(data.totals.conversations)}`} />
        <Stat label="Yangi rejalar (bugun)" value={formatNumber(t.plans_created)} hint={`Jami: ${formatNumber(data.totals.plans)} · AI taxminlari: ${t.estimates_created}`} />
        <Stat label="Ochiq shikoyatlar" value={formatNumber(data.totals.open_reports)} />
        <Stat
          label="Tokenlar (bugun)"
          value={reported ? formatNumber((t.input_tokens ?? 0) + (t.output_tokens ?? 0)) : "—"}
          hint={reported ? `kirish ${formatNumber(t.input_tokens ?? 0)} · chiqish ${formatNumber(t.output_tokens ?? 0)}` : "Provayder sarfni xabar qilmadi"}
        />
        <Stat label="Taxminiy narx (bugun)" value={t.estimated_cost_usd ? `$${Number(t.estimated_cost_usd).toFixed(4)}` : "—"} hint="Faqat provayder sarfni bildirganda" />
      </div>
      <GlassCard className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-bold">So&apos;rovlar dinamikasi</h3>
          <div className="flex gap-1 rounded-xl bg-muted p-1">
            {(["daily", "weekly", "monthly"] as const).map((p) => (
              <button key={p} onClick={() => setPeriod(p)} aria-pressed={period === p} className={cn("rounded-lg px-3 py-1 text-xs font-semibold", period === p ? "bg-background shadow" : "text-muted-foreground")}>
                {p === "daily" ? "Kunlik" : p === "weekly" ? "Haftalik" : "Oylik"}
              </button>
            ))}
          </div>
        </div>
        {rows.length === 0 ? (
          <EmptyState title="Hali so'rovlar yo'q" />
        ) : (
          <ul className="flex flex-col gap-1.5">
            {rows.map((r) => (
              <li key={r.period} className="grid grid-cols-[6.5rem_1fr_auto] items-center gap-3 text-xs">
                <span className="tabular-nums text-muted-foreground">{r.period}</span>
                <span className="flex h-2.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${r.period}: ${r.requests} so'rov, ${r.errors} xato`}>
                  <span className="bg-emerald-500" style={{ width: `${(r.success / max) * 100}%` }} />
                  <span className="bg-amber-400" style={{ width: `${(r.fallback / max) * 100}%` }} />
                  <span className="bg-red-500" style={{ width: `${(r.errors / max) * 100}%` }} />
                </span>
                <span className="tabular-nums">
                  {r.requests}
                  {r.input_tokens !== null && <span className="text-muted-foreground"> · {formatNumber((r.input_tokens ?? 0) + (r.output_tokens ?? 0))} tok</span>}
                  {r.estimated_cost_usd && <span className="text-muted-foreground"> · ${Number(r.estimated_cost_usd).toFixed(3)}</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
        {data.top_errors.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Ko&apos;p uchragan xatolar: {data.top_errors.map((e) => `${e.error_code} (${e.n})`).join(", ")}
          </p>
        )}
      </GlassCard>
    </div>
  );
}

// ---------------------------------------------------------------- usage logs
export function UsagePanel() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const { data, error, isPending, refetch } = useUsageLogs({ page, page_size: 25, status: status || undefined });
  return (
    <div className="flex flex-col gap-3">
      <GlassCard className="flex flex-wrap items-center gap-2 p-3">
        <label className="text-sm">
          Holat{" "}
          <select className={nativeSelect} value={status} onChange={(e) => (setStatus(e.target.value), setPage(1))}>
            <option value="">Hammasi</option>
            {["SUCCESS", "FALLBACK", "ERROR", "BLOCKED"].map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
      </GlassCard>
      {isPending ? (
        <GlassCard><RowsSkeleton /></GlassCard>
      ) : error ? (
        <GlassCard><ErrorState error={error} onRetry={() => refetch()} /></GlassCard>
      ) : data.results.length === 0 ? (
        <GlassCard><EmptyState title="Yozuvlar yo'q" /></GlassCard>
      ) : (
        <GlassCard className="overflow-x-auto p-2">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr><th className="p-2">Vaqt</th><th className="p-2">Holat</th><th className="p-2">Xato kodi</th><th className="p-2">Model</th><th className="p-2 text-right">Tokenlar</th><th className="p-2 text-right">Kechikish</th></tr>
            </thead>
            <tbody>
              {data.results.map((r) => (
                <tr key={r.id} className="border-t border-border/60">
                  <td className="p-2 tabular-nums">{formatDateTime(r.created_at)}</td>
                  <td className="p-2"><Pill value={r.status} /></td>
                  <td className="p-2 font-mono text-xs">{r.error_code || "—"}</td>
                  <td className="p-2 text-xs">{r.model_name}</td>
                  <td className="p-2 text-right tabular-nums">{r.input_tokens === null ? "—" : `${r.input_tokens} / ${r.output_tokens}`}</td>
                  <td className="p-2 text-right tabular-nums">{r.latency_ms === null ? "—" : `${r.latency_ms} ms`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
      )}
      {data && data.count > 0 && <Pagination page={data.page} totalPages={data.total_pages} count={data.count} pageSize={data.page_size} onPage={setPage} />}
    </div>
  );
}

// ------------------------------------------------------------------- reports
const REPORT_REASONS: Record<string, string> = {
  WRONG_INFO: "Noto'g'ri ma'lumot",
  FAKE_SERVICE: "Mavjud bo'lmagan xizmat",
  WRONG_PRICE: "Noto'g'ri narx",
  OFFENSIVE: "Haqoratli",
  PRIVACY: "Shaxsiy ma'lumot",
  OTHER: "Boshqa",
};
const REPORT_STATUS: Record<ReportStatus, string> = { OPEN: "Yangi", IN_REVIEW: "Ko'rilmoqda", RESOLVED: "Hal qilindi", REJECTED: "Rad etildi" };

export function ReportsPanel() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<string>("OPEN");
  const { data, error, isPending, refetch } = useAiReports({ page, page_size: 20, status: status || undefined });
  const update = useUpdateReport();
  const [resolution, setResolution] = useState<Record<string, string>>({});
  return (
    <div className="flex flex-col gap-3">
      <GlassCard className="flex flex-wrap gap-1 p-2">
        {["OPEN", "IN_REVIEW", "RESOLVED", "REJECTED", ""].map((s) => (
          <Button key={s || "all"} size="sm" variant={status === s ? "default" : "ghost"} onClick={() => (setStatus(s), setPage(1))}>
            {s ? REPORT_STATUS[s as ReportStatus] : "Hammasi"}
          </Button>
        ))}
      </GlassCard>
      {isPending ? (
        <GlassCard><RowsSkeleton /></GlassCard>
      ) : error ? (
        <GlassCard><ErrorState error={error} onRetry={() => refetch()} /></GlassCard>
      ) : data.results.length === 0 ? (
        <GlassCard><EmptyState title="Shikoyatlar yo'q" /></GlassCard>
      ) : (
        data.results.map((r) => (
          <GlassCard key={r.id} className="flex flex-col gap-2 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex flex-wrap items-center gap-2 font-bold">
                {REPORT_REASONS[r.reason] ?? r.reason} <Pill value={r.status} label={REPORT_STATUS[r.status]} />
              </span>
              <span className="text-xs text-muted-foreground">{r.reporter?.label} · {formatDateTime(r.created_at)}</span>
            </div>
            <blockquote className="rounded-2xl bg-muted/60 p-3 text-sm whitespace-pre-line">{r.message_excerpt}</blockquote>
            {r.description && <p className="text-sm">Izoh: {r.description}</p>}
            {r.assigned_admin_label && <p className="text-xs text-muted-foreground">Mas&apos;ul: {r.assigned_admin_label}</p>}
            <Textarea
              aria-label="Yechim"
              placeholder="Yechim / javob"
              value={resolution[r.id] ?? r.resolution}
              onChange={(e) => setResolution((prev) => ({ ...prev, [r.id]: e.target.value }))}
            />
            <div className="flex flex-wrap justify-end gap-2">
              {r.status === "OPEN" && (
                <Button size="sm" variant="outline" disabled={update.isPending} onClick={() => update.mutate({ id: r.id, body: { status: "IN_REVIEW", assign_to_me: true } }, { onError })}>
                  O&apos;zimga olish
                </Button>
              )}
              <Button size="sm" variant="ghost" disabled={update.isPending} onClick={() => update.mutate({ id: r.id, body: { status: "REJECTED", resolution: resolution[r.id] ?? r.resolution } }, { onSuccess: () => toast.success("Rad etildi"), onError })}>
                <XCircleIcon /> Rad etish
              </Button>
              <Button size="sm" disabled={update.isPending} onClick={() => update.mutate({ id: r.id, body: { status: "RESOLVED", resolution: resolution[r.id] ?? r.resolution } }, { onSuccess: () => toast.success("Hal qilindi"), onError })}>
                <CheckCircle2Icon /> Hal qilindi
              </Button>
            </div>
          </GlassCard>
        ))
      )}
      {data && data.count > 0 && <Pagination page={data.page} totalPages={data.total_pages} count={data.count} pageSize={data.page_size} onPage={setPage} />}
    </div>
  );
}

// -------------------------------------------------------------- conversations
export function ConversationsPanel() {
  const [page, setPage] = useState(1);
  const [reported, setReported] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const { data, error, isPending, refetch } = useAdminConversations({ page, page_size: 20, reported: reported ? "true" : undefined });
  return (
    <div className="flex flex-col gap-3">
      <p className="flex items-center gap-2 rounded-2xl bg-amber-500/10 px-4 py-2.5 text-sm">
        <ShieldAlertIcon className="size-4 shrink-0" aria-hidden /> Telefon va email yashiriladi. Ro&apos;yxatni va har bir suhbatni ochish audit jurnaliga yoziladi.
      </p>
      <GlassCard className="flex items-center gap-2 p-3 text-sm">
        <Switch id="only-reported" checked={reported} onCheckedChange={(v) => (setReported(v), setPage(1))} />
        <label htmlFor="only-reported">Faqat shikoyat qilinganlar</label>
      </GlassCard>
      {isPending ? (
        <GlassCard><RowsSkeleton /></GlassCard>
      ) : error ? (
        <GlassCard><ErrorState error={error} onRetry={() => refetch()} /></GlassCard>
      ) : data.results.length === 0 ? (
        <GlassCard><EmptyState title="Suhbatlar yo'q" /></GlassCard>
      ) : (
        <GlassCard className="p-2">
          <ul>
            {data.results.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-2 border-t border-border/60 px-2 py-2.5 first:border-t-0">
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold">{c.title || "Nomsiz suhbat"}</span>
                  <span className="text-xs text-muted-foreground">{c.user?.label} · {c.message_count} xabar · {formatDateTime(c.last_message_at ?? c.created_at)}</span>
                </span>
                <Button size="sm" variant="outline" onClick={() => setOpen(c.id)}>
                  <EyeIcon /> Ko&apos;rish
                </Button>
              </li>
            ))}
          </ul>
        </GlassCard>
      )}
      {data && data.count > 0 && <Pagination page={data.page} totalPages={data.total_pages} count={data.count} pageSize={data.page_size} onPage={setPage} />}
      <ConversationDrawer id={open} onClose={() => setOpen(null)} />
    </div>
  );
}

function ConversationDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { data, error, isPending } = useAdminConversation(id);
  return (
    <MotionDrawer open={Boolean(id)} onOpenChange={(o) => !o && onClose()} title="AI suhbati" description="Yashirilgan ko'rinish · bu ochilish audit qilindi">
      {isPending ? (
        <RowsSkeleton rows={4} />
      ) : error ? (
        <ErrorState error={error} />
      ) : (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-muted-foreground">{data.user?.label} {data.user?.phone_masked && `· ${data.user.phone_masked}`}</p>
          {data.messages.map((m) => (
            <div key={m.id} className={cn("rounded-2xl p-3 text-sm whitespace-pre-line", m.role === "user" ? "ml-6 bg-blue-500/10" : "mr-6 bg-muted/70")}>
              <span className="mb-1 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                {m.role} · {formatDateTime(m.created_at)} {m.status !== "OK" && <Pill value={m.status === "FAILED" ? "ERROR" : m.status} label={`${m.status} ${m.error_code}`} />}
                {m.feedback && <span>baho: {m.feedback}</span>}
              </span>
              {m.content}
              {m.validation_notes.length > 0 && <span className="mt-1 block text-[11px] text-amber-600">{m.validation_notes.join(", ")}</span>}
            </div>
          ))}
        </div>
      )}
    </MotionDrawer>
  );
}

// ------------------------------------------------------------ emergency stop
export function ControlPanel() {
  const disable = useDisableAi();
  const [scope, setScope] = useState("all");
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const labels: Record<string, string> = { all: "Butun AI maslahatchi", chat: "Faqat chat", recommendations: "Xizmat tavsiyalari", booking_handoff: "Bronga o'tkazish" };
  return (
    <GlassCard className="flex max-w-xl flex-col gap-4">
      <p className="flex items-center gap-2 font-bold">
        <PowerOffIcon className="size-5 text-red-600" aria-hidden /> Favqulodda o&apos;chirish
      </p>
      <p className="text-sm text-muted-foreground">Bu yerdan faqat o&apos;chirish mumkin. Qayta yoqish — Super Admin sozlamalarida. Rejalar, byudjet va bronlar ishlashda davom etadi.</p>
      <Field label="Nimani o'chirish" htmlFor="ai-scope">
        <select id="ai-scope" className={nativeSelect} value={scope} onChange={(e) => setScope(e.target.value)}>
          {Object.entries(labels).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
      </Field>
      <Field label="Sabab (audit jurnaliga yoziladi)" htmlFor="ai-reason">
        <Textarea id="ai-reason" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <Button variant="destructive" disabled={!reason.trim()} onClick={() => setConfirming(true)}>
        <PowerOffIcon /> O&apos;chirish
      </Button>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        pending={disable.isPending}
        tone="danger"
        title={`${labels[scope]} o'chirilsinmi?`}
        description="Foydalanuvchilar darhol 'vaqtincha mavjud emas' holatini ko'radi. Amal audit jurnaliga yoziladi."
        confirmLabel="Ha, o'chirish"
        onConfirm={() =>
          disable.mutate(
            { scope, reason: reason.trim() },
            { onSuccess: () => (toast.success("O'chirildi"), setConfirming(false), setReason("")), onError },
          )
        }
      />
    </GlassCard>
  );
}

// ------------------------------------------------------------------ settings
const NUMBER_FIELDS: { key: keyof AiConfig; label: string; hint?: string }[] = [
  { key: "max_tokens", label: "Max tokens (javob)", hint: "512–16000" },
  { key: "history_limit", label: "Kontekstdagi xabarlar", hint: "2–40" },
  { key: "max_input_chars", label: "Xabar uzunligi (belgi)", hint: "100–8000" },
  { key: "daily_messages_per_user", label: "Kunlik limit (foydalanuvchi)", hint: "0 = cheksiz" },
  { key: "daily_messages_global", label: "Kunlik limit (platforma)", hint: "0 = cheksiz" },
  { key: "monthly_token_budget", label: "Oylik token byudjeti", hint: "0 = cheksiz" },
];

export function SettingsPanel() {
  const config = useAiConfig(true);
  if (config.isPending) return <Skeleton className="h-96 rounded-3xl" />;
  if (config.error)
    return (
      <GlassCard>
        <ErrorState error={config.error} onRetry={() => config.refetch()} />
      </GlassCard>
    );
  return <SettingsForm key={config.data.version} config={config.data} />;
}

function SettingsForm({ config }: { config: AiConfig }) {
  const update = useUpdateAiConfig();
  const validate = useValidateAiConfig();
  const [draft, setDraft] = useState<AiConfig>(config);
  const [confirm, setConfirm] = useState<string[] | null>(null);
  const changed = Object.fromEntries(
    Object.entries(draft).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(config[k as keyof AiConfig])),
  ) as Partial<AiConfig>;
  const set = <K extends keyof AiConfig>(k: K, v: AiConfig[K]) => setDraft((d) => ({ ...d, [k]: v }));

  const save = (confirmed: boolean) =>
    update.mutate(
      { ...changed, expected_version: config.version, confirm: confirmed },
      {
        onSuccess: () => (toast.success("Sozlamalar saqlandi"), setConfirm(null)),
        onError: (e) => {
          setConfirm(null);
          if (e instanceof ApiError && e.status === 409) toast.error("Boshqa admin o'zgartirgan — sahifa yangilandi.");
          else onError(e);
        },
      },
    );

  return (
    <div className="flex flex-col gap-4">
      <GlassCard className="flex flex-wrap items-center gap-3 p-4">
        {config.provider_configured ? <Pill value="SUCCESS" label="Kalit sozlangan" /> : <Pill value="FALLBACK" label="Kalit yo'q" />}
        <span className="text-xs text-muted-foreground">Manba: {config.key_source}. Kalit panelda saqlanmaydi va ko&apos;rsatilmaydi.</span>
        <Button size="sm" variant="outline" className="ml-auto" disabled={validate.isPending}
          onClick={() => validate.mutate(undefined, { onSuccess: (r) => (r.ok ? toast.success(r.message) : toast.error(`${r.message} (${r.code})`)), onError })}>
          <RefreshCwIcon /> Tekshirish
        </Button>
      </GlassCard>
      <GlassCard className="grid gap-4 sm:grid-cols-2">
        <Field label="Provayder" htmlFor="cfg-provider">
          <select id="cfg-provider" className={nativeSelect} value={draft.provider} onChange={(e) => set("provider", e.target.value as AiConfig["provider"])}>
            <option value="anthropic">Anthropic (Claude)</option>
          </select>
        </Field>
        <Field label="Model" htmlFor="cfg-model" hint="Masalan: claude-opus-5-5">
          <Input id="cfg-model" value={draft.model_name} onChange={(e) => set("model_name", e.target.value.trim())} />
        </Field>
        <Field label="Javob chuqurligi (effort)" htmlFor="cfg-effort">
          <select id="cfg-effort" className={nativeSelect} value={draft.effort} onChange={(e) => set("effort", e.target.value as AiConfig["effort"])}>
            <option value="low">Past (tez, arzon)</option>
            <option value="medium">O&apos;rta</option>
            <option value="high">Yuqori</option>
          </select>
        </Field>
        {NUMBER_FIELDS.map((f) => (
          <Field key={f.key} label={f.label} hint={f.hint} htmlFor={`cfg-${f.key}`}>
            <Input id={`cfg-${f.key}`} type="number" min={0} value={String(draft[f.key])} onChange={(e) => set(f.key, Number(e.target.value) as never)} />
          </Field>
        ))}
        <div className="flex flex-col gap-3 sm:col-span-2">
          {([
            ["enabled", "AI maslahatchi yoqilgan"],
            ["maintenance_mode", "Texnik rejim"],
          ] as const).map(([k, label]) => (
            <label key={k} className="flex items-center gap-2 text-sm font-semibold">
              <Switch checked={draft[k]} onCheckedChange={(v) => set(k, v)} /> {label}
            </label>
          ))}
          {draft.maintenance_mode && (
            <Field label="Texnik rejim xabari" htmlFor="cfg-mm">
              <Input id="cfg-mm" maxLength={300} value={draft.maintenance_message} onChange={(e) => set("maintenance_message", e.target.value)} />
            </Field>
          )}
          {(["chat", "recommendations", "booking_handoff"] as const).map((k) => (
            <label key={k} className="flex items-center gap-2 text-sm">
              <Switch checked={draft.feature_flags[k] !== false} onCheckedChange={(v) => set("feature_flags", { ...draft.feature_flags, [k]: v })} /> Flag: {k}
            </label>
          ))}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 sm:col-span-2">
          <span className="text-xs text-muted-foreground">
            Versiya {config.version} · {config.updated_by_label ? `${config.updated_by_label}, ` : ""}{formatDateTime(config.updated_at)}
          </span>
          <span className="flex gap-2">
            <Button variant="ghost" disabled={!Object.keys(changed).length} onClick={() => setDraft(config)}>Bekor qilish</Button>
            <Button
              disabled={!Object.keys(changed).length || update.isPending}
              onClick={() => {
                const critical = criticalChanges(config as unknown as Record<string, unknown>, changed as Record<string, unknown>);
                if (critical.length) setConfirm(critical);
                else save(false);
              }}
            >
              Saqlash
            </Button>
          </span>
        </div>
      </GlassCard>
      <ConfirmDialog
        open={Boolean(confirm)}
        onOpenChange={(o) => !o && setConfirm(null)}
        pending={update.isPending}
        tone="warning"
        title="Muhim o'zgarishni tasdiqlang"
        description={`Bu o'zgarishlar AI ishlashiga darhol ta'sir qiladi: ${confirm?.join(", ")}. Amal audit jurnaliga yoziladi.`}
        confirmLabel="Tasdiqlash"
        onConfirm={() => save(true)}
      />
    </div>
  );
}

// ------------------------------------------------------------------- prompts
export function PromptsPanel() {
  const { data, error, isPending, refetch } = usePrompts();
  const action = usePromptAction();
  const [editing, setEditing] = useState<PromptVersion | "new" | null>(null);
  const [activating, setActivating] = useState<PromptVersion | null>(null);
  return (
    <div className="flex flex-col gap-3">
      <GlassCard className="flex flex-wrap items-center justify-between gap-2 p-4">
        <p className="text-sm text-muted-foreground">Qoralama → sinov → faollashtirish. Eski versiyani qayta faollashtirish = orqaga qaytish. Xavfsizlik qoidalari har doim server tomonidan qo&apos;shiladi.</p>
        <Button onClick={() => setEditing("new")}>Yangi qoralama</Button>
      </GlassCard>
      {isPending ? (
        <GlassCard><RowsSkeleton /></GlassCard>
      ) : error ? (
        <GlassCard><ErrorState error={error} onRetry={() => refetch()} /></GlassCard>
      ) : data.results.length === 0 ? (
        <GlassCard><EmptyState title="Hali versiyalar yo'q" description="Hozir ichki (builtin-1) prompt ishlatilmoqda." /></GlassCard>
      ) : (
        data.results.map((p) => (
          <GlassCard key={p.id} className="flex flex-col gap-2 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-2 font-bold">v{p.number} · {p.title} <Pill value={p.status} /></span>
              <span className="text-xs text-muted-foreground">{p.created_by_label} · {formatDateTime(p.created_at)}{p.activated_at && ` · faollashtirgan: ${p.activated_by_label}, ${formatDateTime(p.activated_at)}`}</span>
            </div>
            <pre className="max-h-40 overflow-auto rounded-2xl bg-muted/60 p-3 text-xs whitespace-pre-wrap">{p.system_prompt}</pre>
            {p.tested_at && (
              <p className={cn("flex items-center gap-1.5 text-xs", p.test_result.ok ? "text-emerald-600" : "text-red-600")}>
                {p.test_result.ok ? <CheckCircle2Icon className="size-4" /> : <AlertTriangleIcon className="size-4" />}
                Sinov: {p.test_result.ok ? "o'tdi" : `o'tmadi (${p.test_result.code})`} · {p.test_result.live ? "jonli so'rov" : "faqat statik tekshiruv"} · {formatDateTime(p.tested_at)}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              {p.status === "DRAFT" && <Button size="sm" variant="ghost" onClick={() => setEditing(p)}>Tahrirlash</Button>}
              {p.status !== "ACTIVE" && p.status !== "ARCHIVED" && (
                <Button size="sm" variant="outline" disabled={action.isPending} onClick={() => action.mutate({ id: p.id, action: "test" }, { onSuccess: (r) => (r.test_result.ok ? toast.success("Sinov o'tdi") : toast.error("Sinov o'tmadi")), onError })}>
                  Sinash
                </Button>
              )}
              {(p.status === "TESTED" || p.status === "ARCHIVED") && (
                <Button size="sm" onClick={() => setActivating(p)}>{p.status === "ARCHIVED" ? "Shu versiyaga qaytish" : "Faollashtirish"}</Button>
              )}
            </div>
          </GlassCard>
        ))
      )}
      <PromptEditor value={editing} onClose={() => setEditing(null)} />
      <ConfirmDialog
        open={Boolean(activating)}
        onOpenChange={(o) => !o && setActivating(null)}
        pending={action.isPending}
        tone="warning"
        title={`v${activating?.number} faollashtirilsinmi?`}
        description="Keyingi barcha AI javoblari shu prompt bilan tayyorlanadi. Hozirgi faol versiya arxivga o'tadi (keyin unga qaytish mumkin)."
        confirmLabel="Faollashtirish"
        onConfirm={() => activating && action.mutate({ id: activating.id, action: "activate" }, { onSuccess: () => (toast.success("Faollashtirildi"), setActivating(null)), onError })}
      />
    </div>
  );
}

function PromptEditor({ value, onClose }: { value: PromptVersion | "new" | null; onClose: () => void }) {
  const save = useSavePrompt();
  const current = value && value !== "new" ? value : null;
  const [form, setForm] = useState({ title: "", system_prompt: "", notes: "" });
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const key = value === null ? null : current?.id ?? "new";
  if (key !== loadedFor) {
    setLoadedFor(key);
    setForm({ title: current?.title ?? "", system_prompt: current?.system_prompt ?? "", notes: current?.notes ?? "" });
  }
  const [errors, setErrors] = useState<Record<string, string>>({});
  return (
    <MotionDrawer open={value !== null} onOpenChange={(o) => !o && onClose()} title={current ? `v${current.number} qoralamasi` : "Yangi prompt qoralamasi"}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(
            { id: current?.id, body: form },
            {
              onSuccess: () => (toast.success("Saqlandi"), onClose()),
              onError: (err) => (err instanceof ApiError ? (setErrors(err.fieldErrors), toast.error(err.message)) : onError(err)),
            },
          );
        }}
      >
        <Field label="Nomi" htmlFor="pr-title" error={errors.title}>
          <Input id="pr-title" maxLength={120} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </Field>
        <Field label="Tizim prompti" htmlFor="pr-body" error={errors.system_prompt} hint="Kalit yoki maxfiy ma'lumot yozmang.">
          <Textarea id="pr-body" rows={14} value={form.system_prompt} onChange={(e) => setForm({ ...form, system_prompt: e.target.value })} />
        </Field>
        <Field label="Izoh" htmlFor="pr-notes" error={errors.notes}>
          <Input id="pr-notes" maxLength={1000} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </Field>
        <Button type="submit" disabled={save.isPending}>Saqlash</Button>
      </form>
    </MotionDrawer>
  );
}

// --------------------------------------------------------------------- audit
export function AuditPanel() {
  const [page, setPage] = useState(1);
  const { data, error, isPending, refetch } = useAiAudit({ page, page_size: 25 });
  if (isPending) return <GlassCard><RowsSkeleton /></GlassCard>;
  if (error) return <GlassCard><ErrorState error={error} onRetry={() => refetch()} /></GlassCard>;
  if (data.results.length === 0) return <GlassCard><EmptyState title="Audit yozuvlari yo'q" /></GlassCard>;
  return (
    <div className="flex flex-col gap-3">
      <GlassCard className="p-2">
        <ul>
          {data.results.map((a) => (
            <li key={a.id} className="flex flex-col gap-1 border-t border-border/60 px-2 py-2.5 first:border-t-0">
              <span className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-mono text-xs font-bold">{a.action}</span>
                <span className="text-muted-foreground">{a.actor_label || "—"} · {a.target_label}</span>
                <span className="ml-auto text-xs text-muted-foreground tabular-nums">{formatDateTime(a.created_at)}</span>
              </span>
              {Object.keys(a.changes).length > 0 && (
                <code className="block overflow-x-auto rounded-xl bg-muted/60 px-2 py-1 text-[11px]">{JSON.stringify(a.changes)}</code>
              )}
            </li>
          ))}
        </ul>
      </GlassCard>
      <Pagination page={data.page} totalPages={data.total_pages} count={data.count} pageSize={data.page_size} onPage={setPage} />
    </div>
  );
}
