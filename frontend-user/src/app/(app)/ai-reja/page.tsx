"use client";

import { ArchiveIcon, ArchiveRestoreIcon, CopyIcon, DownloadIcon, MessageSquareIcon, PlusIcon, SparklesIcon, Trash2Icon } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { motion } from "motion/react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";

import { PageTitle } from "@/components/shell";
import { Badge, Button, Card, cn, EmptyState, ErrorState, Modal, Skeleton } from "@/components/ui";
import { BudgetStateBadge, OfflineBanner } from "@/features/ai-planner/bits";
import { EVENT_TYPE_LABELS, formatRange } from "@/features/ai-planner/budget";
import { PlannerChat } from "@/features/ai-planner/chat";
import { PlanForm } from "@/features/ai-planner/plan-form";
import { ApiError } from "@/lib/api";
import {
  type Plan,
  plannerApi,
  plannerKeys,
  useConversationAction,
  useConversations,
  useCreateConversation,
  useCreatePlan,
  usePlanAction,
  usePlannerStatus,
  usePlans,
} from "@/lib/ai-planner";
import { formatDateTime, formatEventDate } from "@/lib/format";

export default function AiPlannerPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 rounded-3xl" />}>
      <AiPlannerHub />
    </Suspense>
  );
}

function AiPlannerHub() {
  const router = useRouter();
  const chatId = useSearchParams().get("suhbat");
  const status = usePlannerStatus();
  const createConversation = useCreateConversation();
  const [creating, setCreating] = useState(false);

  const startChat = () =>
    createConversation.mutate(
      {},
      {
        onSuccess: (c) => router.push(`/ai-reja?suhbat=${c.id}`),
        onError: (e) => toast.error(e instanceof ApiError ? e.message : "Suhbat ochilmadi"),
      },
    );

  if (chatId) {
    return (
      <>
        <PageTitle
          title="AI bilan reja tuzish"
          subtitle="Javoblaringiz asosida reja va taxminiy byudjet tuziladi"
          actions={
            <Link href="/ai-reja" className="inline-flex h-10 items-center rounded-xl px-4 text-sm font-semibold hover:bg-muted">
              Barcha rejalar
            </Link>
          }
        />
        <OfflineBanner />
        <PlannerChat key={chatId} conversationId={chatId} onPlanSaved={(id) => router.push(`/ai-reja/${id}?suhbat=${chatId}`)} />
      </>
    );
  }

  return (
    <>
      <PageTitle
        title="AI marosim rejasi"
        subtitle="Marosim GO AI Maslahatchisi bilan reja, byudjet va platformadagi real xizmatlar"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => setCreating(true)}>
              <PlusIcon /> Qo&apos;lda reja
            </Button>
            <Button onClick={startChat} loading={createConversation.isPending} disabled={status.data ? !status.data.available : false}>
              <SparklesIcon /> AI bilan boshlash
            </Button>
          </div>
        }
      />
      <OfflineBanner />
      {status.data && !status.data.available && (
        <p role="status" className="rounded-2xl bg-amber-500/10 px-4 py-3 text-sm">
          {status.data.message ?? "AI maslahatchi vaqtincha mavjud emas."} Rejalar va byudjet kalkulyatori odatdagidek ishlaydi.
        </p>
      )}
      <PlansSection />
      <ConversationsSection />
      <DataSection />
      <CreatePlanModal open={creating} onClose={() => setCreating(false)} />
    </>
  );
}

function CreatePlanModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const create = useCreatePlan();
  const [requestId] = useState(() => crypto.randomUUID());
  return (
    <Modal open={open} onClose={onClose} title="Yangi reja">
      <PlanForm
        submitLabel="Yaratish"
        pending={create.isPending}
        onCancel={onClose}
        onSubmit={(values) =>
          create.mutateAsync({ ...values, client_request_id: requestId }).then((plan) => {
            toast.success("Reja yaratildi");
            router.push(`/ai-reja/${plan.id}`);
          })
        }
      />
    </Modal>
  );
}

function PlansSection() {
  const [tab, setTab] = useState<"current" | "ARCHIVED">("current");
  const { data, error, isPending, refetch } = usePlans(tab === "ARCHIVED" ? "ARCHIVED" : undefined);
  const action = usePlanAction();
  const [deleting, setDeleting] = useState<Plan | null>(null);
  const plans = (data?.results ?? []).filter((p) => (tab === "ARCHIVED" ? true : p.status !== "ARCHIVED"));
  const run = (id: string, act: "archive" | "unarchive" | "duplicate" | "delete", done: string) =>
    action.mutate({ id, action: act }, { onSuccess: () => toast.success(done), onError: (e) => toast.error(e instanceof ApiError ? e.message : "Amal bajarilmadi") });

  return (
    <section aria-labelledby="plans-title" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <h2 id="plans-title" className="text-lg font-bold">Saqlangan rejalar</h2>
        <div role="tablist" className="flex gap-1 rounded-xl bg-muted p-1">
          {(["current", "ARCHIVED"] as const).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={cn("rounded-lg px-3 py-1 text-sm font-semibold", tab === t ? "brand-gradient text-white" : "text-muted-foreground")}>
              {t === "current" ? "Faol" : "Arxiv"}
            </button>
          ))}
        </div>
      </div>
      {isPending ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Skeleton className="h-36 rounded-3xl" />
          <Skeleton className="h-36 rounded-3xl" />
        </div>
      ) : error ? (
        <Card>
          <ErrorState error={error} onRetry={() => refetch()} />
        </Card>
      ) : plans.length === 0 ? (
        <Card>
          <EmptyState title={tab === "ARCHIVED" ? "Arxiv bo'sh" : "Hali reja yo'q"} description="AI bilan boshlang yoki rejani qo'lda yarating." />
        </Card>
      ) : (
        <motion.ul className="grid gap-3 sm:grid-cols-2" initial="initial" animate="animate">
          {plans.map((p) => (
            <Card key={p.id} className="flex flex-col gap-3 p-4 sm:p-5">
              <Link href={`/ai-reja/${p.id}`} className="flex flex-col gap-1 rounded-xl outline-none focus-visible:ring-4 focus-visible:ring-brand/30">
                <span className="flex flex-wrap items-center gap-2 font-bold">
                  {p.title}
                  {p.source === "AI_CONFIRMED" && <Badge tone="brand">AI</Badge>}
                </span>
                <span className="text-xs text-muted-foreground">
                  {EVENT_TYPE_LABELS[p.event_type]} · {p.event_date ? formatEventDate(p.event_date) : p.approximate_date || "sana kiritilmagan"}
                  {p.guest_count ? ` · ${p.guest_count} mehmon` : ""}
                </span>
                <span className="flex flex-wrap items-center gap-2 text-sm">
                  <BudgetStateBadge state={p.totals.status} />
                  <span className="tabular-nums">{p.item_count ? formatRange(p.totals.total_min, p.totals.total_max) : "Hisob yo'q"}</span>
                </span>
              </Link>
              <div className="flex flex-wrap gap-1.5">
                <Button size="sm" variant="ghost" onClick={() => run(p.id, "duplicate", "Nusxa yaratildi")}>
                  <CopyIcon /> Nusxa
                </Button>
                {p.status === "ARCHIVED" ? (
                  <Button size="sm" variant="ghost" onClick={() => run(p.id, "unarchive", "Arxivdan qaytarildi")}>
                    <ArchiveRestoreIcon /> Qaytarish
                  </Button>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => run(p.id, "archive", "Arxivlandi")}>
                    <ArchiveIcon /> Arxivlash
                  </Button>
                )}
                <Button size="sm" variant="ghost" aria-label="O'chirish" onClick={() => setDeleting(p)}>
                  <Trash2Icon />
                </Button>
              </div>
            </Card>
          ))}
        </motion.ul>
      )}
      <Modal open={Boolean(deleting)} onClose={() => setDeleting(null)} title="Rejani o'chirasizmi?">
        <p className="text-sm text-muted-foreground">&quot;{deleting?.title}&quot; rejasi ro&apos;yxatdan olib tashlanadi. Bronlaringizga ta&apos;sir qilmaydi.</p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setDeleting(null)}>
            Bekor qilish
          </Button>
          <Button variant="danger" loading={action.isPending} onClick={() => deleting && (run(deleting.id, "delete", "Reja o'chirildi"), setDeleting(null))}>
            O&apos;chirish
          </Button>
        </div>
      </Modal>
    </section>
  );
}

function ConversationsSection() {
  const { data, isPending, error, refetch } = useConversations();
  const action = useConversationAction();
  if (isPending) return <Skeleton className="h-24 rounded-3xl" />;
  if (error)
    return (
      <Card>
        <ErrorState error={error} onRetry={() => refetch()} />
      </Card>
    );
  const rows = data.results.filter((c) => c.status === "ACTIVE");
  if (rows.length === 0) return null;
  return (
    <section aria-labelledby="chats-title" className="flex flex-col gap-3">
      <h2 id="chats-title" className="px-1 text-lg font-bold">AI suhbatlar</h2>
      <Card className="p-2 sm:p-3">
        <ul className="flex flex-col">
          {rows.map((c) => (
            <li key={c.id} className="flex items-center justify-between gap-2 rounded-2xl px-2 py-2 hover:bg-muted/60">
              <Link href={c.event_plan ? `/ai-reja/${c.event_plan}?suhbat=${c.id}` : `/ai-reja?suhbat=${c.id}`} className="flex min-w-0 items-center gap-2">
                <MessageSquareIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="truncate text-sm font-semibold">{c.title || "Yangi suhbat"}</span>
                {c.event_plan_title && <Badge tone="brand">{c.event_plan_title}</Badge>}
              </Link>
              <span className="flex shrink-0 items-center gap-1">
                <span className="hidden text-xs text-muted-foreground sm:inline">{formatDateTime(c.last_message_at ?? c.created_at)}</span>
                <Button size="sm" variant="ghost" aria-label="Arxivlash" onClick={() => action.mutate({ id: c.id, action: "archive" })}>
                  <ArchiveIcon />
                </Button>
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}

function DataSection() {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState<"export" | "delete" | null>(null);
  const exportData = async () => {
    setBusy("export");
    try {
      const data = await plannerApi.exportData();
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "marosimgo-ai-reja.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Eksport qilib bo'lmadi");
    } finally {
      setBusy(null);
    }
  };
  return (
    <section className="flex flex-wrap items-center justify-between gap-2 px-1 text-sm text-muted-foreground">
      <span>Ma&apos;lumotlaringiz: rejalar va AI suhbatlar faqat sizga ko&apos;rinadi.</span>
      <span className="flex gap-2">
        <Button size="sm" variant="ghost" loading={busy === "export"} onClick={exportData}>
          <DownloadIcon /> Eksport
        </Button>
        <Button size="sm" variant="danger" onClick={() => setConfirming(true)}>
          <Trash2Icon /> Barchasini o&apos;chirish
        </Button>
      </span>
      <Modal open={confirming} onClose={() => setConfirming(false)} title="AI reja ma'lumotlarini o'chirish">
        <p className="text-sm text-muted-foreground">
          Barcha rejalaringiz, xarajat bandlari va AI suhbatlaringiz butunlay o&apos;chiriladi. Bu amalni qaytarib bo&apos;lmaydi. Bronlar
          va obunalarga ta&apos;sir qilmaydi.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirming(false)}>
            Bekor qilish
          </Button>
          <Button
            variant="danger"
            loading={busy === "delete"}
            onClick={async () => {
              setBusy("delete");
              try {
                await plannerApi.deleteData();
                toast.success("Ma'lumotlar o'chirildi");
                await qc.invalidateQueries({ queryKey: plannerKeys.all });
              } catch (e) {
                toast.error(e instanceof ApiError ? e.message : "O'chirib bo'lmadi");
              } finally {
                setBusy(null);
                setConfirming(false);
              }
            }}
          >
            Ha, o&apos;chirish
          </Button>
        </div>
      </Modal>
    </section>
  );
}
