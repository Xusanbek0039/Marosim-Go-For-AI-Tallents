"use client";

import {
  CameraIcon,
  CheckCircle2Icon,
  ChevronLeftIcon,
  ChevronRightIcon,
  DownloadIcon,
  HelpCircleIcon,
  PlayIcon,
  ShirtIcon,
  ShoppingBagIcon,
  SparklesIcon,
  SunIcon,
  VideoIcon,
  XIcon,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Button, cn } from "@/components/ui";

interface GuideStep {
  badge: string;
  title: string;
  description: string;
  tips: string[];
  visual: React.ReactNode;
}

const STEPS: GuideStep[] = [
  {
    badge: "1-qadam",
    title: "Katalogdan libos tanlang",
    description:
      "Sahifadagi «AI uchun kiyimlar» qatoridan o'zingizga yoqqan libosni bosing. Yuqoridagi filtrlar orqali Ayollar, Erkaklar yoki kategoriyalar bo'yicha saralashingiz mumkin.",
    tips: [
      "Tanlangan libos ustida «Tanlandi» belgisi paydo bo'ladi.",
      "Istalgan payt boshqa libosni bosib, qayta sinab ko'rishingiz mumkin.",
    ],
    visual: (
      <div className="flex items-center justify-center gap-3 py-3">
        <div className="w-24 rounded-2xl border border-white/10 bg-white/5 p-2 opacity-55">
          <div className="flex aspect-[3/4] items-center justify-center rounded-xl bg-white/10">
            <ShirtIcon className="size-7 text-white/60" />
          </div>
          <div className="mt-2 h-2 w-14 rounded-full bg-white/20" />
        </div>
        <div className="relative w-28 scale-105 rounded-2xl border-2 border-brand bg-brand/15 p-2 shadow-lg">
          <span className="brand-gradient absolute top-3 right-3 rounded-full px-2 py-0.5 text-[9px] font-bold text-white">
            Tanlandi
          </span>
          <div className="flex aspect-[3/4] items-center justify-center rounded-xl bg-white/90 text-brand">
            <ShirtIcon className="size-9" />
          </div>
          <div className="mt-2 h-2 w-20 rounded-full bg-white/80" />
        </div>
        <div className="w-24 rounded-2xl border border-white/10 bg-white/5 p-2 opacity-55">
          <div className="flex aspect-[3/4] items-center justify-center rounded-xl bg-white/10">
            <ShirtIcon className="size-7 text-white/60" />
          </div>
          <div className="mt-2 h-2 w-16 rounded-full bg-white/20" />
        </div>
      </div>
    ),
  },
  {
    badge: "2-qadam",
    title: "Kamerani yoqing va to'g'ri turing",
    description:
      "«Kamera va AI qayta ishlashga roziman» katakchasini belgilab, «Kamerani yoqish» tugmasini bosing. Brauzer ruxsat so'raganda «Ruxsat berish» ni tanlang.",
    tips: [
      "Kameradan 1–1.5 metr uzoqlikda, tik va yorug' joyda turing.",
      "Boshdan belgacha yoki to'liq bo'yingiz kadrga sig'ishi natijani ancha tabiiy qiladi.",
    ],
    visual: (
      <div className="flex flex-col items-center gap-3 py-2">
        <div className="relative flex h-36 w-52 items-center justify-center rounded-2xl border border-dashed border-white/30 bg-white/5">
          <div className="flex flex-col items-center gap-1.5 text-white/85">
            <span className="brand-gradient flex size-12 items-center justify-center rounded-full text-white shadow">
              <CameraIcon className="size-6" />
            </span>
            <span className="text-[11px] font-semibold">1 – 1.5 metr masofa</span>
          </div>
          <span className="absolute top-2 left-2 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
            Yorug&apos; joy
          </span>
          <span className="absolute right-2 bottom-2 rounded-full bg-sky-500/20 px-2 py-0.5 text-[10px] font-semibold text-sky-300">
            Tik holat
          </span>
        </div>
      </div>
    ),
  },
  {
    badge: "3-qadam",
    title: "Video yoki Foto kiyib ko'ring",
    description:
      "Kamera yongach, pastki panelda 2 ta imkoniyat paydo bo'ladi — o'zingizga qulayini tanlang:",
    tips: [
      "Video kiyib ko'rish (4s): 4 soniya davomida sekin chapga va o'ngga buriling — AI harakatingizni saqlab haqiqiy video yaratadi.",
      "Rasmga tushish (AI): 1 ta kadr olib, qisqa vaqtda fotorealistik surat tayyorlaydi.",
    ],
    visual: (
      <div className="grid grid-cols-2 gap-3 py-2">
        <div className="flex flex-col items-center gap-2 rounded-2xl border border-brand/40 bg-brand/15 p-3 text-center">
          <span className="brand-gradient flex size-10 items-center justify-center rounded-full text-white">
            <VideoIcon className="size-5" />
          </span>
          <p className="text-xs font-bold text-white">Video (4 soniya)</p>
          <p className="text-[11px] text-white/70">Sekin chapga va o&apos;ngga buriling</p>
        </div>
        <div className="flex flex-col items-center gap-2 rounded-2xl border border-white/15 bg-white/5 p-3 text-center">
          <span className="flex size-10 items-center justify-center rounded-full bg-white/15 text-white">
            <CameraIcon className="size-5" />
          </span>
          <p className="text-xs font-bold text-white">Foto surat</p>
          <p className="text-[11px] text-white/70">Tezkor fotorealistik kadr</p>
        </div>
      </div>
    ),
  },
  {
    badge: "4-qadam",
    title: "Ko'ring, yuklab oling va buyurtma bering",
    description:
      "Tayyor rasm va videolar avtomatik «Saqlangan obrazlarim» bo'limida saqlanadi. Istalgan payt ustiga bosib qayta ko'rishingiz mumkin.",
    tips: [
      "Videoni bosganingizda MarosimGo Player ochiladi — 0.5x sekinlashtirib libos harakatini ko'ring.",
      "«Yuklab olish» orqali MP4/JPG saqlang yoki «Sotib olish» bilan to'g'ridan-to'g'ri buyurtma bering.",
    ],
    visual: (
      <div className="flex flex-wrap items-center justify-center gap-2.5 py-3">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-2 text-xs font-semibold text-white">
          <PlayIcon className="size-3.5 fill-current text-brand" /> MarosimGo Player (0.5x)
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-2 text-xs font-semibold text-white">
          <DownloadIcon className="size-3.5 text-sky-400" /> Yuklab olish
        </span>
        <span className="brand-gradient inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 text-xs font-semibold text-white shadow">
          <ShoppingBagIcon className="size-3.5" /> Sotib olish
        </span>
      </div>
    ),
  },
  {
    badge: "Maslahatlar",
    title: "Eng aniq va real natija sirlari",
    description: "Quyidagi 4 ta oddiy qoidaga amal qilsangiz, AI natijasi studiya darajasida chiqadi:",
    tips: [
      "Yorug'lik yuzingizga oldindan tushsin (derazaga orqa o'girib turmang).",
      "Orqa fon imkon qadar oddiy va tartibli bo'lsin.",
      "Video yozishda keskin harakat qilmang — sekin va ravon buriling.",
      "Yuzingiz va tanangizni qo'l yoki telefon bilan to'sib qo'ymang.",
    ],
    visual: (
      <div className="grid grid-cols-2 gap-2 py-2 text-left">
        {[
          { icon: <SunIcon className="size-4 text-amber-400" />, label: "Oldindan yorug'lik" },
          { icon: <SparklesIcon className="size-4 text-brand" />, label: "Toza orqa fon" },
          { icon: <VideoIcon className="size-4 text-sky-400" />, label: "Sekin harakat" },
          { icon: <CheckCircle2Icon className="size-4 text-emerald-400" />, label: "Aniq kadr" },
        ].map((item) => (
          <div key={item.label} className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-xs font-semibold text-white">
            {item.icon}
            <span>{item.label}</span>
          </div>
        ))}
      </div>
    ),
  },
];

export function StudioHelpButton() {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!open) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
      else if (e.key === "ArrowRight") setStep((s) => Math.min(STEPS.length - 1, s + 1));
      else if (e.key === "ArrowLeft") setStep((s) => Math.max(0, s - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setStep(0);
          setOpen(true);
        }}
        aria-label="Qo'llanma: AI Fashion Studio qanday ishlaydi?"
        title="Qanday ishlaydi?"
        className="glass inline-flex items-center gap-1.5 rounded-full border border-glass-border px-3 py-2 text-xs font-semibold text-foreground shadow-sm transition hover:border-brand/50 hover:text-brand active:scale-95"
      >
        <HelpCircleIcon className="size-4 text-brand" />
        <span className="hidden sm:inline">Qanday ishlaydi?</span>
      </button>

      {typeof document !== "undefined" &&
        createPortal(
          <AnimatePresence>
            {open && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                onClick={() => setOpen(false)}
                className="fixed inset-0 z-[100] flex h-dvh w-screen items-center justify-center bg-black/80 p-3 backdrop-blur-md sm:p-6"
              >
                <motion.div
                  initial={{ opacity: 0, scale: 0.96, y: 10 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.96, y: 10 }}
                  transition={{ duration: 0.2 }}
                  onClick={(e) => e.stopPropagation()}
                  className="glass relative flex max-h-[90dvh] w-full max-w-lg flex-col overflow-hidden rounded-3xl border border-white/15 bg-neutral-950 text-white shadow-2xl"
                >
                  {/* Header */}
                  <div className="flex items-center justify-between gap-2 border-b border-white/10 px-5 py-4">
                    <div className="flex items-center gap-2">
                      <span className="brand-gradient flex size-8 items-center justify-center rounded-xl text-white">
                        <SparklesIcon className="size-4" />
                      </span>
                      <div>
                        <h2 className="text-sm font-bold">AI Fashion Studio qo&apos;llanmasi</h2>
                        <p className="text-[11px] text-white/60">
                          {step + 1} / {STEPS.length}-qadam
                        </p>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setOpen(false)}
                      aria-label="Yopish"
                      className="flex size-8 items-center justify-center rounded-full bg-white/10 text-white transition hover:bg-white/20"
                    >
                      <XIcon className="size-4" />
                    </button>
                  </div>

                  {/* Step pills */}
                  <div className="flex items-center gap-1.5 px-5 pt-3">
                    {STEPS.map((s, i) => (
                      <button
                        key={s.badge}
                        type="button"
                        onClick={() => setStep(i)}
                        aria-label={`${i + 1}-qadam`}
                        className={cn(
                          "h-1.5 flex-1 rounded-full transition-all",
                          i === step ? "brand-gradient" : i < step ? "bg-brand/50" : "bg-white/15 hover:bg-white/25",
                        )}
                      />
                    ))}
                  </div>

                  {/* Step body */}
                  <div className="flex-1 overflow-y-auto px-5 py-4">
                    <AnimatePresence mode="wait">
                      <motion.div
                        key={step}
                        initial={{ opacity: 0, x: 12 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: -12 }}
                        transition={{ duration: 0.18 }}
                        className="flex flex-col gap-4"
                      >
                        <div className="rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3">
                          {current.visual}
                        </div>

                        <div className="flex flex-col gap-1.5">
                          <span className="brand-gradient w-fit rounded-full px-2.5 py-0.5 text-[11px] font-bold text-white">
                            {current.badge}
                          </span>
                          <h3 className="text-lg font-extrabold tracking-tight">{current.title}</h3>
                          <p className="text-sm leading-relaxed text-white/80">{current.description}</p>
                        </div>

                        <ul className="flex flex-col gap-2">
                          {current.tips.map((tip) => (
                            <li
                              key={tip}
                              className="flex items-start gap-2 rounded-xl bg-white/5 px-3 py-2 text-xs leading-relaxed text-white/85"
                            >
                              <CheckCircle2Icon className="mt-0.5 size-4 shrink-0 text-emerald-400" />
                              <span>{tip}</span>
                            </li>
                          ))}
                        </ul>
                      </motion.div>
                    </AnimatePresence>
                  </div>

                  {/* Footer navigation */}
                  <div className="flex items-center justify-between gap-2 border-t border-white/10 px-5 py-3.5">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={step === 0}
                      onClick={() => setStep((s) => Math.max(0, s - 1))}
                      className="border-white/20 bg-white/5 text-white hover:bg-white/15 disabled:opacity-35"
                    >
                      <ChevronLeftIcon className="size-4" /> Oldingi
                    </Button>

                    {isLast ? (
                      <Button size="sm" onClick={() => setOpen(false)}>
                        Tushundim, boshlaymiz!
                      </Button>
                    ) : (
                      <Button size="sm" onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}>
                        Keyingi <ChevronRightIcon className="size-4" />
                      </Button>
                    )}
                  </div>
                </motion.div>
              </motion.div>
            )}
          </AnimatePresence>,
          document.body,
        )}
    </>
  );
}
