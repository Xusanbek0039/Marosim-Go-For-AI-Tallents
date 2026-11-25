"use client";

import { ArrowLeftIcon, MessageSquareIcon } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { toast } from "sonner";

import { PageTitle } from "@/components/shell";
import { Button, Card, cn, ErrorState, Skeleton } from "@/components/ui";
import { OfflineBanner } from "@/features/ai-planner/bits";
import { BudgetDashboard } from "@/features/ai-planner/budget-dashboard";
import { EVENT_TYPE_LABELS } from "@/features/ai-planner/budget";
import { PlannerChat } from "@/features/ai-planner/chat";
import { ItemsEditor } from "@/features/ai-planner/items-editor";
import { PlanForm } from "@/features/ai-planner/plan-form";
import { Recommendations } from "@/features/ai-planner/recommendations";
import { ApiError } from "@/lib/api";
import { useConversations, useCreateConversation, usePlan, usePlannerStatus, useUpdatePlan } from "@/lib/ai-planner";
import { formatEventDate } from "@/lib/format";
import { usePathId } from "@/lib/path-id";

const TABS = [
  { key: "byudjet", label: "Byudjet" },
  { key: "reja", label: "Reja" },
  { key: "tavsiyalar", label: "Xizmatlar" },
  { key: "suhbat", label: "AI suhbat" },
] as const;
type Tab = (typeof TABS)[number]["key"];

export function PlanWorkspace() {
  return (
    <Suspense fallback={<Skeleton className="h-64 rounded-3xl" />}>
      <Workspace />
    </Suspense>
  );
}

function Workspace() {
  const id = usePathId();
  const router = useRouter();
  const params = useSearchParams();
  const chatParam = params.get("suhbat");
  const tab = (params.get("tab") as Tab | null) ?? (chatParam ? "suhbat" : "byudjet");
  const { data: plan, error, isPending, refetch } = usePlan(id);
  const update = useUpdatePlan(id);

  const go = (next: Tab) => {
    const q = new URLSearchParams(params.toString());
    q.set("tab", next);
    router.replace(`/ai-reja/${id}?${q.toString()}`, { scroll: false });
  };

  if (isPending) return <Skeleton className="h-64 rounded-3xl" />;
  if (error)
    return (
      <Card>
        <ErrorState error={error} onRetry={() => refetch()} />
      </Card>
    );

  return (
    <>
      <Link href="/ai-reja" className="inline-flex items-center gap-1.5 self-start px-1 text-sm font-semibold text-muted-foreground hover:text-foreground">
        <ArrowLeftIcon className="size-4" aria-hidden /> Barcha rejalar
      </Link>
      <PageTitle
        title={plan.title}
        subtitle={`${EVENT_TYPE_LABELS[plan.event_type]} · ${plan.event_date ? formatEventDate(plan.event_date) : plan.approximate_date || "sana kiritilmagan"}${plan.guest_count ? ` · ${plan.guest_count} mehmon` : ""}`}
      />
      <OfflineBanner />
      {plan.status === "ARCHIVED" && <p className="rounded-2xl bg-muted px-4 py-2.5 text-sm">Bu reja arxivda. Uni &quot;Reja&quot; bo&apos;limidan qayta faollashtirishingiz mumkin.</p>}
      <div role="tablist" aria-label="Reja bo'limlari" className="glass flex gap-1 overflow-x-auto rounded-2xl p-1 [scrollbar-width:none]">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => go(t.key)}
            className={cn("flex-1 shrink-0 rounded-xl px-3 py-2 text-sm font-semibold whitespace-nowrap", tab === t.key ? "brand-gradient text-white" : "text-muted-foreground")}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "byudjet" && (
        <>
          <BudgetDashboard planId={plan.id} />
          <ItemsEditor plan={plan} />
        </>
      )}
      {tab === "reja" && (
        <Card>
          <PlanForm
            key={plan.updated_at}
            plan={plan}
            submitLabel="Saqlash"
            pending={update.isPending}
            onSubmit={(values) => update.mutateAsync(values).then(() => toast.success("Reja saqlandi — byudjet qayta hisoblandi"))}
          />
          <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4">
            {(["DRAFT", "ACTIVE", "COMPLETED"] as const).map((s) => (
              <Button key={s} size="sm" variant={plan.status === s ? "primary" : "outline"} onClick={() => update.mutate({ status: s })}>
                {s === "DRAFT" ? "Qoralama" : s === "ACTIVE" ? "Faol" : "Yakunlangan"}
              </Button>
            ))}
          </div>
        </Card>
      )}
      {tab === "tavsiyalar" && <Recommendations plan={plan} />}
      {tab === "suhbat" && <PlanChat planId={plan.id} chatParam={chatParam} />}
    </>
  );
}

/** The plan's own conversation: the one in the URL, else the latest one linked to this plan, else a new one. */
function PlanChat({ planId, chatParam }: { planId: string; chatParam: string | null }) {
  const router = useRouter();
  const status = usePlannerStatus();
  const conversations = useConversations();
  const create = useCreateConversation();
  if (conversations.isPending) return <Skeleton className="h-64 rounded-3xl" />;
  const linked = conversations.data?.results.find((c) => c.event_plan === planId && c.status === "ACTIVE");
  const conversationId = chatParam ?? linked?.id ?? null;
  if (conversationId) return <PlannerChat key={conversationId} conversationId={conversationId} />;
  return (
    <Card className="flex flex-col items-center gap-3 py-10 text-center">
      <MessageSquareIcon className="size-8 text-accent" aria-hidden />
      <p className="max-w-sm text-sm text-muted-foreground">AI maslahatchi bu reja ma&apos;lumotlari bilan ishlaydi: savol bering, byudjetni tahlil qildiring.</p>
      <Button
        loading={create.isPending}
        disabled={status.data ? !status.data.available : false}
        onClick={() =>
          create.mutate(
            { event_plan: planId },
            {
              onSuccess: (c) => router.replace(`/ai-reja/${planId}?tab=suhbat&suhbat=${c.id}`),
              onError: (e) => toast.error(e instanceof ApiError ? e.message : "Suhbat ochilmadi"),
            },
          )
        }
      >
        Suhbatni boshlash
      </Button>
      {status.data && !status.data.available && <p className="text-xs text-muted-foreground">{status.data.message}</p>}
    </Card>
  );
}
