"use client";

import {
  AlertTriangleIcon,
  BookmarkIcon,
  CameraIcon,
  CircleStopIcon,
  GaugeIcon,
  ImagesIcon,
  Loader2Icon,
  PauseIcon,
  RefreshCwIcon,
  ScanFaceIcon,
  ShieldCheckIcon,
  ShirtIcon,
  SparklesIcon,
  TimerIcon,
  Trash2Icon,
  VideoOffIcon,
  WifiOffIcon,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { Badge, Button, Card, cn, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { aiApi, type AiStatus, useAiGarments, useDeleteLook, useSavedLooks, useSaveLook } from "@/lib/ai-tryon";
import { type Garment, useGarmentCategories } from "@/lib/tryon";

import { type GarmentInput, type Phase, type StudioDeps, StudioSession, type StudioState } from "./session";

// ------------------------------------------------------------------ real dependencies
/** The official SDK is loaded only when the studio opens (it pulls in livekit-client). */
async function createDeps(modelName: string): Promise<StudioDeps> {
  const sdk = await import("@decartai/sdk");
  const model = sdk.models.realtime(modelName as Parameters<typeof sdk.models.realtime>[0]);
  return {
    hasSupport: () =>
      typeof window !== "undefined" &&
      window.isSecureContext &&
      !!navigator.mediaDevices?.getUserMedia &&
      typeof RTCPeerConnection !== "undefined",
    // Camera constraints come from the model definition (lucy-vton-3.6: 1280×720, ≤30 fps). No microphone.
    getCamera: () =>
      navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: "user", frameRate: model.fps, width: { ideal: model.width }, height: { ideal: model.height } },
      }),
    connect: async ({ stream, image, prompt, apiKeyProvider, onRemoteStream, onConnectionChange }) => {
      // apiKeyProvider: the SDK asks our server for a fresh short-lived client token before every dial.
      const client = sdk.createDecartClient({ apiKeyProvider, telemetry: false });
      return client.realtime.connect(stream, {
        model,
        mirror: "auto",
        onRemoteStream,
        onConnectionChange,
        initialState: { image, ...(prompt ? { prompt: { text: prompt, enhance: false } } : {}) },
      });
    },
    api: {
      start: aiApi.start,
      status: aiApi.status,
      token: aiApi.token,
      finish: aiApi.finish,
    },
    fetchImage: async (url) => {
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error(`reference ${res.status}`);
      return res.blob();
    },
    now: () => performance.now(),
    setTimer: (fn, ms) => window.setTimeout(fn, ms),
    clearTimer: (handle) => window.clearTimeout(handle as number),
  };
}

function useStudio(session: StudioSession | null): StudioState {
  const subscribe = useCallback((cb: () => void) => (session ? session.subscribe(cb) : () => undefined), [session]);
  return useSyncExternalStore(subscribe, () => session?.snapshot ?? IDLE, () => IDLE);
}

const IDLE: StudioState = { phase: "idle", metrics: {} };
const ACTIVE: Phase[] = ["starting", "connecting", "processing", "live", "switching", "reconnecting"];

const PHASE_LABEL: Record<Phase, string> = {
  idle: "Tayyor",
  unsupported: "Qurilma mos emas",
  "requesting-camera": "Kameraga ruxsat so'ralmoqda",
  "camera-denied": "Kameraga ruxsat yo'q",
  "camera-unavailable": "Kamera mavjud emas",
  "camera-ready": "Kamera tayyor · AI o'chiq",
  starting: "Seans ochilmoqda",
  connecting: "AI'ga ulanmoqda",
  processing: "AI qayta ishlamoqda",
  live: "Jonli AI",
  switching: "Kiyim almashtirilmoqda",
  reconnecting: "Qayta ulanmoqda",
  "network-error": "Tarmoq xatosi",
  "provider-error": "AI xizmati xatosi",
  limit: "Cheklov",
  expired: "Seans vaqti tugadi",
  paused: "To'xtatildi",
  finished: "Yakunlandi",
};

function toInput(g: Garment): GarmentInput | null {
  return g.ai_reference_image ? { id: g.id, referenceUrl: g.ai_reference_image, prompt: g.ai_prompt ?? "" } : null;
}

// ------------------------------------------------------------------ video element bound to a MediaStream
function StreamVideo({ stream, mirrored, className, videoRef }: {
  stream?: MediaStream;
  mirrored?: boolean;
  className?: string;
  videoRef?: React.RefObject<HTMLVideoElement | null>;
}) {
  const local = useRef<HTMLVideoElement | null>(null);
  const ref = videoRef ?? local;
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.srcObject = stream ?? null;
    if (stream) void el.play().catch(() => undefined);
  }, [ref, stream]);
  return (
    <video
      ref={ref}
      autoPlay
      muted
      playsInline
      className={cn("h-full w-full object-cover", mirrored && "-scale-x-100", className)}
    />
  );
}

// ------------------------------------------------------------------ studio
export function AiFashionStudio({ status }: { status: AiStatus }) {
  const [session, setSession] = useState<StudioSession | null>(null);
  const [consent, setConsent] = useState(false);
  const state = useStudio(session);
  const remoteRef = useRef<HTMLVideoElement | null>(null);
  const [selected, setSelected] = useState<Garment | null>(null);
  const [capture, setCapture] = useState<{ blob: Blob; url: string } | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const saveLook = useSaveLook();

  const active = ACTIVE.includes(state.phase);

  // Leaving the page: end the AI session and release the camera.
  useEffect(() => () => void session?.close(), [session]);

  // Hidden tab / locked phone: stop generating (it is billed per second) — the user can resume.
  useEffect(() => {
    if (!session) return;
    const onHide = () => {
      if (document.visibilityState === "hidden" && ACTIVE.includes(session.snapshot.phase)) void session.end("PAGE_HIDDEN");
    };
    const onPageHide = () => void session.close();
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", onPageHide);
    };
  }, [session]);

  // Countdown of the server-side session budget.
  useEffect(() => {
    if (!state.expiresAt || !active) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [state.expiresAt, active]);

  const open = async () => {
    const studio = session ?? new StudioSession(await createDeps(status.model));
    if (!session) setSession(studio);
    await studio.openCamera();
  };

  const startAi = async (garment: Garment | null) => {
    const input = garment && toInput(garment);
    if (!session || !input) return;
    await session.start(input);
  };

  const pick = (garment: Garment) => {
    setSelected(garment);
    const input = toInput(garment);
    if (session && input && ["live", "switching", "processing"].includes(state.phase)) void session.switchGarment(input);
  };

  const takeShot = async () => {
    const video = remoteRef.current;
    if (!video || state.phase !== "live" || !video.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0); // the AI result frame, as delivered by Decart
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/jpeg", 0.92));
    if (blob) setCapture({ blob, url: URL.createObjectURL(blob) });
  };

  const discardShot = () => {
    if (capture) URL.revokeObjectURL(capture.url);
    setCapture(null);
    saveLook.reset();
  };

  const secondsLeft = state.expiresAt && active ? Math.max(0, Math.round((state.expiresAt - now) / 1000)) : null;
  const showRemote = !!state.remoteStream && ["live", "switching", "reconnecting"].includes(state.phase);

  return (
    <div className="flex flex-col gap-4">
      {/* -------------------------------------------------- stage */}
      <section
        aria-label="Jonli AI kiyib ko'rish"
        className="relative overflow-hidden rounded-3xl bg-neutral-950 shadow-[0_30px_80px_-40px_rgb(15_23_42/0.8)] ring-1 ring-white/10"
      >
        <div className="relative aspect-[3/4] w-full sm:aspect-video">
          {/* The AI stream is the result. The raw camera is shown only before AI starts, and labelled as such. */}
          {showRemote ? (
            <StreamVideo stream={state.remoteStream} videoRef={remoteRef} />
          ) : state.localStream ? (
            <StreamVideo
              stream={state.localStream}
              mirrored
              className={cn("transition", active && "scale-105 blur-md brightness-50")}
            />
          ) : (
            <div className="brand-gradient absolute inset-0 opacity-30" />
          )}

          {/* top bar */}
          <div className="absolute inset-x-0 top-0 flex items-center justify-between gap-2 p-3">
            <span
              role="status"
              aria-live="polite"
              className="inline-flex items-center gap-2 rounded-full bg-black/45 px-3 py-1.5 text-xs font-semibold text-white backdrop-blur-md ring-1 ring-white/15"
            >
              <span
                className={cn(
                  "size-2 rounded-full",
                  state.phase === "live" ? "animate-pulse bg-emerald-400" : active ? "animate-pulse bg-amber-400" : "bg-white/50",
                )}
              />
              {PHASE_LABEL[state.phase]}
              {state.localStream && !showRemote && !active && (
                <span className="text-white/60">(oddiy kamera, AI emas)</span>
              )}
            </span>
            <div className="flex items-center gap-2">
              {state.metrics.fps !== undefined && showRemote && (
                <span className="hidden items-center gap-1 rounded-full bg-black/45 px-2.5 py-1.5 text-[11px] font-medium text-white/85 backdrop-blur-md sm:inline-flex">
                  <GaugeIcon className="size-3.5" />
                  {state.metrics.fps} fps
                  {state.metrics.glass_to_glass_ms !== undefined && ` · ${state.metrics.glass_to_glass_ms} ms`}
                </span>
              )}
              {secondsLeft !== null && (
                <span className="inline-flex items-center gap-1 rounded-full bg-black/45 px-2.5 py-1.5 text-xs font-semibold tabular-nums text-white backdrop-blur-md">
                  <TimerIcon className="size-3.5" />
                  {Math.floor(secondsLeft / 60)}:{String(secondsLeft % 60).padStart(2, "0")}
                </span>
              )}
            </div>
          </div>

          {/* phase overlays */}
          <AnimatePresence mode="wait">
            <StageOverlay
              key={state.phase}
              state={state}
              status={status}
              consent={consent}
              setConsent={setConsent}
              selected={selected}
              onOpen={open}
              onStart={() => startAi(selected)}
            />
          </AnimatePresence>

          {/* bottom controls */}
          {(active || state.phase === "camera-ready") && (
            <div className="absolute inset-x-0 bottom-0 flex items-center justify-center gap-3 bg-gradient-to-t from-black/70 to-transparent p-4 pt-10">
              {state.phase === "camera-ready" ? (
                <Button size="lg" onClick={() => startAi(selected)} disabled={!selected}>
                  <SparklesIcon />
                  {selected ? "AI bilan kiyib ko'rish" : "Pastdan kiyim tanlang"}
                </Button>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={takeShot}
                    disabled={state.phase !== "live"}
                    aria-label="Kadrni olish"
                    className="inline-flex size-16 items-center justify-center rounded-full bg-white text-neutral-900 shadow-xl ring-4 ring-white/30 transition active:scale-95 disabled:opacity-40"
                  >
                    <CameraIcon className="size-7" />
                  </button>
                  <button
                    type="button"
                    onClick={() => void session?.end("USER")}
                    aria-label="Seansni yakunlash"
                    className="absolute right-4 inline-flex items-center gap-1.5 rounded-full bg-black/50 px-3 py-2 text-xs font-semibold text-white backdrop-blur-md ring-1 ring-white/20 transition hover:bg-black/70"
                  >
                    <CircleStopIcon className="size-4" /> Yakunlash
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      </section>

      {state.message && ["live", "camera-ready"].includes(state.phase) && (
        <p role="alert" className="text-sm text-amber-600 dark:text-amber-400">
          {state.message}
        </p>
      )}

      {/* -------------------------------------------------- garment picker */}
      <GarmentPicker selected={selected} onPick={pick} disabled={state.phase === "starting" || state.phase === "connecting"} />

      {/* -------------------------------------------------- saved looks */}
      <SavedLooks />

      {/* -------------------------------------------------- capture preview */}
      <AnimatePresence>
        {capture && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-4 backdrop-blur-sm sm:items-center"
            role="dialog"
            aria-modal="true"
            aria-label="Olingan kadr"
          >
            <motion.div
              initial={{ y: 30, scale: 0.97 }}
              animate={{ y: 0, scale: 1 }}
              className="glass w-full max-w-md overflow-hidden rounded-3xl"
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- a local blob URL */}
              <img src={capture.url} alt="AI natijasidan olingan kadr" className="max-h-[60vh] w-full object-contain bg-black" />
              <div className="flex flex-col gap-3 p-4">
                <p className="text-sm text-muted-foreground">
                  {"Kadr faqat siz «Saqlash»ni bossangiz hisobingizga yuklanadi va faqat sizga ko'rinadi."}
                </p>
                {saveLook.error && <ErrorState error={saveLook.error} />}
                {saveLook.isSuccess ? (
                  <div className="flex items-center justify-between gap-2">
                    <Badge tone="success">Saqlandi</Badge>
                    <Button variant="outline" onClick={discardShot}>
                      Yopish
                    </Button>
                  </div>
                ) : (
                  <div className="flex justify-end gap-2">
                    <Button variant="ghost" onClick={discardShot}>
                      Bekor qilish
                    </Button>
                    <Button
                      loading={saveLook.isPending}
                      onClick={() =>
                        saveLook.mutate({ image: capture.blob, garment: state.garmentId ?? null, session: state.sessionId ?? null })
                      }
                    >
                      <BookmarkIcon /> Saqlash
                    </Button>
                  </div>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ------------------------------------------------------------------ overlays per phase
function Panel({ icon, title, children }: { icon: React.ReactNode; title: string; children?: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="absolute inset-0 flex items-center justify-center p-5"
    >
      <div className="w-full max-w-sm rounded-3xl bg-white/10 p-5 text-center text-white shadow-2xl ring-1 ring-white/20 backdrop-blur-xl">
        <div className="mx-auto mb-3 flex size-12 items-center justify-center rounded-2xl bg-white/15 [&_svg]:size-6">{icon}</div>
        <h2 className="text-lg font-bold">{title}</h2>
        <div className="mt-2 space-y-3 text-sm text-white/80">{children}</div>
      </div>
    </motion.div>
  );
}

function Busy({ title, note }: { title: string; note?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-white"
    >
      <Loader2Icon className="size-9 animate-spin" />
      <p className="text-base font-semibold">{title}</p>
      {note && <p className="max-w-xs text-center text-xs text-white/70">{note}</p>}
    </motion.div>
  );
}

function StageOverlay({
  state,
  status,
  consent,
  setConsent,
  selected,
  onOpen,
  onStart,
}: {
  state: StudioState;
  status: AiStatus;
  consent: boolean;
  setConsent: (v: boolean) => void;
  selected: Garment | null;
  onOpen: () => void;
  onStart: () => void;
}) {
  const retry = (
    <Button variant="outline" className="border-white/30 bg-white/15 text-white" onClick={onStart} disabled={!selected}>
      <RefreshCwIcon /> Qayta urinish
    </Button>
  );
  switch (state.phase) {
    case "idle":
      return (
        <Panel icon={<ShieldCheckIcon />} title="MarosimGo AI Fashion Studio">
          <p>
            Kamerangiz tasviri jonli ravishda AI xizmatiga (Decart) yuboriladi va siz tanlagan kiyimda qaytariladi.
            Video serverlarimizda saqlanmaydi; kadr faqat siz «Saqlash»ni bossangiz saqlanadi.
          </p>
          <p className="text-xs text-white/60">
            Bugun: {Math.floor(status.seconds_left_today / 60)} daqiqa · {status.sessions_left_today} ta seans qoldi.
            {" Bir seans ko'pi bilan "}{Math.round(status.max_session_seconds / 60)} daqiqa.
          </p>
          <label className="flex items-start gap-2 text-left text-white">
            <input
              type="checkbox"
              className="mt-0.5 size-4 accent-blue-500"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />
            <span>Kamera va AI qayta ishlashga roziman</span>
          </label>
          <Button size="lg" className="w-full" disabled={!consent} onClick={onOpen}>
            <CameraIcon /> Kamerani yoqish
          </Button>
        </Panel>
      );
    case "requesting-camera":
      return <Busy title="Kameraga ruxsat so'ralmoqda" note="Brauzer oynasida «Ruxsat berish»ni bosing." />;
    case "unsupported":
      return (
        <Panel icon={<VideoOffIcon />} title="Bu qurilmada ishlamaydi">
          <p>{state.message} {"Chrome, Safari (iOS 16+) yoki Edge'ning yangi versiyasidan HTTPS orqali foydalaning."}</p>
        </Panel>
      );
    case "camera-denied":
      return (
        <Panel icon={<VideoOffIcon />} title="Kameraga ruxsat berilmadi">
          <p>{"Manzil satridagi qulf belgisi → «Kamera» → «Ruxsat berish», so'ng qayta urinib ko'ring."}</p>
          <Button variant="outline" className="border-white/30 bg-white/15 text-white" onClick={onOpen}>
            <RefreshCwIcon /> Qayta urinish
          </Button>
        </Panel>
      );
    case "camera-unavailable":
      return (
        <Panel icon={<VideoOffIcon />} title="Kamera mavjud emas">
          <p>{state.message}</p>
          <Button variant="outline" className="border-white/30 bg-white/15 text-white" onClick={onOpen}>
            <RefreshCwIcon /> Qayta urinish
          </Button>
        </Panel>
      );
    case "starting":
      return <Busy title="Seans ochilmoqda" />;
    case "connecting":
      return <Busy title="AI'ga ulanmoqda" note="Xavfsiz WebRTC ulanishi o'rnatilmoqda." />;
    case "processing":
      return <Busy title="AI qayta ishlamoqda" note="Birinchi kadr tayyorlanmoqda. Kameraga to'liq ko'rining." />;
    case "switching":
      return (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="absolute bottom-28 left-1/2 -translate-x-1/2 rounded-full bg-black/55 px-4 py-2 text-sm font-semibold text-white backdrop-blur-md"
        >
          <Loader2Icon className="mr-2 inline size-4 animate-spin" /> Kiyim almashtirilmoqda
        </motion.div>
      );
    case "reconnecting":
      return <Busy title="Qayta ulanmoqda" note="Aloqa beqaror. Avtomatik qayta ulanmoqda." />;
    case "network-error":
      return (
        <Panel icon={<WifiOffIcon />} title="Tarmoq xatosi">
          <p>{state.message ?? "Aloqa uzildi."} Kamida 4 Mbit/s barqaror internet kerak.</p>
          {retry}
        </Panel>
      );
    case "provider-error":
      return (
        <Panel icon={<AlertTriangleIcon />} title="AI xizmati xatosi">
          <p>{state.message}</p>
          {retry}
        </Panel>
      );
    case "limit":
      return (
        <Panel icon={<TimerIcon />} title="Hozircha mavjud emas">
          <p>{state.message}</p>
        </Panel>
      );
    case "expired":
      return (
        <Panel icon={<TimerIcon />} title="Seans vaqti tugadi">
          <p>Xarajatni nazorat qilish uchun har bir seans vaqti cheklangan.</p>
          {retry}
        </Panel>
      );
    case "paused":
      return (
        <Panel icon={<PauseIcon />} title="To'xtatildi">
          <p>{"Sahifa fonga o'tgani uchun AI to'xtatildi."}</p>
          <Button variant="outline" className="border-white/30 bg-white/15 text-white" onClick={onStart} disabled={!selected}>
            <SparklesIcon /> Davom ettirish
          </Button>
        </Panel>
      );
    case "finished":
      return (
        <Panel icon={<ScanFaceIcon />} title="Seans yakunlandi">
          <p>{"Kamera o'chirildi."}</p>
          <Button variant="outline" className="border-white/30 bg-white/15 text-white" onClick={onOpen}>
            <CameraIcon /> Kamerani qayta yoqish
          </Button>
        </Panel>
      );
    default:
      return null;
  }
}

// ------------------------------------------------------------------ garment picker
const AUDIENCES = [
  { key: "ALL", label: "Hammasi" },
  { key: "WOMEN", label: "Ayollar" },
  { key: "MEN", label: "Erkaklar" },
  { key: "UNISEX", label: "Umumiy" },
] as const;

function GarmentPicker({ selected, onPick, disabled }: { selected: Garment | null; onPick: (g: Garment) => void; disabled: boolean }) {
  const categories = useGarmentCategories();
  const [audience, setAudience] = useState<(typeof AUDIENCES)[number]["key"]>("ALL");
  const [category, setCategory] = useState<string | null>(null);
  const garments = useAiGarments(category);

  const visibleCategories = useMemo(
    () => (categories.data ?? []).filter((c) => audience === "ALL" || c.audience === audience),
    [categories.data, audience],
  );
  const list = (garments.data?.results ?? []).filter(
    (g) => audience === "ALL" || g.category.audience === audience,
  );

  return (
    <Card className="flex flex-col gap-3 p-3 sm:p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-bold">
          <ShirtIcon className="size-4" /> AI uchun kiyimlar
        </h2>
        <div role="tablist" aria-label="Kimlar uchun" className="glass flex gap-1 rounded-xl p-1">
          {AUDIENCES.map((a) => (
            <button
              key={a.key}
              type="button"
              role="tab"
              aria-selected={audience === a.key}
              onClick={() => {
                setAudience(a.key);
                setCategory(null);
              }}
              className={cn(
                "rounded-lg px-2.5 py-1 text-xs font-semibold transition",
                audience === a.key ? "brand-gradient text-white" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none]">
        <Chip active={category === null} onClick={() => setCategory(null)}>
          Barchasi
        </Chip>
        {visibleCategories.map((c) => (
          <Chip key={c.slug} active={category === c.slug} onClick={() => setCategory(c.slug)}>
            {c.name}
          </Chip>
        ))}
      </div>

      {garments.error ? (
        <ErrorState error={garments.error} onRetry={() => garments.refetch()} />
      ) : garments.isPending ? (
        <div className="flex gap-3 overflow-hidden">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-40 w-28 shrink-0 rounded-2xl" />
          ))}
        </div>
      ) : list.length === 0 ? (
        <EmptyState
          title="Bu bo'limda AI kiyimlari hali yo'q"
          description="Kiyimlar AI uchun tayyorlangan rasm (odamsiz, oddiy fonda) yuklangach shu yerda paydo bo'ladi."
        />
      ) : (
        <ul className="flex snap-x gap-3 overflow-x-auto pb-1 [scrollbar-width:none]" aria-label="Kiyimlar">
          {list.map((g) => {
            const isSelected = selected?.id === g.id;
            return (
              <li key={g.id} className="snap-start">
                <button
                  type="button"
                  onClick={() => onPick(g)}
                  disabled={disabled}
                  aria-pressed={isSelected}
                  className={cn(
                    "group flex w-28 flex-col gap-1.5 rounded-2xl p-1.5 text-left transition disabled:opacity-50 sm:w-32",
                    isSelected ? "bg-brand/10 ring-2 ring-brand" : "hover:bg-muted",
                  )}
                >
                  <span className="relative block aspect-[3/4] overflow-hidden rounded-xl bg-white">
                    {/* eslint-disable-next-line @next/next/no-img-element -- same-origin media, static export */}
                    <img
                      src={g.cover_image ?? g.ai_reference_image ?? ""}
                      alt={g.name}
                      loading="lazy"
                      className="h-full w-full object-contain transition group-hover:scale-105"
                    />
                    {isSelected && (
                      <span className="brand-gradient absolute top-1.5 right-1.5 rounded-full px-1.5 py-0.5 text-[10px] font-bold text-white">
                        Tanlandi
                      </span>
                    )}
                  </span>
                  <span className="line-clamp-2 text-xs font-semibold">{g.name}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "shrink-0 rounded-full px-3 py-1.5 text-xs font-semibold transition",
        active ? "brand-gradient text-white" : "glass text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

// ------------------------------------------------------------------ saved looks
function SavedLooks() {
  const looks = useSavedLooks();
  const remove = useDeleteLook();
  const rows = looks.data?.results ?? [];
  return (
    <Card className="flex flex-col gap-3 p-3 sm:p-4">
      <h2 className="flex items-center gap-2 text-sm font-bold">
        <ImagesIcon className="size-4" /> Saqlangan obrazlarim
      </h2>
      {looks.error ? (
        <ErrorState error={looks.error} onRetry={() => looks.refetch()} />
      ) : looks.isPending ? (
        <Skeleton className="h-32 w-full rounded-2xl" />
      ) : rows.length === 0 ? (
        <EmptyState title="Hali saqlangan obraz yo'q" description="Jonli AI paytida kamera tugmasini bosing va «Saqlash»ni tanlang." />
      ) : (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {rows.map((look) => (
            <li key={look.id} className="group relative overflow-hidden rounded-2xl bg-black">
              {/* eslint-disable-next-line @next/next/no-img-element -- owner-only API URL */}
              <img src={look.image} alt={look.garment?.name ?? "Saqlangan obraz"} loading="lazy" className="aspect-[3/4] w-full object-cover" />
              <div className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-1 bg-gradient-to-t from-black/80 to-transparent p-2 pt-6">
                <span className="truncate text-[11px] font-semibold text-white">{look.garment?.name ?? "—"}</span>
                <button
                  type="button"
                  aria-label="O'chirish"
                  onClick={() => remove.mutate(look.id)}
                  disabled={remove.isPending}
                  className="rounded-full bg-white/15 p-1.5 text-white transition hover:bg-red-500/80"
                >
                  {remove.isPending && remove.variables === look.id ? (
                    <Loader2Icon className="size-3.5 animate-spin" />
                  ) : (
                    <Trash2Icon className="size-3.5" />
                  )}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

