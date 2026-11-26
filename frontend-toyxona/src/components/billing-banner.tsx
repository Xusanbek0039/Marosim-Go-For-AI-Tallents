"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangleIcon, EyeOffIcon } from "lucide-react";
import Link from "next/link";

import { api } from "@/lib/api";
import { formatEventDate } from "@/lib/format";

export type BusinessBilling = {
  kind: "studio" | "venue";
  id: string;
  name: string;
  state: "OK" | "GRACE" | "OVERDUE";
  monthly_fee: number;
  paid_until: string | null;
  grace_until: string;
  visible: boolean;
};

export const money = (v: number | string) => `${String(Math.round(Number(v))).replace(/\B(?=(\d{3})+(?!\d))/g, " ")} so'm`;

export function useBilling() {
  return useQuery({
    queryKey: ["business-billing"],
    queryFn: () => api.get<BusinessBilling[]>("/me/subscriptions/billing/"),
    refetchInterval: 5 * 60_000,
  });
}

/** Mandatory monthly fee reminder: amber during the 7-day grace, red once hidden from the catalog. */
export function BillingBanner() {
  const { data } = useBilling();
  const due = (data ?? []).filter((b) => b.state !== "OK");
  if (due.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      {due.map((b) => {
        const overdue = b.state === "OVERDUE";
        const Icon = overdue ? EyeOffIcon : AlertTriangleIcon;
        return (
          <div
            key={b.id}
            role="alert"
            className={
              overdue
                ? "flex flex-wrap items-center gap-3 rounded-2xl border border-red-500/40 bg-red-500/10 p-4 text-sm"
                : "flex flex-wrap items-center gap-3 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm"
            }
          >
            <Icon className={overdue ? "size-5 shrink-0 text-red-600 dark:text-red-400" : "size-5 shrink-0 text-amber-600 dark:text-amber-400"} aria-hidden />
            <p className="min-w-60 flex-1">
              <b>{b.name}:</b>{" "}
              {overdue
                ? `katalogdan yashirildi — mijozlar sizni ko'rmayapti. Oylik to'lov (${money(b.monthly_fee)}) qilinsa darhol qaytadi.`
                : `oylik majburiy to'lov ${money(b.monthly_fee)}. ${formatEventDate(b.grace_until.slice(0, 10))} gacha to'lanmasa, katalogdan yashiriladi.`}
            </p>
            <Link
              href="/galichka"
              className="inline-flex h-9 items-center rounded-xl bg-gradient-to-r from-indigo-500 to-fuchsia-500 px-4 text-sm font-bold text-white"
            >
              To&apos;lash
            </Link>
          </div>
        );
      })}
    </div>
  );
}
