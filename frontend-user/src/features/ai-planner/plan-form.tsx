"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button, cn, Field, Input, Select, Textarea } from "@/components/ui";
import { ApiError } from "@/lib/api";
import type { BudgetFlexibility, EventType, ItemCategory, Plan, PlanInput, PlanStyle } from "@/lib/ai-planner";
import { type Region, REGION_LABELS } from "@/lib/venues";

import { todayIso } from "./bits";
import { CATEGORY_LABELS, EVENT_TYPE_LABELS, ITEM_CATEGORIES, STYLE_LABELS, validatePlanForm } from "./budget";

const PRIORITY_OPTIONS = ITEM_CATEGORIES;

/** Plan details. Validation runs here for quick feedback and again on the server (the source of truth). */
export function PlanForm({
  plan,
  submitLabel,
  pending,
  onSubmit,
  onCancel,
}: {
  plan?: Plan;
  submitLabel: string;
  pending: boolean;
  onSubmit: (values: PlanInput) => Promise<unknown>;
  onCancel?: () => void;
}) {
  const [v, setV] = useState({
    title: plan?.title ?? "",
    event_type: (plan?.event_type ?? "TOY") as EventType,
    event_date: plan?.event_date ?? "",
    date_is_approximate: plan?.date_is_approximate ?? false,
    approximate_date: plan?.approximate_date ?? "",
    region: (plan?.region ?? "") as Region | "",
    district: plan?.district ?? "",
    guest_count: plan?.guest_count ? String(plan.guest_count) : "",
    total_budget: plan?.total_budget ? String(Math.round(Number(plan.total_budget))) : "",
    budget_flexibility: (plan?.budget_flexibility ?? "FLEXIBLE") as BudgetFlexibility,
    style: (plan?.style ?? "STANDARD") as PlanStyle,
    priorities: (plan?.priorities ?? []) as ItemCategory[],
    wishes: plan?.wishes ?? "",
    reserve_percent: plan?.reserve_percent ? String(Number(plan.reserve_percent)) : "7",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = <K extends keyof typeof v>(key: K, value: (typeof v)[K]) => setV((prev) => ({ ...prev, [key]: value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    // A past date is fine on an existing plan (it may already have happened); new plans must look ahead.
    const local = validatePlanForm(v, plan ? "0000-00-00" : todayIso());
    setErrors(local);
    if (Object.keys(local).length) return;
    try {
      await onSubmit({
        title: v.title.trim(),
        event_type: v.event_type,
        event_date: v.event_date || null,
        date_is_approximate: v.date_is_approximate,
        approximate_date: v.approximate_date.trim(),
        region: v.region,
        district: v.district.trim(),
        guest_count: v.guest_count ? Number(v.guest_count) : null,
        total_budget: v.total_budget ? v.total_budget.replace(/\s/g, "") : null,
        budget_flexibility: v.budget_flexibility,
        style: v.style,
        priorities: v.priorities,
        wishes: v.wishes.trim(),
        reserve_percent: v.reserve_percent || "7",
      });
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors);
        toast.error(err.message);
      } else toast.error("Saqlab bo'lmadi");
    }
  };

  return (
    <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2" noValidate>
      <div className="sm:col-span-2">
        <Field label="Reja nomi" htmlFor="pf-title" error={errors.title}>
          <Input id="pf-title" value={v.title} maxLength={150} onChange={(e) => set("title", e.target.value)} placeholder="Masalan: Akmal va Laylo to'yi" aria-invalid={Boolean(errors.title)} />
        </Field>
      </div>
      <Field label="Marosim turi" htmlFor="pf-type" error={errors.event_type}>
        <Select id="pf-type" value={v.event_type} onChange={(e) => set("event_type", e.target.value as EventType)}>
          {Object.entries(EVENT_TYPE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </Select>
      </Field>
      <Field label="Sana" htmlFor="pf-date" error={errors.event_date} hint="Aniq bo'lmasa, taxminiy deb belgilang">
        <Input id="pf-date" type="date" value={v.event_date} onChange={(e) => set("event_date", e.target.value)} aria-invalid={Boolean(errors.event_date)} />
      </Field>
      <label className="flex items-center gap-2 text-sm sm:col-span-2">
        <input type="checkbox" className="size-4 accent-blue-600" checked={v.date_is_approximate} onChange={(e) => set("date_is_approximate", e.target.checked)} />
        Sana taxminiy
      </label>
      {v.date_is_approximate && (
        <div className="sm:col-span-2">
          <Field label="Taxminiy vaqt" htmlFor="pf-approx" error={errors.approximate_date}>
            <Input id="pf-approx" maxLength={60} value={v.approximate_date} onChange={(e) => set("approximate_date", e.target.value)} placeholder="Masalan: 2027 yil bahor" />
          </Field>
        </div>
      )}
      <Field label="Viloyat" htmlFor="pf-region" error={errors.region}>
        <Select id="pf-region" value={v.region} onChange={(e) => set("region", e.target.value as Region | "")}>
          <option value="">Tanlanmagan</option>
          {Object.entries(REGION_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </Select>
      </Field>
      <Field label="Tuman (ixtiyoriy)" htmlFor="pf-district" error={errors.district}>
        <Input id="pf-district" maxLength={100} value={v.district} onChange={(e) => set("district", e.target.value)} />
      </Field>
      <Field label="Mehmonlar soni" htmlFor="pf-guests" error={errors.guest_count}>
        <Input id="pf-guests" type="number" inputMode="numeric" min={1} max={10000} value={v.guest_count} onChange={(e) => set("guest_count", e.target.value)} placeholder="300" aria-invalid={Boolean(errors.guest_count)} />
      </Field>
      <Field label="Umumiy byudjet (so'm)" htmlFor="pf-budget" error={errors.total_budget}>
        <Input id="pf-budget" inputMode="numeric" value={v.total_budget} onChange={(e) => set("total_budget", e.target.value)} placeholder="150000000" aria-invalid={Boolean(errors.total_budget)} />
      </Field>
      <Field label="Byudjet" htmlFor="pf-flex">
        <Select id="pf-flex" value={v.budget_flexibility} onChange={(e) => set("budget_flexibility", e.target.value as BudgetFlexibility)}>
          <option value="FIXED">Qat&apos;iy</option>
          <option value="FLEXIBLE">Moslashuvchan</option>
        </Select>
      </Field>
      <Field label="Uslub" htmlFor="pf-style">
        <Select id="pf-style" value={v.style} onChange={(e) => set("style", e.target.value as PlanStyle)}>
          {Object.entries(STYLE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </Select>
      </Field>
      <Field label="Kutilmagan xarajatlar zaxirasi (%)" htmlFor="pf-reserve" error={errors.reserve_percent} hint="Tavsiya: 5–10%">
        <Input id="pf-reserve" type="number" inputMode="decimal" min={0} max={30} step="0.5" value={v.reserve_percent} onChange={(e) => set("reserve_percent", e.target.value)} />
      </Field>
      <fieldset className="flex flex-col gap-2 sm:col-span-2">
        <legend className="mb-1.5 text-[13px] font-semibold text-foreground/85">Siz uchun eng muhim xizmatlar</legend>
        <div className="flex flex-wrap gap-2">
          {PRIORITY_OPTIONS.map((c) => {
            const on = v.priorities.includes(c);
            return (
              <button
                key={c}
                type="button"
                aria-pressed={on}
                onClick={() => set("priorities", on ? v.priorities.filter((p) => p !== c) : [...v.priorities, c])}
                className={cn("rounded-full px-3 py-1.5 text-xs font-semibold transition", on ? "brand-gradient text-white" : "glass text-muted-foreground hover:text-foreground")}
              >
                {CATEGORY_LABELS[c]}
              </button>
            );
          })}
        </div>
      </fieldset>
      <div className="sm:col-span-2">
        <Field label="Qo'shimcha istaklar" htmlFor="pf-wishes" error={errors.wishes}>
          <Textarea id="pf-wishes" maxLength={2000} value={v.wishes} onChange={(e) => set("wishes", e.target.value)} placeholder="Masalan: jonli musiqa, oq-tilla bezak" />
        </Field>
      </div>
      <div className="flex justify-end gap-2 sm:col-span-2">
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            Bekor qilish
          </Button>
        )}
        <Button type="submit" loading={pending}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
