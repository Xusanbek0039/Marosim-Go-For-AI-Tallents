"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArchiveIcon, BellIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { formatEventDate } from "@/lib/format";

import { cn } from "./ui";

type Notification = { id: string; kind: string; title: string; body: string; link: string; read_at: string | null; created_at: string };
type Backup = { status: "NO_VIDEO" | "TRIAL" | "PREMIUM" | "BACKUP"; in_backup: boolean; grace_ends_at: string | null; premium_until: string | null };

const KEY = ["me", "notifications"] as const;

function useNotifications() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<Notification[]>("/me/notifications/"), refetchInterval: 60_000 });
}

/** Bell with the unread count and a dropdown list (Backup / Premium notifications). */
export function NotificationBell() {
  const qc = useQueryClient();
  const { data } = useNotifications();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const readAll = useMutation({
    mutationFn: () => api.post("/me/notifications/read-all/"),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  const unread = (data ?? []).filter((n) => !n.read_at).length;

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen((o) => !o);
          if (!open && unread) readAll.mutate();
        }}
        className="relative flex size-9 items-center justify-center rounded-xl hover:bg-muted"
        aria-label={unread ? `Bildirishnomalar: ${unread} ta yangi` : "Bildirishnomalar"}
        aria-expanded={open}
      >
        <BellIcon className="size-5" aria-hidden />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex min-w-4.5 items-center justify-center rounded-full bg-rose-600 px-1 text-[10px] font-bold text-white">
            {unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute top-11 right-0 z-50 w-80 max-w-[calc(100vw-2rem)] rounded-2xl border border-border bg-background p-2 shadow-2xl">
          <p className="px-2 py-1.5 text-sm font-bold">Bildirishnomalar</p>
          {!data || data.length === 0 ? (
            <p className="px-2 py-4 text-sm text-muted-foreground">Hozircha bildirishnoma yo&apos;q.</p>
          ) : (
            <ul className="flex max-h-96 flex-col gap-1 overflow-y-auto">
              {data.map((n) => (
                <li key={n.id}>
                  <Link
                    href={n.link || "#"}
                    onClick={() => setOpen(false)}
                    className={cn("block rounded-xl p-2.5 hover:bg-muted", !n.read_at && "bg-brand/10")}
                  >
                    <p className="text-sm font-semibold">{n.title}</p>
                    {n.body && <p className="mt-0.5 text-xs text-muted-foreground">{n.body}</p>}
                    <p className="mt-1 text-[11px] text-muted-foreground">{formatEventDate(n.created_at.slice(0, 10))}</p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** Shown on every page while the account is in Backup mode. */
export function BackupBanner() {
  const { data } = useQuery({ queryKey: ["me", "backup"], queryFn: () => api.get<Backup>("/me/backup/"), refetchInterval: 5 * 60_000 });
  if (!data?.in_backup) return null;
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
      <ArchiveIcon className="size-5 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />
      <p className="min-w-60 flex-1">
        <b>Akkauntingiz Backup rejimida.</b> Bepul muddat tugadi. Video va rasmlaringiz o&apos;chirilmagan, xavfsiz saqlanmoqda,
        lekin ularni Premium obuna bilan qayta ko&apos;rasiz.
      </p>
      <Link href="/obuna" className="inline-flex h-10 items-center rounded-xl bg-gradient-to-r from-amber-400 to-orange-500 px-4 text-sm font-bold text-white">
        Premium olish
      </Link>
    </div>
  );
}
