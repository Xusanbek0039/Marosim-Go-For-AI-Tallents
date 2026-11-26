"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";

export type ExpenseCategory = "AI" | "SERVER" | "STORAGE" | "SMS" | "MARKETING" | "SALARY" | "OTHER";

export const EXPENSE_CATEGORIES: Record<ExpenseCategory, string> = {
  SERVER: "Server / hosting",
  STORAGE: "Bulutli xotira (Google Drive)",
  AI: "AI xizmatlari (qo'lda)",
  SMS: "SMS / aloqa",
  MARKETING: "Reklama",
  SALARY: "Ish haqi",
  OTHER: "Boshqa",
};

export interface Expense {
  id: string;
  category: ExpenseCategory;
  title: string;
  amount: string;
  spent_on: string;
  note: string;
  created_by_name: string;
  created_at: string;
}

type Money = number | string;

export interface FinanceReport {
  month: string;
  usd_rate: Money;
  income: { total: Money; by_audience: Record<"USER" | "STUDIO" | "VENUE", { amount: Money; count: number }> };
  expenses: {
    total: Money;
    ai_total: Money;
    manual_total: Money;
    ai: { key: string; label: string; count: number; usd: Money; amount: Money }[];
    manual: { category: ExpenseCategory; label: string; amount: Money }[];
  };
  profit: Money;
  trend: { month: string; income: Money; expense: Money; profit: Money }[];
  receivables: {
    rows: {
      kind: "studio" | "venue";
      id: string;
      name: string;
      state: "GRACE" | "OVERDUE";
      monthly_fee: number;
      paid_until: string | null;
      grace_until: string;
    }[];
    total_due: Money;
    paying_venues: number;
    paying_studios: number;
    monthly_recurring: Money;
  };
  unit_costs: { ai_video: Money; ai_photo: Money; storage_gb_month: Money };
  plans: {
    id: string;
    code: string;
    name: string;
    audience: "USER" | "STUDIO" | "VENUE";
    price: Money;
    duration_months: number;
    ai_video_per_month: number;
    ai_photo_per_month: number;
    price_per_month: Money;
    max_cost_per_month: Money;
    margin: Money;
    healthy: boolean;
  }[];
}

const keys = {
  report: (month: string) => ["finance", "report", month] as const,
  expenses: (month: string) => ["finance", "expenses", month] as const,
};

export function useFinanceReport(month: string) {
  return useQuery({ queryKey: keys.report(month), queryFn: () => api.get<FinanceReport>("/admin/finance/report/", { month }) });
}

export function useExpenses(month: string) {
  return useQuery({ queryKey: keys.expenses(month), queryFn: () => api.get<Expense[]>("/admin/finance/", { month }) });
}

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["finance"] });
}

export function useAddExpense() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: Pick<Expense, "category" | "title" | "amount" | "spent_on" | "note">) => api.post<Expense>("/admin/finance/", body),
    onSuccess: invalidate,
  });
}

export function useDeleteExpense() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (id: string) => api.delete(`/admin/finance/${id}/`), onSuccess: invalidate });
}

export function useUpdateRate() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (usd_rate: string) => api.patch<{ usd_rate: string }>("/admin/finance/rate/", { usd_rate }),
    onSuccess: invalidate,
  });
}
