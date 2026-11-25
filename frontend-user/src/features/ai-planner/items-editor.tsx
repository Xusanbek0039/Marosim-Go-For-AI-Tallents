"use client";

import { PencilIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, Select, Skeleton, Textarea } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { type BudgetItem, type ItemCategory, type ItemInput, type Plan, type Unit, useDeleteItem, useItems, useSaveItem } from "@/lib/ai-planner";
import { formatDateTime } from "@/lib/format";

import { PriceStatusBadge, SourceLabel } from "./bits";
import { CATEGORY_LABELS, formatRange, ITEM_CATEGORIES, parseMoney, previewLine, UNIT_LABELS } from "./budget";

/** Budget lines grouped by category. Totals shown are the server's; the form only previews while typing. */
export function ItemsEditor({ plan }: { plan: Plan }) {
  const { data, error, isPending, refetch } = useItems(plan.id);
  const remove = useDeleteItem(plan.id);
  const save = useSaveItem(plan.id);
  const [editing, setEditing] = useState<BudgetItem | "new" | null>(null);
  const [deleting, setDeleting] = useState<BudgetItem | null>(null);

  if (isPending) return <Skeleton className="h-48 rounded-3xl" />;
  if (error)
    return (
      <Card>
        <ErrorState error={error} onRetry={() => refetch()} />
      </Card>
    );

  const groups = ITEM_CATEGORIES.map((c) => ({ category: c, items: data.filter((i) => i.category === c) })).filter((g) => g.items.length);

  return (
    <Card className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-bold">Xarajat bandlari</h3>
        <Button size="sm" onClick={() => setEditing("new")}>
          <PlusIcon /> Band qo&apos;shish
        </Button>
      </div>
      {groups.length === 0 ? (
        <EmptyState title="Bandlar yo'q" description="To'yxona, dasturxon, foto-video va boshqa xarajatlarni qo'shing." />
      ) : (
        groups.map((g) => (
          <section key={g.category} aria-label={CATEGORY_LABELS[g.category]} className="flex flex-col gap-2">
            <h4 className="text-xs font-bold tracking-wide text-muted-foreground uppercase">{CATEGORY_LABELS[g.category]}</h4>
            <ul className="flex flex-col gap-2">
              {g.items.map((item) => (
                <li key={item.id} className={`flex flex-col gap-2 rounded-2xl bg-muted/50 p-3 sm:flex-row sm:items-center sm:justify-between ${item.is_active ? "" : "opacity-60"}`}>
                  <div className="flex min-w-0 flex-col gap-1">
                    <span className="flex flex-wrap items-center gap-2 font-semibold">
                      <span className="truncate">{item.title}</span>
                      <PriceStatusBadge status={item.price_status} checkedAt={item.price_checked_at} />
                      {item.is_included_in_package && <Badge tone="brand">Paketda</Badge>}
                      {!item.is_active && <Badge>Hisobdan chiqarilgan</Badge>}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {item.per_guest ? `kishi boshiga × ${plan.guest_count ?? "?"} mehmon` : `${Number(item.quantity)} ${UNIT_LABELS[item.unit]}`} ·{" "}
                      {formatRange(item.unit_price, item.unit_price_max ?? item.unit_price)} dan · <SourceLabel source={item.source_type} />
                      {item.price_checked_at && <> · tekshirilgan {formatDateTime(item.price_checked_at)}</>}
                    </span>
                    {item.source_kind === "VENUE_HALL" && item.notes === "" && (
                      <span className="text-xs text-muted-foreground">Boshlang&apos;ich narx — to&apos;yxona tasdig&apos;igacha o&apos;zgarishi mumkin.</span>
                    )}
                    {item.notes && <span className="text-xs whitespace-pre-line text-muted-foreground">{item.notes}</span>}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="font-bold tabular-nums">{formatRange(item.total_price, item.total_price_max)}</span>
                    <Button size="sm" variant="ghost" aria-label={item.is_active ? "Hisobdan chiqarish" : "Hisobga qaytarish"}
                      onClick={() => save.mutate({ id: item.id, body: { is_active: !item.is_active } }, { onError: (e) => toast.error(e instanceof ApiError ? e.message : "Saqlab bo'lmadi") })}>
                      {item.is_active ? "O'chirish" : "Yoqish"}
                    </Button>
                    <Button size="sm" variant="ghost" aria-label="Tahrirlash" onClick={() => setEditing(item)}>
                      <PencilIcon />
                    </Button>
                    <Button size="sm" variant="ghost" aria-label="O'chirish" onClick={() => setDeleting(item)}>
                      <Trash2Icon />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}

      <Modal open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? "Yangi band" : "Bandni tahrirlash"}>
        {editing !== null && <ItemForm key={editing === "new" ? "new" : editing.id} plan={plan} item={editing === "new" ? null : editing} onDone={() => setEditing(null)} />}
      </Modal>
      <Modal open={deleting !== null} onClose={() => setDeleting(null)} title="Bandni o'chirasizmi?">
        <p className="text-sm text-muted-foreground">&quot;{deleting?.title}&quot; rejadan butunlay o&apos;chiriladi. Faqat hisobdan chiqarish uchun &quot;O&apos;chirish&quot; tugmasidan foydalaning.</p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setDeleting(null)}>
            Bekor qilish
          </Button>
          <Button
            variant="danger"
            loading={remove.isPending}
            onClick={() =>
              deleting &&
              remove.mutate(deleting.id, {
                onSuccess: () => (toast.success("Band o'chirildi"), setDeleting(null)),
                onError: (e) => toast.error(e instanceof ApiError ? e.message : "O'chirib bo'lmadi"),
              })
            }
          >
            O&apos;chirish
          </Button>
        </div>
      </Modal>
    </Card>
  );
}

function ItemForm({ plan, item, onDone }: { plan: Plan; item: BudgetItem | null; onDone: () => void }) {
  const save = useSaveItem(plan.id);
  const platform = item?.source_type === "PLATFORM_SERVICE";
  const hall = item?.source_kind === "VENUE_HALL";
  const [v, setV] = useState({
    category: (item?.category ?? "FOOD") as ItemCategory,
    title: item?.title ?? "",
    per_guest: item?.per_guest ?? false,
    quantity: item ? String(Number(item.quantity)) : "1",
    unit: (item?.unit ?? "SERVICE") as Unit,
    unit_price: item ? String(Number(item.unit_price)) : "",
    unit_price_max: item?.unit_price_max ? String(Number(item.unit_price_max)) : "",
    is_included_in_package: item?.is_included_in_package ?? false,
    package_includes: item?.package_includes ?? [],
    actual_amount: item?.actual_amount ? String(Number(item.actual_amount)) : "",
    notes: item?.notes ?? "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = <K extends keyof typeof v>(key: K, value: (typeof v)[K]) => setV((p) => ({ ...p, [key]: value }));
  const [requestId] = useState(() => crypto.randomUUID());

  const preview = previewLine({
    unitPrice: v.unit_price || "0",
    unitPriceMax: v.unit_price_max,
    quantity: v.quantity,
    perGuest: v.per_guest,
    guests: plan.guest_count,
    included: v.is_included_in_package,
    active: item?.is_active ?? true,
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const local: Record<string, string> = {};
    if (!platform && !v.title.trim()) local.title = "Nomini kiriting.";
    if (!hall && v.unit_price && parseMoney(v.unit_price) === null) local.unit_price = "Narx manfiy bo'lmagan son bo'lishi kerak.";
    if (v.unit_price_max && (parseMoney(v.unit_price_max) ?? BigInt(-1)) < (parseMoney(v.unit_price || "0") ?? BigInt(0))) local.unit_price_max = "Yuqori narx pastki narxdan kam bo'lmasin.";
    if (!v.per_guest && !hall && !(Number(v.quantity) > 0)) local.quantity = "Miqdor 0 dan katta bo'lishi kerak.";
    if (v.actual_amount && parseMoney(v.actual_amount) === null) local.actual_amount = "Noto'g'ri summa.";
    setErrors(local);
    if (Object.keys(local).length) return;
    const body: ItemInput = hall
      ? { title: v.title.trim(), notes: v.notes.trim(), package_includes: v.package_includes, actual_amount: v.actual_amount || null }
      : {
          ...(platform ? {} : { category: v.category }),
          title: v.title.trim(),
          per_guest: v.per_guest,
          quantity: v.per_guest ? "1" : v.quantity,
          unit: v.per_guest ? "PERSON" : v.unit,
          unit_price: v.unit_price || "0",
          unit_price_max: v.unit_price_max || null,
          is_included_in_package: v.is_included_in_package,
          actual_amount: v.actual_amount || null,
          notes: v.notes.trim(),
          ...(item ? {} : { source_type: "USER_INPUT" as const, client_request_id: requestId }),
        };
    save.mutate(
      { id: item?.id, body },
      {
        onSuccess: () => (toast.success("Saqlandi"), onDone()),
        onError: (err) => {
          if (err instanceof ApiError) {
            setErrors(err.fieldErrors);
            toast.error(err.message);
          } else toast.error("Saqlab bo'lmadi");
        },
      },
    );
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
      {!platform && (
        <Field label="Toifa" htmlFor="it-cat" error={errors.category}>
          <Select id="it-cat" value={v.category} onChange={(e) => set("category", e.target.value as ItemCategory)}>
            {ITEM_CATEGORIES.map((c) => (
              <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>
            ))}
          </Select>
        </Field>
      )}
      <Field label="Nomi" htmlFor="it-title" error={errors.title}>
        <Input id="it-title" maxLength={150} value={v.title} onChange={(e) => set("title", e.target.value)} aria-invalid={Boolean(errors.title)} />
      </Field>
      {hall ? (
        <>
          <p className="rounded-2xl bg-emerald-500/10 p-3 text-sm">
            Zal narxi platformadan olinadi va bu yerda o&apos;zgartirilmaydi (boshlang&apos;ich narx, to&apos;yxona tasdig&apos;igacha
            o&apos;zgarishi mumkin).
          </p>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-[13px] font-semibold">To&apos;yxona paketiga kiradi (ikki marta hisoblanmaydi)</legend>
            <div className="flex flex-wrap gap-2">
              {ITEM_CATEGORIES.filter((c) => c !== "VENUE").map((c) => {
                const on = v.package_includes.includes(c);
                return (
                  <label key={c} className="flex items-center gap-1.5 rounded-full bg-muted px-3 py-1.5 text-xs font-semibold">
                    <input type="checkbox" className="accent-blue-600" checked={on} onChange={() => set("package_includes", on ? v.package_includes.filter((p) => p !== c) : [...v.package_includes, c])} />
                    {CATEGORY_LABELS[c]}
                  </label>
                );
              })}
            </div>
          </fieldset>
        </>
      ) : (
        <>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="size-4 accent-blue-600" checked={v.per_guest} onChange={(e) => set("per_guest", e.target.checked)} />
            Kishi boshiga (mehmonlar soniga ko&apos;paytiriladi{plan.guest_count ? `: ${plan.guest_count}` : " — mehmonlar sonini kiriting"})
          </label>
          {!v.per_guest && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Miqdor" htmlFor="it-qty" error={errors.quantity}>
                <Input id="it-qty" type="number" inputMode="decimal" min={0.01} step="0.01" value={v.quantity} onChange={(e) => set("quantity", e.target.value)} />
              </Field>
              <Field label="Birlik" htmlFor="it-unit">
                <Select id="it-unit" value={v.unit} onChange={(e) => set("unit", e.target.value as Unit)}>
                  {Object.entries(UNIT_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </Select>
              </Field>
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Narx (so'm)" htmlFor="it-price" error={errors.unit_price}>
              <Input id="it-price" inputMode="numeric" value={v.unit_price} onChange={(e) => set("unit_price", e.target.value)} placeholder="0" />
            </Field>
            <Field label="Yuqori narx (oraliq)" htmlFor="it-price-max" error={errors.unit_price_max} hint="Ixtiyoriy">
              <Input id="it-price-max" inputMode="numeric" value={v.unit_price_max} onChange={(e) => set("unit_price_max", e.target.value)} />
            </Field>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="size-4 accent-blue-600" checked={v.is_included_in_package} onChange={(e) => set("is_included_in_package", e.target.checked)} />
            To&apos;yxona paketiga kiritilgan (0 so&apos;m deb hisoblanadi)
          </label>
        </>
      )}
      <Field label="Haqiqatda to'langan (ixtiyoriy)" htmlFor="it-actual" error={errors.actual_amount}>
        <Input id="it-actual" inputMode="numeric" value={v.actual_amount} onChange={(e) => set("actual_amount", e.target.value)} />
      </Field>
      <Field label="Izoh" htmlFor="it-notes" error={errors.notes}>
        <Textarea id="it-notes" maxLength={1000} value={v.notes} onChange={(e) => set("notes", e.target.value)} />
      </Field>
      {!hall && (
        <p className="rounded-2xl bg-muted/60 px-3 py-2 text-sm" aria-live="polite">
          {preview ? <>Taxminiy jami: <b className="tabular-nums">≈ {formatRange(preview.min, preview.max)}</b> (saqlangach server hisoblaydi)</> : "Jami summani ko'rish uchun narx va miqdorni to'g'ri kiriting."}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onDone}>
          Bekor qilish
        </Button>
        <Button type="submit" loading={save.isPending}>
          Saqlash
        </Button>
      </div>
    </form>
  );
}
