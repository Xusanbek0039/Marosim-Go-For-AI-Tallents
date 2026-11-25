"use client";

import { AlertTriangleIcon, CalculatorIcon, ScissorsIcon, WalletIcon } from "lucide-react";
import { motion } from "motion/react";
import { toast } from "sonner";

import { Button, Card, cn, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { type Summary, useSaveItem, useSummary } from "@/lib/ai-planner";

import { BudgetStateBadge } from "./bits";
import { BUDGET_STATE, formatRange, formatSum, parseMoney } from "./budget";

const n = (value: string | null | undefined) => Number(parseMoney(value?.replace("-", "") ?? "0") ?? BigInt(0)) / 100;

/** Server-computed budget: totals, remaining, overrun, category chart (planned vs actual, verified vs estimated). */
export function BudgetDashboard({ planId }: { planId: string }) {
  const { data, error, isPending, refetch } = useSummary(planId);
  if (isPending)
    return (
      <div className="grid gap-3 sm:grid-cols-3" aria-busy="true">
        <Skeleton className="h-28 rounded-3xl" />
        <Skeleton className="h-28 rounded-3xl" />
        <Skeleton className="h-28 rounded-3xl" />
      </div>
    );
  if (error)
    return (
      <Card>
        <ErrorState error={error} onRetry={() => refetch()} />
      </Card>
    );
  if (data.status === "NO_ITEMS")
    return (
      <Card>
        <EmptyState title="Hali hisob-kitob yo'q" description="Xarajat bandlarini qo'shing yoki AI maslahatchidan taxminiy reja so'rang." />
      </Card>
    );
  return <DashboardBody planId={planId} s={data} />;
}

function Stat({ icon: Icon, label, value, hint, tone }: { icon: typeof WalletIcon; label: string; value: string; hint?: string; tone?: "danger" | "success" }) {
  return (
    <Card className="flex flex-col gap-1.5 p-4 sm:p-5">
      <span className="flex items-center gap-2 text-xs font-semibold text-muted-foreground">
        <Icon className="size-4" aria-hidden /> {label}
      </span>
      <span className={cn("text-lg font-extrabold tabular-nums sm:text-xl", tone === "danger" && "text-danger", tone === "success" && "text-success")}>{value}</span>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </Card>
  );
}

function DashboardBody({ planId, s }: { planId: string; s: Summary }) {
  const over = s.status === "OVER" || s.status === "AT_RISK";
  const remaining = s.remaining_min === null ? "—" : s.remaining_min === s.remaining_max ? formatSum(s.remaining_min) : `${formatSum(s.remaining_min)} … ${formatSum(s.remaining_max)}`;
  const maxBar = Math.max(1, ...s.by_category.map((c) => Math.max(n(c.max), n(c.actual))));
  const save = useSaveItem(planId);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2 px-1">
        <BudgetStateBadge state={s.status} />
        <span className="text-sm text-muted-foreground">{BUDGET_STATE[s.status].hint}</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat icon={CalculatorIcon} label="Jami reja (zaxira bilan)" value={formatRange(s.total_min, s.total_max)} hint={`Zaxira ${Number(s.reserve_percent)}%: ${formatRange(s.reserve_min, s.reserve_max)}`} />
        <Stat icon={WalletIcon} label="Byudjet" value={formatSum(s.total_budget)} hint={s.total_budget ? undefined : "Kiritilmagan"} />
        <Stat icon={WalletIcon} label="Qolgan summa" value={remaining} tone={s.remaining_min && s.remaining_min.startsWith("-") ? "danger" : "success"} />
      </div>

      {over && (
        <Card className="flex flex-col gap-3 border-red-500/30">
          <p className="flex items-center gap-2 font-bold text-danger">
            <AlertTriangleIcon className="size-5" aria-hidden />
            Byudjetdan {s.overrun_min === s.overrun_max ? formatSum(s.overrun_max) : `${formatSum(s.overrun_min)} – ${formatSum(s.overrun_max)}`} oshib ketish
          </p>
          <div>
            <p className="mb-1 text-sm font-semibold">Eng katta xarajatlar</p>
            <ul className="flex flex-col gap-1 text-sm">
              {s.biggest_items.map((b, i) => (
                <li key={b.id ?? i} className="flex justify-between gap-3">
                  <span className="truncate">{b.title}</span>
                  <span className="tabular-nums text-muted-foreground">{formatRange(b.min, b.max)}</span>
                </li>
              ))}
            </ul>
          </div>
          {s.cut_suggestions.length > 0 && (
            <div className="flex flex-col gap-2">
              <p className="text-sm font-semibold">Qisqartirish takliflari (siz tanlaysiz — avtomatik qo&apos;llanmaydi)</p>
              {s.cut_suggestions.map((c, i) => (
                <div key={i} className="flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-muted/60 px-3 py-2 text-sm">
                  <span>{c.message}</span>
                  {c.item_id && (
                    <Button
                      size="sm"
                      variant="outline"
                      loading={save.isPending && save.variables?.id === c.item_id}
                      onClick={() =>
                        save.mutate(
                          { id: c.item_id!, body: { is_active: false } },
                          {
                            onSuccess: () => toast.success("Band hisobdan chiqarildi (qayta yoqish mumkin)"),
                            onError: (e) => toast.error(e instanceof ApiError ? e.message : "Saqlab bo'lmadi"),
                          },
                        )
                      }
                    >
                      <ScissorsIcon /> Hisobdan chiqarish
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      <Card className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-bold">Toifalar bo&apos;yicha</h3>
          <span className="flex flex-wrap gap-3 text-xs text-muted-foreground" aria-hidden>
            <Legend className="bg-emerald-500" label="Platforma narxi" />
            <Legend className="bg-amber-400" label="Taxminiy" />
            <Legend className="bg-slate-400/60" label="Oraliq (yuqori chegara)" />
            {s.actual_total && <Legend className="bg-blue-600" label="Haqiqiy to'lov" />}
          </span>
        </div>
        <ul className="flex flex-col gap-3">
          {s.by_category.map((c) => {
            const verified = (n(c.verified) / maxBar) * 100;
            const estimated = (n(c.estimated) / maxBar) * 100;
            const range = Math.max(0, ((n(c.max) - n(c.min)) / maxBar) * 100);
            const actual = (n(c.actual) / maxBar) * 100;
            return (
              <li key={c.category} className="flex flex-col gap-1">
                <div className="flex justify-between gap-3 text-sm">
                  <span className="font-semibold">{c.label}</span>
                  <span className="tabular-nums text-muted-foreground">{formatRange(c.min, c.max)}</span>
                </div>
                <div
                  role="img"
                  aria-label={`${c.label}: reja ${formatRange(c.min, c.max)}, shundan platforma narxi ${formatSum(c.verified)}, taxminiy ${formatSum(c.estimated)}${s.actual_total ? `, haqiqiy ${formatSum(c.actual)}` : ""}`}
                  className="flex h-3 overflow-hidden rounded-full bg-muted"
                >
                  <motion.span className="h-full bg-emerald-500" initial={{ width: 0 }} animate={{ width: `${verified}%` }} transition={{ duration: 0.5 }} />
                  <motion.span className="h-full bg-amber-400" initial={{ width: 0 }} animate={{ width: `${estimated}%` }} transition={{ duration: 0.5 }} />
                  <motion.span className="h-full bg-slate-400/60" initial={{ width: 0 }} animate={{ width: `${range}%` }} transition={{ duration: 0.5 }} />
                </div>
                {s.actual_total && (
                  <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                    <motion.span className="block h-full bg-blue-600" initial={{ width: 0 }} animate={{ width: `${actual}%` }} transition={{ duration: 0.5 }} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
        <p className="text-xs text-muted-foreground">
          Platforma narxi: {formatSum(s.by_price_status.verified)} · Taxminiy: {formatSum(s.by_price_status.estimated)}
          {s.actual_total && <> · Haqiqiy to&apos;langan: {formatSum(s.actual_total)}</>}
        </p>
      </Card>

      {s.warnings.filter((w) => w.code !== "budget_overrun").length > 0 && (
        <ul className="flex flex-col gap-1.5 px-1 text-sm text-muted-foreground">
          {s.warnings
            .filter((w) => w.code !== "budget_overrun")
            .map((w) => (
              <li key={w.code} className="flex gap-2">
                <AlertTriangleIcon className="mt-0.5 size-4 shrink-0 text-amber-500" aria-hidden /> {w.message}
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}

function Legend({ className, label }: { className: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={cn("size-2.5 rounded-full", className)} /> {label}
    </span>
  );
}
