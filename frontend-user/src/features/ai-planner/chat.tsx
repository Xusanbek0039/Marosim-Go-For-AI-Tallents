"use client";

import {
  AlertTriangleIcon,
  BotIcon,
  CheckIcon,
  FlagIcon,
  Loader2Icon,
  RotateCwIcon,
  SendIcon,
  ShieldAlertIcon,
  SparklesIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
  WrenchIcon,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Card, cn, ErrorState, Field, Modal, Select, Skeleton, Textarea } from "@/components/ui";
import { ApiError } from "@/lib/api";
import {
  type Message,
  useConfirmPlan,
  useMessageFeedback,
  useMessages,
  usePlannerStatus,
  useReportMessage,
  useSendMessage,
} from "@/lib/ai-planner";

import { BudgetStateBadge, useOnline } from "./bits";
import { CATEGORY_LABELS, chatBlockFor, EVENT_TYPE_LABELS, formatRange, formatSum, NOTE_LABELS, UNIT_LABELS } from "./budget";
import { pendingAlreadySaved } from "./pending";

const SUGGESTIONS = [
  "300 kishilik to'y rejalashtirmoqchiman, byudjetim 150 million so'm",
  "Toshkentda sunnat to'yi uchun nimalardan boshlash kerak?",
  "Tug'ilgan kun uchun tejamkor reja tuzib bering",
];

interface Pending {
  content: string;
  key: string;
  error?: ApiError;
}

/** One AI conversation. Everything shown comes from the server; a reload restores the same state. */
export function PlannerChat({ conversationId, onPlanSaved }: { conversationId: string; onPlanSaved?: (planId: string) => void }) {
  const status = usePlannerStatus();
  const messages = useMessages(conversationId);
  const send = useSendMessage(conversationId);
  const online = useOnline();
  const [text, setText] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const history = useMemo(() => (messages.data?.pages ?? []).flatMap((p) => p.results).slice().reverse(), [messages.data]);
  const blockedCode = pending?.error && [503, 429].includes(pending.error.status) ? pending.error.code : status.data && !status.data.available ? status.data.reason : null;
  const block = chatBlockFor(online ? blockedCode : "network_error", status.data?.message);
  const maxChars = status.data?.max_input_chars ?? 2000;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [history.length, send.isPending]);

  const submit = (content: string, key = crypto.randomUUID()) => {
    const value = content.trim();
    if (!value || send.isPending) return;
    setPending({ content: value, key });
    setText("");
    send.mutate(
      { content: value, client_request_id: key },
      {
        onSuccess: () => setPending(null),
        onError: (err) => {
          const error = err instanceof ApiError ? err : new ApiError(0, "network_error", "Xabar yuborilmadi.");
          setPending({ content: value, key, error });
          if (error.code === "validation_error" || error.code === "message_too_long") {
            setText(value);
            setPending(null);
            toast.error(error.message);
          }
        },
      },
    );
  };

  if (messages.isPending || status.isPending)
    return (
      <Card className="flex flex-col gap-3" aria-busy="true">
        <Skeleton className="h-16 w-3/4" />
        <Skeleton className="ml-auto h-12 w-1/2" />
        <Skeleton className="h-24 w-4/5" />
      </Card>
    );
  if (messages.error)
    return (
      <Card>
        <ErrorState error={messages.error} onRetry={() => messages.refetch()} />
      </Card>
    );

  return (
    <Card className="flex flex-col gap-4 p-3 sm:p-5">
      <div className="flex items-center gap-2 px-1">
        <span className="flex size-9 items-center justify-center rounded-2xl brand-gradient text-white">
          <BotIcon className="size-5" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="font-bold">Marosim GO AI Maslahatchisi</p>
          <p className="text-xs text-muted-foreground">Narxlar taxminiy bo&apos;lishi mumkin — har birining manbasi ko&apos;rsatiladi. Bron faqat siz tasdiqlaganingizda.</p>
        </div>
      </div>

      <div className="flex max-h-[62dvh] min-h-64 flex-col gap-3 overflow-y-auto px-1" role="log" aria-live="polite" aria-label="Suhbat">
        {messages.hasNextPage && (
          <Button variant="ghost" size="sm" className="self-center" loading={messages.isFetchingNextPage} onClick={() => messages.fetchNextPage()}>
            Avvalgi xabarlar
          </Button>
        )}
        {history.length === 0 && !pending && (
          <div className="flex flex-col items-center gap-3 py-8 text-center">
            <SparklesIcon className="size-8 text-accent" aria-hidden />
            <p className="max-w-md text-sm text-muted-foreground">
              Assalomu alaykum! Marosimingiz turi, sanasi, viloyati, mehmonlar soni va byudjetini ayting — men reja va taxminiy
              hisob tuzib, platformadagi real to&apos;yxona va studiyalarni taklif qilaman.
            </p>
            {block.kind === "ready" && (
              <div className="flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" onClick={() => submit(s)} className="glass rounded-full px-3 py-1.5 text-xs font-semibold hover:bg-muted">
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {history.map((m) => (m.role === "user" ? <UserBubble key={m.id} message={m} /> : <AssistantBubble key={m.id} message={m} conversationId={conversationId} onPlanSaved={onPlanSaved} />))}
        <AnimatePresence>
          {pending && (
            <motion.div key={pending.key} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="flex flex-col gap-2">
              {!pendingAlreadySaved(history, pending.key) && (
                <p className={cn("ml-auto max-w-[85%] rounded-2xl rounded-br-md px-4 py-2.5 text-sm whitespace-pre-line", pending.error ? "bg-red-500/10" : "brand-gradient text-white")}>
                  {pending.content}
                </p>
              )}
              {pending.error ? (
                <div role="alert" className="ml-auto flex flex-wrap items-center justify-end gap-2 text-xs text-danger">
                  <AlertTriangleIcon className="size-4" aria-hidden /> {pending.error.message}
                  {chatBlockFor(pending.error.code).kind !== "limit" && (
                    <Button size="sm" variant="outline" disabled={!online} onClick={() => submit(pending.content, pending.key)}>
                      <RotateCwIcon /> Qayta yuborish
                    </Button>
                  )}
                </div>
              ) : (
                <p className="flex items-center gap-2 text-xs text-muted-foreground" aria-live="polite">
                  <Loader2Icon className="size-4 animate-spin" aria-hidden /> AI maslahatchi yozmoqda…
                </p>
              )}
            </motion.div>
          )}
        </AnimatePresence>
        <div ref={endRef} />
      </div>

      {block.kind !== "ready" ? (
        <div role="status" className="flex items-start gap-3 rounded-2xl bg-amber-500/10 p-4 text-sm">
          {block.kind === "maintenance" ? <WrenchIcon className="mt-0.5 size-5 shrink-0" aria-hidden /> : <ShieldAlertIcon className="mt-0.5 size-5 shrink-0" aria-hidden />}
          <div className="flex-1">
            <p className="font-bold">{block.title}</p>
            <p className="text-muted-foreground">{block.message}</p>
          </div>
          <Button size="sm" variant="ghost" onClick={() => (setPending(null), status.refetch())}>
            <RotateCwIcon /> Tekshirish
          </Button>
        </div>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit(text);
          }}
          className="flex flex-col gap-1.5"
        >
          <div className="flex items-end gap-2">
            <label htmlFor="ai-input" className="sr-only">
              Xabar
            </label>
            <Textarea
              id="ai-input"
              value={text}
              maxLength={maxChars}
              rows={2}
              className="min-h-12 resize-none"
              placeholder="Savolingizni yozing…"
              disabled={send.isPending}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit(text);
                }
              }}
            />
            <Button type="submit" size="lg" aria-label="Yuborish" loading={send.isPending} disabled={!text.trim()}>
              {!send.isPending && <SendIcon />}
            </Button>
          </div>
          <p className="flex justify-between px-1 text-[11px] text-muted-foreground">
            <span>Karta raqami, CVV yoki SMS kodlarini yozmang.</span>
            <span className="tabular-nums">
              {text.length}/{maxChars}
              {status.data?.daily_limit ? ` · bugun ${status.data.messages_today}/${status.data.daily_limit}` : ""}
            </span>
          </p>
        </form>
      )}
    </Card>
  );
}

function UserBubble({ message }: { message: Message }) {
  return (
    <div className="flex flex-col items-end gap-1">
      <p className="max-w-[85%] rounded-2xl rounded-br-md brand-gradient px-4 py-2.5 text-sm whitespace-pre-line text-white">{message.content}</p>
      {message.structured_data?.sensitive_data_removed && (
        <span className="text-[11px] text-amber-600">To&apos;lov ma&apos;lumotlari olib tashlandi — ularni hech kimga yubormang.</span>
      )}
    </div>
  );
}

function AssistantBubble({ message, conversationId, onPlanSaved }: { message: Message; conversationId: string; onPlanSaved?: (id: string) => void }) {
  const data = message.structured_data ?? {};
  const feedback = useMessageFeedback(conversationId);
  const confirm = useConfirmPlan(conversationId);
  const [askConfirm, setAskConfirm] = useState(false);
  const [reporting, setReporting] = useState(false);
  const hasProposal = message.status === "OK" && Boolean(data.event_plan || (data.budget_items && data.budget_items.length));
  const preview = data.budget_preview;

  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex max-w-[92%] flex-col gap-2">
      <div className={cn("rounded-2xl rounded-bl-md px-4 py-3 text-sm whitespace-pre-line", message.status === "FALLBACK" ? "bg-amber-500/10" : "glass")}>
        {message.content}
        {data.next_question && data.next_question !== message.content && <p className="mt-2 font-semibold">{data.next_question}</p>}
      </div>

      {hasProposal && (
        <div className="flex flex-col gap-2 rounded-2xl border border-cyan-400/30 bg-cyan-500/[0.06] p-3 text-sm">
          {data.event_plan && (
            <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
              {data.event_plan.event_type && <span>{EVENT_TYPE_LABELS[data.event_plan.event_type]}</span>}
              {data.event_plan.guest_count && <span>{data.event_plan.guest_count} mehmon</span>}
              {data.event_plan.total_budget && <span>Byudjet {formatSum(String(data.event_plan.total_budget))}</span>}
              {data.event_plan.event_date && <span>{data.event_plan.event_date}</span>}
            </p>
          )}
          {data.budget_items && data.budget_items.length > 0 && (
            <ul className="flex flex-col gap-1">
              {data.budget_items.map((item, i) => (
                <li key={i} className="flex flex-wrap items-center justify-between gap-2">
                  <span className="flex items-center gap-2">
                    {item.title}
                    <Badge tone={item.service_id ? "success" : "warning"}>{item.service_id ? "Platforma" : "Taxmin"}</Badge>
                  </span>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {item.service_id
                      ? CATEGORY_LABELS[item.category]
                      : `${formatRange(item.unit_price ?? "0", item.unit_price_max ?? item.unit_price ?? "0")} / ${item.per_guest ? "kishi" : UNIT_LABELS[item.unit]}`}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {preview && preview.status !== "NO_ITEMS" && (
            <p className="flex flex-wrap items-center gap-2">
              <BudgetStateBadge state={preview.status} />
              <span>
                Server hisobi: <b className="tabular-nums">{formatRange(preview.total_min, preview.total_max)}</b> (zaxira bilan)
                {preview.status === "OVER" || preview.status === "AT_RISK" ? <> · oshish {formatSum(preview.overrun_max)}</> : null}
              </span>
            </p>
          )}
          {data.confirmed_plan_id ? (
            <Link href={`/ai-reja/${data.confirmed_plan_id}`} className="inline-flex items-center gap-1.5 self-start text-xs font-semibold text-success">
              <CheckIcon className="size-4" aria-hidden /> Rejaga saqlangan — ochish
            </Link>
          ) : (
            <Button size="sm" className="self-start" onClick={() => setAskConfirm(true)}>
              Rejaga saqlash
            </Button>
          )}
        </div>
      )}

      {data.recommended_services && data.recommended_services.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {data.recommended_services.map((s) => (
            <li key={s.id} className="glass flex flex-wrap items-center justify-between gap-2 rounded-2xl px-3 py-2 text-sm">
              <span className="min-w-0 truncate font-semibold">{s.name}</span>
              <span className="text-xs text-muted-foreground tabular-nums">
                {s.price ? `${formatSum(s.price)} dan` : "narx ko'rsatilmagan"}
                {s.rating_avg !== null ? ` · ★ ${s.rating_avg}` : ""}
              </span>
              <Link href={s.url} className="text-xs font-semibold text-brand">
                Sahifasi
              </Link>
            </li>
          ))}
        </ul>
      )}

      {(data.validation_notes ?? []).filter((n) => NOTE_LABELS[n]).length > 0 && (
        <ul className="text-[11px] text-muted-foreground">
          {(data.validation_notes ?? []).filter((n) => NOTE_LABELS[n]).map((n) => (
            <li key={n}>• {NOTE_LABELS[n]}</li>
          ))}
        </ul>
      )}

      <div className="flex items-center gap-1 text-muted-foreground">
        <button type="button" aria-label="Foydali" aria-pressed={message.feedback === "UP"} onClick={() => feedback.mutate({ id: message.id, value: message.feedback === "UP" ? "" : "UP" })} className={cn("rounded-lg p-1.5 hover:bg-muted", message.feedback === "UP" && "text-success")}>
          <ThumbsUpIcon className="size-4" />
        </button>
        <button type="button" aria-label="Foydasiz" aria-pressed={message.feedback === "DOWN"} onClick={() => feedback.mutate({ id: message.id, value: message.feedback === "DOWN" ? "" : "DOWN" })} className={cn("rounded-lg p-1.5 hover:bg-muted", message.feedback === "DOWN" && "text-danger")}>
          <ThumbsDownIcon className="size-4" />
        </button>
        <button type="button" aria-label="Shikoyat qilish" onClick={() => setReporting(true)} className="rounded-lg p-1.5 hover:bg-muted">
          <FlagIcon className="size-4" />
        </button>
      </div>

      <Modal open={askConfirm} onClose={() => setAskConfirm(false)} title="Taklifni rejaga saqlaysizmi?">
        <p className="text-sm text-muted-foreground">
          Reja ma&apos;lumotlari va xarajat bandlari saqlanadi. AI narxlari <b>taxminiy</b> deb belgilanadi, platformadagi xizmatlar narxi
          bazadan qayta o&apos;qiladi. Hech qanday bron yoki to&apos;lov amalga oshirilmaydi.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setAskConfirm(false)}>
            Bekor qilish
          </Button>
          <Button
            loading={confirm.isPending}
            onClick={() =>
              confirm.mutate(message.id, {
                onSuccess: (res) => {
                  setAskConfirm(false);
                  toast.success(res.created ? "Reja saqlandi" : "Bu taklif allaqachon saqlangan");
                  if (res.notes.length) toast.message("Ba'zi bandlar qo'shilmadi (paketda bor yoki xizmat mavjud emas).");
                  onPlanSaved?.(res.plan.id);
                },
                onError: (e) => toast.error(e instanceof ApiError ? e.message : "Saqlab bo'lmadi"),
              })
            }
          >
            Ha, saqlash
          </Button>
        </div>
      </Modal>
      <ReportDialog open={reporting} onClose={() => setReporting(false)} messageId={message.id} />
    </motion.div>
  );
}

const REASONS = [
  ["WRONG_INFO", "Noto'g'ri ma'lumot"],
  ["FAKE_SERVICE", "Mavjud bo'lmagan xizmat"],
  ["WRONG_PRICE", "Noto'g'ri narx"],
  ["OFFENSIVE", "Haqoratli / nomaqbul"],
  ["PRIVACY", "Shaxsiy ma'lumot muammosi"],
  ["OTHER", "Boshqa"],
] as const;

function ReportDialog({ open, onClose, messageId }: { open: boolean; onClose: () => void; messageId: string }) {
  const report = useReportMessage();
  const [reason, setReason] = useState<string>("WRONG_INFO");
  const [description, setDescription] = useState("");
  return (
    <Modal open={open} onClose={onClose} title="Javob ustidan shikoyat">
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          report.mutate(
            { id: messageId, reason, description: description.trim() },
            {
              onSuccess: () => (toast.success("Shikoyat yuborildi. Rahmat!"), onClose()),
              onError: (err) => toast.error(err instanceof ApiError ? err.message : "Yuborilmadi"),
            },
          );
        }}
      >
        <Field label="Sabab" htmlFor="rp-reason">
          <Select id="rp-reason" value={reason} onChange={(e) => setReason(e.target.value)}>
            {REASONS.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </Select>
        </Field>
        <Field label="Izoh (ixtiyoriy)" htmlFor="rp-desc">
          <Textarea id="rp-desc" maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Bekor qilish
          </Button>
          <Button type="submit" loading={report.isPending}>
            Yuborish
          </Button>
        </div>
      </form>
    </Modal>
  );
}
