"use client";

import { CheckCircle2Icon, CircleDashedIcon, CloudOffIcon, SparklesIcon } from "lucide-react";
import { useSyncExternalStore } from "react";

import { Badge } from "@/components/ui";
import { formatDateTime } from "@/lib/format";
import type { BudgetState, PriceStatus, SourceType } from "@/lib/ai-planner";

import { BUDGET_STATE, PRICE_STATUS, SOURCE_LABELS } from "./budget";

export function PriceStatusBadge({ status, checkedAt }: { status: PriceStatus; checkedAt?: string | null }) {
  const meta = PRICE_STATUS[status];
  const Icon = status === "VERIFIED" ? CheckCircle2Icon : status === "ESTIMATED" ? SparklesIcon : CircleDashedIcon;
  return (
    <span title={checkedAt ? `${meta.hint} ${formatDateTime(checkedAt)}` : meta.hint} className="inline-flex">
      <Badge tone={meta.tone}>
        <Icon className="mr-1 size-3" aria-hidden />
        {meta.label}
      </Badge>
    </span>
  );
}

export function SourceLabel({ source }: { source: SourceType }) {
  return <span className="text-xs text-muted-foreground">{SOURCE_LABELS[source]}</span>;
}

export function BudgetStateBadge({ state }: { state: BudgetState }) {
  const meta = BUDGET_STATE[state];
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}

function subscribe(cb: () => void) {
  window.addEventListener("online", cb);
  window.addEventListener("offline", cb);
  return () => {
    window.removeEventListener("online", cb);
    window.removeEventListener("offline", cb);
  };
}

export function useOnline() {
  return useSyncExternalStore(subscribe, () => navigator.onLine, () => true);
}

export function OfflineBanner() {
  const online = useOnline();
  if (online) return null;
  return (
    <p role="status" className="flex items-center gap-2 rounded-2xl bg-amber-500/12 px-4 py-2.5 text-sm font-medium text-amber-800 dark:text-amber-200">
      <CloudOffIcon className="size-4" aria-hidden /> Internet aloqasi yo&apos;q — o&apos;zgarishlar aloqa tiklangach saqlanadi.
    </p>
  );
}

const pad = (n: number) => String(n).padStart(2, "0");
export const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};
