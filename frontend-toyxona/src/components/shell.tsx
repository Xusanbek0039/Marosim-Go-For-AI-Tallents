"use client";

import {
  BadgeCheckIcon,
  CastleIcon,
  LifeBuoyIcon,
  LogOutIcon,
  MoonIcon,
  SunIcon,
  UserIcon,
  type LucideIcon,
} from "lucide-react";
import { MotionConfig, motion } from "motion/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";
import { toast } from "sonner";

import { BillingBanner } from "./billing-banner";
import { PaidBadge } from "./paid-badge";

import { APP } from "@/lib/app-config";
import { useLogout, useMe } from "@/lib/auth";

import { Avatar, cn } from "./ui";

const useMounted = () =>
  useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );

const SPRING = { type: "spring" as const, stiffness: 420, damping: 34 };

const NAV_ICON: Record<string, LucideIcon> = {
  "/": CastleIcon,
  "/galichka": BadgeCheckIcon,
  "/yordam": LifeBuoyIcon,
  "/profile": UserIcon,
};

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset */}
      <img src="/brand/logo-icon.png" alt="" className="h-8 w-auto" />
      <span className="text-lg font-extrabold tracking-tight">
        Marosim<span className="bg-gradient-to-r from-emerald-600 to-amber-500 bg-clip-text text-transparent">To&apos;yxona</span>
      </span>
    </span>
  );
}

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useMounted();
  const dark = mounted && resolvedTheme === "dark";
  return (
    <motion.button
      type="button"
      whileTap={{ scale: 0.92 }}
      onClick={() => setTheme(dark ? "light" : "dark")}
      aria-label={dark ? "Yorug' rejim" : "Qorong'i rejim"}
      className="glass inline-flex size-10 items-center justify-center rounded-2xl text-muted-foreground transition-colors hover:text-foreground"
    >
      {mounted && (dark ? <SunIcon className="size-4 text-amber-400" /> : <MoonIcon className="size-4 text-emerald-700" />)}
    </motion.button>
  );
}

export interface NavLink {
  href: string;
  label: string;
}

export function Shell({ nav, children }: { nav: NavLink[]; children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { data: me } = useMe();
  const logout = useLogout();

  const doLogout = () =>
    logout.mutate(undefined, {
      onSettled: () => {
        toast.success("Tizimdan chiqdingiz");
        router.replace("/login");
      },
    });

  return (
    <MotionConfig reducedMotion="user">
      <div className="mx-auto flex min-h-dvh w-full max-w-[1320px] gap-6 px-3 pt-3 pb-24 sm:px-6 lg:py-5">
        {/* Desktop Toyxona Sidebar */}
        <aside className="glass sticky top-5 hidden h-[calc(100dvh-2.5rem)] w-64 shrink-0 flex-col gap-5 rounded-[28px] p-4 lg:flex">
          <div className="flex items-center justify-between px-1.5 pt-1">
            <Link href={APP.home} aria-label={`${APP.name} — bosh sahifa`}>
              <Logo />
            </Link>
            <ThemeToggle />
          </div>

          <nav aria-label="To'yxona menyusi" className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pr-1">
            <p className="px-3 pb-1 text-[11px] font-bold tracking-[0.14em] text-muted-foreground uppercase">
              To&apos;yxona kabineti
            </p>
            {nav.map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              const Icon = NAV_ICON[item.href] ?? CastleIcon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "relative flex h-11 items-center gap-3 rounded-2xl px-3.5 text-sm font-semibold transition-colors",
                    active ? "text-white" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  {active && (
                    <motion.span
                      layoutId="toyxona-rail-pill"
                      className="brand-gradient absolute inset-0 rounded-2xl shadow-[0_12px_26px_-12px_rgb(4_120_87/0.8)]"
                      transition={SPRING}
                      aria-hidden
                    />
                  )}
                  <Icon className="relative z-10 size-[18px] shrink-0" aria-hidden />
                  <span className="relative z-10 truncate">{item.label}</span>
                </Link>
              );
            })}
          </nav>

          <div className="flex items-center gap-2 rounded-2xl border border-glass-border bg-muted/50 p-2">
            <Link href="/profile" className="flex min-w-0 flex-1 items-center gap-2.5 rounded-xl p-1 hover:bg-muted">
              {me ? <Avatar first={me.first_name} last={me.last_name} src={me.profile_picture} className="size-9 text-xs" /> : <UserIcon className="size-5" />}
              <div className="min-w-0">
                <p className="truncate text-sm font-bold">
                  {me?.first_name || "Profil"} <PaidBadge verified={me?.is_verified} />
                </p>
                <p className="truncate text-[11px] text-muted-foreground">To&apos;yxona egasi</p>
              </div>
            </Link>
            <button
              type="button"
              aria-label="Chiqish"
              onClick={doLogout}
              className="inline-flex size-9 shrink-0 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-muted hover:text-danger"
            >
              <LogOutIcon className="size-4" />
            </button>
          </div>
        </aside>

        {/* Main Column */}
        <div className="flex min-w-0 flex-1 flex-col gap-5">
          <header className="glass sticky top-3 z-40 flex items-center justify-between gap-2 rounded-2xl px-3.5 py-2.5 lg:hidden">
            <Link href={APP.home} aria-label={`${APP.name} — bosh sahifa`}>
              <Logo />
            </Link>
            <div className="flex items-center gap-1.5">
              <ThemeToggle />
              <Link href="/profile" className="flex items-center gap-2 rounded-2xl p-1 hover:bg-muted" aria-label="Profil">
                {me ? <Avatar first={me.first_name} last={me.last_name} src={me.profile_picture} className="size-8 text-xs" /> : <UserIcon className="size-5" />}
              </Link>
              <button
                type="button"
                aria-label="Chiqish"
                onClick={doLogout}
                className="inline-flex size-9 items-center justify-center rounded-xl text-muted-foreground hover:bg-muted"
              >
                <LogOutIcon className="size-4" />
              </button>
            </div>
          </header>

          <motion.main
            key={pathname}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
            className="flex flex-1 flex-col gap-5"
          >
            <BillingBanner />
            {children}
          </motion.main>
        </div>

        {/* Mobile Floating Bottom Dock */}
        <nav
          aria-label="Mobil menyu"
          className="glass-strong fixed inset-x-3 bottom-3 z-40 flex items-center justify-around gap-1 rounded-3xl px-2 py-1.5 pb-[max(0.375rem,env(safe-area-inset-bottom))] shadow-2xl lg:hidden"
        >
          {nav.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            const Icon = NAV_ICON[item.href] ?? CastleIcon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "relative flex flex-1 flex-col items-center gap-0.5 rounded-2xl py-2 text-[11px] font-semibold transition-colors",
                  active ? "text-white" : "text-muted-foreground",
                )}
              >
                {active && (
                  <motion.span layoutId="toyxona-dock-pill" className="brand-gradient absolute inset-0 rounded-2xl" transition={SPRING} aria-hidden />
                )}
                <Icon className="relative z-10 size-5" aria-hidden />
                <span className="relative z-10 truncate max-w-20">{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </MotionConfig>
  );
}

export function PageTitle({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 px-1">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}
