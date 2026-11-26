"use client";

import {
  BotIcon,
  CalendarCheck2Icon,
  CameraIcon,
  CastleIcon,
  CrownIcon,
  HomeIcon,
  LayoutGridIcon,
  LifeBuoyIcon,
  LogOutIcon,
  MessageCircleIcon,
  MoonIcon,
  ShirtIcon,
  SparklesIcon,
  SunIcon,
  UserIcon,
  XIcon,
  type LucideIcon,
} from "lucide-react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useState, useSyncExternalStore } from "react";
import { toast } from "sonner";

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
  "/": HomeIcon,
  "/ai-reja": BotIcon,
  "/ai-studio": SparklesIcon,
  "/kiyib-korish": ShirtIcon,
  "/toyxonalar": CastleIcon,
  "/studiyalar": CameraIcon,
  "/bronlarim": CalendarCheck2Icon,
  "/xabarlar": MessageCircleIcon,
  "/obuna": CrownIcon,
  "/yordam": LifeBuoyIcon,
  "/profile": UserIcon,
};

const NAV_GROUPS: { title: string; hrefs: string[] }[] = [
  { title: "Asosiy", hrefs: ["/", "/ai-reja", "/ai-studio", "/kiyib-korish"] },
  { title: "Katalog", hrefs: ["/toyxonalar", "/studiyalar", "/bronlarim"] },
  { title: "Shaxsiy", hrefs: ["/xabarlar", "/obuna", "/yordam", "/profile"] },
];

const DOCK_HREFS = ["/", "/ai-reja", "/ai-studio", "/toyxonalar"];

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset */}
      <img src="/brand/logo-icon.png" alt="" className="h-8 w-auto" />
      <span className="text-lg font-extrabold tracking-tight">
        Marosim<span className="bg-gradient-to-r from-rose-600 to-amber-500 bg-clip-text text-transparent">Go</span>
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
      {mounted && (dark ? <SunIcon className="size-4 text-amber-400" /> : <MoonIcon className="size-4 text-rose-600" />)}
    </motion.button>
  );
}

export interface NavLink {
  href: string;
  label: string;
}

function isRouteActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

/**
 * MarosimGo "Silk & Atelier" Shell:
 * - Desktop: calm grouped left sidebar rail with spring active pill (no cramped 11-item top bar).
 * - Mobile: sleek top bar + native-feel floating bottom dock + slide-up "More" drawer.
 */
export function Shell({ nav, children }: { nav: NavLink[]; children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { data: me } = useMe();
  const logout = useLogout();
  const [menuOpen, setMenuOpen] = useState(false);

  const byHref = new Map(nav.map((n) => [n.href, n]));
  const dockItems = DOCK_HREFS.map((h) => byHref.get(h)).filter((x): x is NavLink => !!x);
  const moreItems = nav.filter((item) => !DOCK_HREFS.includes(item.href));

  const doLogout = () =>
    logout.mutate(undefined, {
      onSettled: () => {
        toast.success("Tizimdan chiqdingiz");
        router.replace("/login");
      },
    });

  return (
    <MotionConfig reducedMotion="user">
      <div className="mx-auto flex min-h-dvh w-full max-w-[1340px] gap-6 px-3 pt-3 pb-24 sm:px-6 lg:py-5">
        {/* ------------------------------------------------ Desktop Atelier Sidebar */}
        <aside className="glass sticky top-5 hidden h-[calc(100dvh-2.5rem)] w-64 shrink-0 flex-col gap-5 rounded-[28px] p-4 lg:flex">
          <div className="flex items-center justify-between px-1.5 pt-1">
            <Link href={APP.home} aria-label={`${APP.name} — bosh sahifa`}>
              <Logo />
            </Link>
            <ThemeToggle />
          </div>

          <nav aria-label="Asosiy menyu" className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto pr-1">
            {NAV_GROUPS.map((group) => {
              const items = group.hrefs.map((h) => byHref.get(h)).filter((x): x is NavLink => !!x);
              if (items.length === 0) return null;
              return (
                <div key={group.title} className="flex flex-col gap-1">
                  <p className="px-3 pb-1 text-[11px] font-bold tracking-[0.14em] text-muted-foreground uppercase">
                    {group.title}
                  </p>
                  {items.map((item) => {
                    const active = isRouteActive(pathname, item.href);
                    const Icon = NAV_ICON[item.href] ?? HomeIcon;
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "group relative flex h-11 items-center gap-3 rounded-2xl px-3.5 text-sm font-semibold transition-colors",
                          active ? "text-white" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                        )}
                      >
                        {active && (
                          <motion.span
                            layoutId="atelier-rail-pill"
                            className="brand-gradient absolute inset-0 rounded-2xl shadow-[0_12px_26px_-12px_rgb(190_18_60/0.8)]"
                            transition={SPRING}
                            aria-hidden
                          />
                        )}
                        <Icon className="relative z-10 size-[18px] shrink-0" aria-hidden />
                        <span className="relative z-10 truncate">{item.label}</span>
                        {item.href === "/ai-studio" && !active && (
                          <span className="relative z-10 ml-auto rounded-full bg-rose-500/15 px-2 py-0.5 text-[10px] font-bold text-rose-600 dark:text-rose-300">
                            AI
                          </span>
                        )}
                      </Link>
                    );
                  })}
                </div>
              );
            })}
          </nav>

          {/* Profile footer card */}
          <div className="flex items-center gap-2 rounded-2xl border border-glass-border bg-muted/50 p-2">
            <Link href="/profile" className="flex min-w-0 flex-1 items-center gap-2.5 rounded-xl p-1 hover:bg-muted">
              {me ? (
                <Avatar first={me.first_name} last={me.last_name} src={me.profile_picture} className="size-9 text-xs" />
              ) : (
                <UserIcon className="size-5" />
              )}
              <div className="min-w-0">
                <p className="truncate text-sm font-bold">
                  {me?.first_name || "Profil"} <PaidBadge verified={me?.is_verified} />
                </p>
                <p className="truncate text-[11px] text-muted-foreground">Shaxsiy kabinet</p>
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

        {/* ------------------------------------------------ Main Content Column */}
        <div className="flex min-w-0 flex-1 flex-col gap-5">
          {/* Mobile top header */}
          <header className="glass sticky top-3 z-40 flex items-center justify-between gap-2 rounded-2xl px-3.5 py-2.5 lg:hidden">
            <Link href={APP.home} aria-label={`${APP.name} — bosh sahifa`}>
              <Logo />
            </Link>
            <div className="flex items-center gap-1.5">
              <ThemeToggle />
              <Link
                href="/profile"
                className="flex items-center gap-2 rounded-2xl p-1 pr-2 hover:bg-muted"
                aria-label="Profil"
              >
                {me ? (
                  <Avatar first={me.first_name} last={me.last_name} src={me.profile_picture} className="size-8 text-xs" />
                ) : (
                  <UserIcon className="size-5" />
                )}
              </Link>
            </div>
          </header>

          <motion.main
            key={pathname}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
            className="flex flex-1 flex-col gap-6"
          >
            {children}
          </motion.main>
        </div>

        {/* ------------------------------------------------ Mobile Floating Bottom Dock */}
        <nav
          aria-label="Mobil navigatsiya"
          className="glass-strong fixed inset-x-3 bottom-3 z-40 flex items-center justify-around rounded-3xl px-2 py-1.5 pb-[max(0.375rem,env(safe-area-inset-bottom))] shadow-2xl lg:hidden"
        >
          {dockItems.map((item) => {
            const active = isRouteActive(pathname, item.href);
            const Icon = NAV_ICON[item.href] ?? HomeIcon;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative flex flex-1 flex-col items-center gap-0.5 rounded-2xl py-2 text-[11px] font-semibold transition-colors",
                  active ? "text-white" : "text-muted-foreground",
                )}
              >
                {active && (
                  <motion.span
                    layoutId="atelier-dock-pill"
                    className="brand-gradient absolute inset-0 rounded-2xl"
                    transition={SPRING}
                    aria-hidden
                  />
                )}
                <Icon className="relative z-10 size-5" aria-hidden />
                <span className="relative z-10 truncate max-w-16">
                  {item.href === "/" ? "Asosiy" : item.label}
                </span>
              </Link>
            );
          })}
          <button
            type="button"
            onClick={() => setMenuOpen(true)}
            className="relative flex flex-1 flex-col items-center gap-0.5 rounded-2xl py-2 text-[11px] font-semibold text-muted-foreground"
          >
            <LayoutGridIcon className="size-5" aria-hidden />
            <span>Bo&apos;limlar</span>
          </button>
        </nav>

        {/* ------------------------------------------------ Mobile "More" Sheet */}
        <AnimatePresence>
          {menuOpen && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-50 flex items-end bg-black/60 p-3 backdrop-blur-sm lg:hidden"
              onClick={() => setMenuOpen(false)}
            >
              <motion.div
                initial={{ y: 60, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                exit={{ y: 60, opacity: 0 }}
                transition={SPRING}
                onClick={(e) => e.stopPropagation()}
                className="glass-strong w-full rounded-3xl p-4 pb-[max(1rem,env(safe-area-inset-bottom))]"
              >
                <div className="mb-3 flex items-center justify-between px-1">
                  <p className="text-sm font-extrabold">Barcha bo&apos;limlar</p>
                  <button
                    type="button"
                    onClick={() => setMenuOpen(false)}
                    aria-label="Yopish"
                    className="rounded-xl p-1.5 text-muted-foreground hover:bg-muted"
                  >
                    <XIcon className="size-5" />
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {moreItems.map((item) => {
                    const active = isRouteActive(pathname, item.href);
                    const Icon = NAV_ICON[item.href] ?? HomeIcon;
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        onClick={() => setMenuOpen(false)}
                        className={cn(
                          "flex items-center gap-2.5 rounded-2xl p-3 text-sm font-semibold transition-colors",
                          active ? "brand-gradient text-white" : "bg-muted/60 text-foreground hover:bg-muted",
                        )}
                      >
                        <Icon className="size-4 shrink-0" />
                        <span className="truncate">{item.label}</span>
                      </Link>
                    );
                  })}
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    doLogout();
                  }}
                  className="mt-3 flex w-full items-center justify-center gap-2 rounded-2xl bg-red-500/10 py-3 text-sm font-bold text-danger"
                >
                  <LogOutIcon className="size-4" /> Tizimdan chiqish
                </button>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </MotionConfig>
  );
}

export function PageTitle({
  title,
  subtitle,
  action,
  actions,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {actions ?? action}
    </div>
  );
}
