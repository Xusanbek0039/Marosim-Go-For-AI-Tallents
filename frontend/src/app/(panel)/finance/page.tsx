"use client";

import {
  AlertTriangleIcon,
  ArrowDownRightIcon,
  ArrowUpRightIcon,
  BuildingIcon,
  CheckCircle2Icon,
  CoinsIcon,
  DollarSignIcon,
  PlusIcon,
  ReceiptIcon,
  SparklesIcon,
  Trash2Icon,
  WalletIcon,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState, ErrorState, GlassCard, PageHeader, RowsSkeleton } from "@/components/common";
import { RequirePermission } from "@/components/layout/require-permission";
import { PageTransition } from "@/components/motion/page-transition";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCan } from "@/features/auth/hooks";
import {
  EXPENSE_CATEGORIES,
  type ExpenseCategory,
  type FinanceReport,
  useAddExpense,
  useDeleteExpense,
  useExpenses,
  useFinanceReport,
  useUpdateRate,
} from "@/features/finance/api";
import { formatMoney } from "@/features/subscriptions/api";
import { ApiError } from "@/lib/api/client";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

const nativeSelect =
  "h-11 w-full rounded-xl border border-input bg-white/60 px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-slate-950/40";
const MONTHS = ["Yan", "Fev", "Mar", "Apr", "May", "Iyn", "Iyl", "Avg", "Sen", "Okt", "Noy", "Dek"];
const monthLabel = (ym: string) => `${MONTHS[Number(ym.slice(5, 7)) - 1]} ${ym.slice(0, 4)}`;
const num = (v: number | string) => Number(v) || 0;
const thisMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
const errorText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? ((Object.values(e.fieldErrors)[0] as string | undefined) ?? e.message) : fallback;
const AUDIENCE = { USER: "Foydalanuvchi Premium", STUDIO: "Studiyalar (150 000/oy)", VENUE: "To'yxonalar (300 000/oy)" };

// ================================================================ cards
function StatCards({ r }: { r: FinanceReport }) {
  const profit = num(r.profit);
  const cards = [
    { label: "Kirim", value: formatMoney(r.income.total), icon: ArrowDownRightIcon, tone: "from-emerald-500 to-teal-500" },
    { label: "Chiqim", value: formatMoney(r.expenses.total), icon: ArrowUpRightIcon, tone: "from-rose-500 to-orange-500" },
    {
      label: profit >= 0 ? "Sof foyda" : "Zarar",
      value: formatMoney(profit),
      icon: WalletIcon,
      tone: profit >= 0 ? "from-blue-600 to-cyan-500" : "from-red-600 to-rose-500",
    },
    {
      label: "Bizneslardan oylik to'lov",
      value: formatMoney(r.receivables.monthly_recurring),
      hint: `${r.receivables.paying_venues} to'yxona · ${r.receivables.paying_studios} studiya to'lagan`,
      icon: BuildingIcon,
      tone: "from-violet-500 to-fuchsia-500",
    },
  ];
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((c) => (
        <GlassCard key={c.label} className="flex items-center gap-4 p-4 sm:p-5">
          <span className={cn("flex size-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br text-white", c.tone)}>
            <c.icon className="size-5" aria-hidden />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-muted-foreground">{c.label}</p>
            <p className="truncate text-lg font-extrabold tabular-nums">{c.value}</p>
            {c.hint && <p className="truncate text-xs text-muted-foreground">{c.hint}</p>}
          </div>
        </GlassCard>
      ))}
    </div>
  );
}

// ================================================================ trend chart
const SERIES = [
  { key: "income" as const, label: "Kirim", cls: "fill-[#257de0] dark:fill-[#338ced]", dot: "bg-[#257de0] dark:bg-[#338ced]" },
  { key: "expense" as const, label: "Chiqim", cls: "fill-[#f47230] dark:fill-[#e76624]", dot: "bg-[#f47230] dark:bg-[#e76624]" },
];

function TrendChart({ trend }: { trend: FinanceReport["trend"] }) {
  const [hover, setHover] = useState<{ i: number; s: number } | null>(null);
  const [table, setTable] = useState(false);
  const W = 640, H = 220, PAD_L = 8, PAD_B = 26, PAD_T = 18;
  const max = Math.max(1, ...trend.flatMap((t) => [num(t.income), num(t.expense)]));
  const group = (W - PAD_L) / trend.length;
  const bar = Math.min(28, (group - 20) / 2);
  const y = (v: number) => H - PAD_B - ((H - PAD_B - PAD_T) * v) / max;
  const short = (v: number) => (v >= 1e6 ? `${(v / 1e6).toFixed(1)} mln` : v >= 1e3 ? `${Math.round(v / 1e3)} ming` : String(v));

  return (
    <GlassCard className="flex flex-col gap-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-bold">Oxirgi 6 oy: kirim va chiqim</h2>
        <div className="flex items-center gap-4 text-sm">
          {SERIES.map((s) => (
            <span key={s.key} className="flex items-center gap-1.5 text-muted-foreground">
              <span className={cn("size-2.5 rounded-sm", s.dot)} aria-hidden /> {s.label}
            </span>
          ))}
          <Button size="sm" variant="ghost" onClick={() => setTable((v) => !v)}>
            {table ? "Grafik" : "Jadval"}
          </Button>
        </div>
      </div>
      {table ? (
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr>
              <th className="py-2">Oy</th>
              <th className="py-2 text-right">Kirim</th>
              <th className="py-2 text-right">Chiqim</th>
              <th className="py-2 text-right">Foyda</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border tabular-nums">
            {trend.map((t) => (
              <tr key={t.month}>
                <td className="py-2">{monthLabel(t.month)}</td>
                <td className="py-2 text-right">{formatMoney(t.income)}</td>
                <td className="py-2 text-right">{formatMoney(t.expense)}</td>
                <td className={cn("py-2 text-right font-semibold", num(t.profit) < 0 && "text-red-600 dark:text-red-400")}>
                  {formatMoney(t.profit)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="relative">
          {trend.every((t) => !num(t.income) && !num(t.expense)) && (
            <p className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
              Hali kirim yoki chiqim qayd etilmagan
            </p>
          )}
          <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Oylik kirim va chiqim grafigi">
            {[0.25, 0.5, 0.75, 1].map((f) => (
              <line key={f} x1={PAD_L} x2={W} y1={y(max * f)} y2={y(max * f)} className="stroke-border" strokeDasharray="2 4" strokeWidth={1} />
            ))}
            <line x1={PAD_L} x2={W} y1={H - PAD_B} y2={H - PAD_B} className="stroke-border" strokeWidth={1} />
            {trend.map((t, i) => {
              const cx = PAD_L + group * i + group / 2;
              return (
                <g key={t.month}>
                  {SERIES.map((s, si) => {
                    const v = num(t[s.key]);
                    const h = Math.max(v > 0 ? 2 : 0, H - PAD_B - y(v));
                    const x = cx - bar - 1 + si * (bar + 2);
                    return (
                      <g key={s.key}>
                        <path
                          d={h > 0 ? `M${x},${H - PAD_B} v${-(h - 4)} q0,-4 4,-4 h${bar - 8} q4,0 4,4 v${h - 4} z` : ""}
                          className={cn(s.cls, hover && (hover.i !== i || hover.s !== si) && "opacity-40", "transition-opacity")}
                        />
                        <rect
                          x={x - 1}
                          y={PAD_T}
                          width={bar + 2}
                          height={H - PAD_B - PAD_T}
                          fill="transparent"
                          onMouseEnter={() => setHover({ i, s: si })}
                          onMouseLeave={() => setHover(null)}
                        />
                      </g>
                    );
                  })}
                  <text x={cx} y={H - 8} textAnchor="middle" className="fill-muted-foreground text-[9px]">
                    {monthLabel(t.month)}
                  </text>
                </g>
              );
            })}
            <text x={W} y={y(max) - 5} textAnchor="end" className="fill-muted-foreground text-[10px]">
              {short(max)}
            </text>
          </svg>
          {hover && (
            <div
              className="pointer-events-none absolute -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-xl border border-border bg-popover px-3 py-2 text-xs shadow-lg"
              style={{ left: `${((PAD_L + group * hover.i + group / 2) / W) * 100}%`, top: `${(y(num(trend[hover.i][SERIES[hover.s].key])) / H) * 100}%` }}
            >
              <p className="font-semibold">{monthLabel(trend[hover.i].month)}</p>
              <p className="flex items-center gap-1.5">
                <span className={cn("size-2 rounded-sm", SERIES[hover.s].dot)} /> {SERIES[hover.s].label}:{" "}
                <b className="tabular-nums">{formatMoney(trend[hover.i][SERIES[hover.s].key])}</b>
              </p>
            </div>
          )}
        </div>
      )}
    </GlassCard>
  );
}

// ================================================================ breakdowns
function Breakdown({ r }: { r: FinanceReport }) {
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <GlassCard className="flex flex-col gap-3 p-5">
        <h2 className="flex items-center gap-2 text-base font-bold">
          <CoinsIcon className="size-4" aria-hidden /> Kirim manbalari
        </h2>
        <ul className="divide-y divide-border text-sm">
          {(Object.keys(AUDIENCE) as (keyof typeof AUDIENCE)[]).map((a) => (
            <li key={a} className="flex items-center justify-between gap-3 py-2.5">
              <span>
                {AUDIENCE[a]} <span className="text-muted-foreground">· {r.income.by_audience[a].count} ta to&apos;lov</span>
              </span>
              <b className="tabular-nums">{formatMoney(r.income.by_audience[a].amount)}</b>
            </li>
          ))}
        </ul>
      </GlassCard>
      <GlassCard className="flex flex-col gap-3 p-5">
        <h2 className="flex items-center gap-2 text-base font-bold">
          <SparklesIcon className="size-4" aria-hidden /> AI xarajatlari (avtomatik hisoblangan)
        </h2>
        <ul className="divide-y divide-border text-sm">
          {r.expenses.ai.map((row) => (
            <li key={row.key} className="flex items-center justify-between gap-3 py-2.5">
              <span>
                {row.label} <span className="text-muted-foreground">· {row.count} ta · ${num(row.usd).toFixed(2)}</span>
              </span>
              <b className="tabular-nums">{formatMoney(row.amount)}</b>
            </li>
          ))}
          {r.expenses.manual.map((row) => (
            <li key={row.category} className="flex items-center justify-between gap-3 py-2.5">
              <span>
                {row.label} <span className="text-muted-foreground">· qo&apos;lda</span>
              </span>
              <b className="tabular-nums">{formatMoney(row.amount)}</b>
            </li>
          ))}
        </ul>
        <p className="text-xs text-muted-foreground">
          Birlik narxlari ({num(r.usd_rate).toLocaleString("ru-RU")} so&apos;m/$, +10% zaxira bilan): AI video {formatMoney(r.unit_costs.ai_video)}, AI foto{" "}
          {formatMoney(r.unit_costs.ai_photo)}, bulut xotira 1 GB/oy {formatMoney(r.unit_costs.storage_gb_month)}.
        </p>
      </GlassCard>
    </div>
  );
}

function Receivables({ r }: { r: FinanceReport }) {
  const rows = r.receivables.rows;
  return (
    <GlassCard className="flex flex-col gap-3 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-base font-bold">
          <AlertTriangleIcon className="size-4" aria-hidden /> Majburiy oylik to&apos;lov qarzdorlari
        </h2>
        <span className="text-sm text-muted-foreground">
          Jami kutilayotgan: <b className="text-foreground tabular-nums">{formatMoney(r.receivables.total_due)}</b>
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-300">
          <CheckCircle2Icon className="size-4" aria-hidden /> Barcha to&apos;yxona va studiyalar to&apos;lagan.
        </p>
      ) : (
        <ul className="divide-y divide-border text-sm">
          {rows.map((b) => (
            <li key={`${b.kind}-${b.id}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5">
              <span className="min-w-40 flex-1 font-semibold">
                {b.name} <span className="font-normal text-muted-foreground">· {b.kind === "venue" ? "To'yxona" : "Studiya"}</span>
              </span>
              <span
                className={cn(
                  "inline-flex h-6 items-center gap-1 rounded-full px-2.5 text-xs font-bold",
                  b.state === "OVERDUE" ? "bg-red-500/15 text-red-700 dark:text-red-300" : "bg-amber-500/15 text-amber-700 dark:text-amber-300",
                )}
              >
                {b.state === "OVERDUE" ? "Katalogdan yashirilgan" : `Muhlat: ${formatDate(b.grace_until)} gacha`}
              </span>
              <span className="text-muted-foreground">{b.paid_until ? `Oxirgi to'lov ${formatDate(b.paid_until)} gacha` : "Hali to'lamagan"}</span>
              <b className="tabular-nums">{formatMoney(b.monthly_fee)}</b>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted-foreground">
        To&apos;lovni &quot;Obunalar&quot; bo&apos;limida biznes nomidan Premium tarifini qayd etib qabul qiling — biznes darhol katalogga qaytadi.
      </p>
    </GlassCard>
  );
}

function PlanEconomics({ r }: { r: FinanceReport }) {
  return (
    <GlassCard className="flex flex-col gap-3 p-5">
      <h2 className="text-base font-bold">Tariflar iqtisodi (AI limiti to&apos;liq ishlatilganda)</h2>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr>
              <th className="py-2">Tarif</th>
              <th className="py-2">AI / oy</th>
              <th className="py-2 text-right">Narx / oy</th>
              <th className="py-2 text-right">Xarajat / oy</th>
              <th className="py-2 text-right">Foyda ulushi</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border tabular-nums">
            {r.plans.map((p) => (
              <tr key={p.id}>
                <td className="py-2 font-semibold">
                  {p.name} <span className="font-normal text-muted-foreground">· {formatMoney(p.price)}</span>
                </td>
                <td className="py-2 text-muted-foreground">
                  {p.audience === "USER" ? `${p.ai_video_per_month} video · ${p.ai_photo_per_month} foto` : "—"}
                </td>
                <td className="py-2 text-right">{formatMoney(p.price_per_month)}</td>
                <td className="py-2 text-right">{formatMoney(p.max_cost_per_month)}</td>
                <td className={cn("py-2 text-right font-bold", p.healthy ? "text-emerald-700 dark:text-emerald-300" : "text-red-600 dark:text-red-400")}>
                  {Math.round(num(p.margin) * 100)}%{!p.healthy && " ⚠"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">35% dan past foyda ulushi qizil bilan belgilanadi — narxni yoki AI limitini qayta ko&apos;rib chiqing.</p>
    </GlassCard>
  );
}

// ================================================================ expenses
function Expenses({ month }: { month: string }) {
  const can = useCan();
  const manage = can("finance.manage");
  const list = useExpenses(month);
  const add = useAddExpense();
  const remove = useDeleteExpense();
  const [form, setForm] = useState({ category: "SERVER" as ExpenseCategory, title: "", amount: "", spent_on: `${month}-01`, note: "" });

  return (
    <GlassCard className="flex flex-col gap-4 p-5">
      <h2 className="flex items-center gap-2 text-base font-bold">
        <ReceiptIcon className="size-4" aria-hidden /> Qo&apos;lda kiritilgan xarajatlar
      </h2>
      {manage && (
        <form
          className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_1.4fr_1fr_1fr_auto]"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate(form, {
              onSuccess: () => {
                toast.success("Xarajat qo'shildi");
                setForm((f) => ({ ...f, title: "", amount: "", note: "" }));
              },
              onError: (err) => toast.error(errorText(err, "Saqlanmadi")),
            });
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="e-cat">Turi</Label>
            <select id="e-cat" className={nativeSelect} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value as ExpenseCategory })}>
              {Object.entries(EXPENSE_CATEGORIES).map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="e-title">Nomi</Label>
            <Input id="e-title" required maxLength={120} placeholder="Masalan: Google One 2 TB" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="e-amount">Summa (so&apos;m)</Label>
            <Input
              id="e-amount"
              required
              inputMode="numeric"
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value.replace(/[^\d]/g, "") })}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="e-date">Sana</Label>
            <Input id="e-date" type="date" required value={form.spent_on} onChange={(e) => setForm({ ...form, spent_on: e.target.value })} />
          </div>
          <Button type="submit" className="self-end" disabled={add.isPending}>
            <PlusIcon /> Qo&apos;shish
          </Button>
        </form>
      )}
      {list.isPending ? (
        <RowsSkeleton rows={3} />
      ) : list.error ? (
        <ErrorState error={list.error} onRetry={() => list.refetch()} />
      ) : list.data.length === 0 ? (
        <EmptyState title="Bu oyda qo'lda kiritilgan xarajat yo'q" description="Server, Google Drive, reklama kabi to'lovlarni shu yerga yozing." />
      ) : (
        <ul className="divide-y divide-border text-sm">
          {list.data.map((x) => (
            <li key={x.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5">
              <span className="w-24 text-muted-foreground">{formatDate(x.spent_on)}</span>
              <span className="min-w-40 flex-1">
                <b>{x.title}</b> <span className="text-muted-foreground">· {EXPENSE_CATEGORIES[x.category]}</span>
              </span>
              <b className="tabular-nums">{formatMoney(x.amount)}</b>
              {manage && (
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`${x.title} xarajatini o'chirish`}
                  onClick={() => remove.mutate(x.id, { onSuccess: () => toast.success("O'chirildi") })}
                >
                  <Trash2Icon />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </GlassCard>
  );
}

function RateEditor({ rate }: { rate: number | string }) {
  const can = useCan();
  const update = useUpdateRate();
  const [value, setValue] = useState(String(Math.round(num(rate))));
  if (!can("finance.manage"))
    return (
      <span className="flex items-center gap-1 text-sm text-muted-foreground">
        <DollarSignIcon className="size-4" /> 1$ = {num(rate).toLocaleString("ru-RU")} so&apos;m
      </span>
    );
  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        update.mutate(value, { onSuccess: () => toast.success("Kurs yangilandi"), onError: (err) => toast.error(errorText(err, "Saqlanmadi")) });
      }}
    >
      <Label htmlFor="usd" className="whitespace-nowrap text-sm text-muted-foreground">
        1$ =
      </Label>
      <Input id="usd" className="h-10 w-28" inputMode="numeric" value={value} onChange={(e) => setValue(e.target.value.replace(/[^\d]/g, ""))} />
      <Button size="sm" variant="ghost" type="submit" disabled={update.isPending}>
        Saqlash
      </Button>
    </form>
  );
}

function FinanceContent() {
  const [month, setMonth] = useState(thisMonth());
  const report = useFinanceReport(month);
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Kirim-chiqim"
        crumb="Platforma moliyasi"
        actions={
          <>
            {report.data && <RateEditor key={String(report.data.usd_rate)} rate={report.data.usd_rate} />}
            <Input type="month" aria-label="Oy" className="h-10 w-44" value={month} max={thisMonth()} onChange={(e) => e.target.value && setMonth(e.target.value)} />
          </>
        }
      />
      {report.isPending ? (
        <RowsSkeleton rows={6} />
      ) : report.error ? (
        <ErrorState error={report.error} onRetry={() => report.refetch()} />
      ) : (
        <>
          <StatCards r={report.data} />
          <TrendChart trend={report.data.trend} />
          <Breakdown r={report.data} />
          <Receivables r={report.data} />
          <Expenses month={month} />
          <PlanEconomics r={report.data} />
        </>
      )}
    </div>
  );
}

export default function FinancePage() {
  return (
    <RequirePermission requires="finance.view">
      <PageTransition>
        <FinanceContent />
      </PageTransition>
    </RequirePermission>
  );
}
