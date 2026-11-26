"use client";

import {
  AlertTriangleIcon,
  BookmarkIcon,
  CameraIcon,
  CheckCircle2Icon,
  CircleStopIcon,
  CrownIcon,
  DownloadIcon,
  GaugeIcon,
  ImagesIcon,
  Loader2Icon,
  PauseIcon,
  PlayIcon,
  RefreshCwIcon,
  ScanFaceIcon,
  ShieldCheckIcon,
  ShirtIcon,
  ShoppingBagIcon,
  SparklesIcon,
  TimerIcon,
  Trash2Icon,
  VideoIcon,
  VideoOffIcon,
  WifiOffIcon,
  XIcon,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { createPortal } from "react-dom";

import { Badge, Button, Card, cn, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import {
  aiApi,
  type AiStatus,
  type SavedLook,
  useAiGarments,
  useCreateGarmentOrder,
  useDeleteLook,
  useSavedLooks,
  useSaveLook,
} from "@/lib/ai-tryon";
import { useMe } from "@/lib/auth";
import { type Garment, useGarmentCategories } from "@/lib/tryon";

import { type GarmentInput, type Phase, type StudioDeps, StudioSession, type StudioState } from "./session";
import { MarosimVideoPlayer } from "./video-player";

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

const VIDEO_LOADER_NOTES = [
  "MarosimGo AI libosni sizga kiydirmoqda...",
  "Tanlangan libos qomatingizga moslashtirilmoqda...",
  "Bir necha soniyada rasmingiz chiqadi, video esa ortidan keladi...",
] as const;

const PHOTO_LOADER_NOTES = [
  "Suratingiz tahlil qilinmoqda...",
  "Tanlangan libos qomatingizga moslashtirilmoqda...",
  "Yorug'lik va mato detallari sayqallanmoqda...",
  "Deyarli tayyor! Natija yuklanmoqda...",
] as const;

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
  if (status.mode === "snapshot") {
    return <SnapshotAiStudio status={status} />;
  }
  return <RealtimeAiStudio status={status} />;
}

function SnapshotAiStudio({ status }: { status: AiStatus }) {
  const videoLeft = status.quota?.video_left;
  const photoLeft = status.quota?.photo_left;
  const [consent, setConsent] = useState(false);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Garment | null>(null);
  const [rendering, setRendering] = useState(false);
  const [renderingMode, setRenderingMode] = useState<"photo" | "video">("photo");
  const [recordingSec, setRecordingSec] = useState<number | null>(null);
  const [renderError, setRenderError] = useState<unknown>(null);
  const [result, setResult] = useState<{
    url: string;
    videoUrl?: string;
    lookId?: string;
    garment: Garment;
    latencyMs: number;
  } | null>(null);
  const [buyOpen, setBuyOpen] = useState(false);
  /** fast pipeline: the dressed photo is on screen while the video is still being made. */
  const [videoPending, setVideoPending] = useState(false);
  const runRef = useRef(0);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const stageRef = useRef<HTMLElement | null>(null);
  const queryClient = useQueryClient();
  const saveLook = useSaveLook();
  const allAiGarments = useAiGarments(null);

  // Auto-select garment if navigated from /kiyib-korish?garment=<id>
  useEffect(() => {
    if (selected || typeof window === "undefined") return;
    const preselectedId = new URLSearchParams(window.location.search).get("garment");
    if (!preselectedId) return;
    const match = allAiGarments.data?.results.find((g) => g.id === preselectedId);
    if (match) setSelected(match);
  }, [allAiGarments.data, selected]);

  useEffect(() => {
    return () => {
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [stream]);

  const openCamera = async () => {
    if (!selected) return;
    setCameraError(null);
    setResult(null);
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: "user", width: { ideal: 1080 }, height: { ideal: 1440 } },
      });
      setStream(s);
    } catch {
      setCameraError("Kameraga ruxsat berilmadi yoki kamera topilmadi.");
    }
  };

  const stopCamera = () => {
    stream?.getTracks().forEach((t) => t.stop());
    setStream(null);
  };

  const tryOnNow = async (garment: Garment | null) => {
    const video = videoRef.current;
    if (!garment || !video || !video.videoWidth) return;
    setRenderingMode("photo");
    setRendering(true);
    setRenderError(null);
    saveLook.reset();
    try {
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const ctx = canvas.getContext("2d");
      if (ctx) {
        ctx.translate(canvas.width, 0);
        ctx.scale(-1, 1);
        ctx.drawImage(video, 0, 0);
      }
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.94));
      if (!blob) throw new Error("Kadrni olib bo'lmadi.");
      const out = await aiApi.render(blob, garment.id);
      setResult({ url: out.image, lookId: out.look_id, garment, latencyMs: out.latency_ms });
      void queryClient.invalidateQueries({ queryKey: ["tryon", "looks"] });
    } catch (err) {
      setRenderError(err);
    } finally {
      setRendering(false);
      void queryClient.invalidateQueries({ queryKey: ["tryon", "ai", "status"] });
    }
  };

  const tryOnVideo = async (garment: Garment | null) => {
    if (!garment || !stream || typeof MediaRecorder === "undefined") return;
    setRenderError(null);
    saveLook.reset();
    const mimeCandidates = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm", "video/mp4"];
    const mimeType = mimeCandidates.find((m) => MediaRecorder.isTypeSupported(m));
    const chunks: BlobPart[] = [];
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };

    const recorded = new Promise<Blob>((resolve, reject) => {
      recorder.onerror = () => reject(new Error("Video yozishda xatolik yuz berdi."));
      recorder.onstop = () => resolve(new Blob(chunks, { type: recorder.mimeType || "video/webm" }));
    });

    setRecordingSec(4);
    recorder.start(250);
    let left = 4;
    const timer = window.setInterval(() => {
      left -= 1;
      if (left <= 0) {
        window.clearInterval(timer);
        setRecordingSec(null);
        if (recorder.state !== "inactive") recorder.stop();
      } else {
        setRecordingSec(left);
      }
    }, 1000);

    try {
      const videoBlob = await recorded;
      setRenderingMode("video");
      setRendering(true);
      const run = ++runRef.current;
      const out = await aiApi.renderVideo(videoBlob, garment.id, (job) => {
        if (run !== runRef.current || !job.preview_url || job.status === "DONE") return;
        // the photo is ready (~20 s): show it now, the video follows in about a minute
        setResult({ url: job.preview_url, lookId: job.look_id, garment, latencyMs: 0 });
        setVideoPending(true);
        setRendering(false);
      });
      if (run !== runRef.current) return; // the user started over meanwhile
      setResult({
        url: out.poster_url,
        videoUrl: out.video_url,
        lookId: out.look_id,
        garment,
        latencyMs: out.latency_ms,
      });
      void queryClient.invalidateQueries({ queryKey: ["tryon", "looks"] });
    } catch (err) {
      setRenderError(err);
    } finally {
      window.clearInterval(timer);
      setRecordingSec(null);
      setRendering(false);
      setVideoPending(false);
      void queryClient.invalidateQueries({ queryKey: ["tryon", "ai", "status"] });
    }
  };

  const downloadResult = () => {
    if (!result?.lookId) return;
    const a = document.createElement("a");
    a.href = aiApi.downloadUrl(result.lookId);
    a.download = `marosimgo-look-${result.lookId.slice(0, 8)}.jpg`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  const saveResult = async () => {
    if (!result) return;
    const res = await fetch(result.url);
    const blob = await res.blob();
    saveLook.mutate({ image: blob, garment: result.garment.id, session: null });
  };

  return (
    <div className="flex flex-col gap-4">
      {/* -------------------------------------------------- 1-qadam: Avval kiyim tanlash */}
      <GarmentPicker
        selected={selected}
        onPick={(g) => {
          setSelected(g);
          setResult(null);
          setRenderError(null);
          stageRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }}
        disabled={rendering}
      />

      {/* -------------------------------------------------- 2-qadam: Kamera va rasm tushib kiyib ko'rish */}
      <section
        ref={stageRef}
        aria-label="AI kiyib ko'rish"
        className="relative overflow-hidden rounded-3xl bg-neutral-950 shadow-[0_30px_80px_-40px_rgb(15_23_42/0.8)] ring-1 ring-white/10"
      >
        <div className="relative aspect-[3/4] w-full sm:aspect-video">
          {result?.videoUrl ? (
            <video
              src={result.videoUrl}
              poster={result.url}
              autoPlay
              loop
              controls
              playsInline
              className="h-full w-full bg-black object-contain"
            />
          ) : result ? (
            /* eslint-disable-next-line @next/next/no-img-element -- data URL from OpenAI try-on */
            <img src={result.url} alt={result.garment.name} className="h-full w-full object-contain bg-black" />
          ) : stream ? (
            <StreamVideo
              stream={stream}
              mirrored
              videoRef={videoRef}
              className={cn("transition", rendering && "scale-105 blur-md brightness-50")}
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
              <span className={cn("size-2 rounded-full", rendering ? "animate-pulse bg-amber-400" : result ? "bg-emerald-400" : stream ? "bg-sky-400" : "bg-white/50")} />
              {rendering
                ? "AI tanlangan kiyimni kiydirmoqda..."
                : result
                  ? `Tayyor · ${result.garment.name}`
                  : stream && selected
                    ? `2-qadam: Rasmga tushing · ${selected.name}`
                    : selected
                      ? `Tanlangan kiyim: ${selected.name}`
                      : "1-qadam: Tepadan kiyim tanlang"}
            </span>
            <span className="rounded-full bg-black/45 px-2.5 py-1 text-[11px] font-medium text-white/80 backdrop-blur-md">
              {status.model}
            </span>
          </div>

          {/* Selected garment mini preview while camera is open */}
          {selected && stream && !result && !rendering && (
            <div className="absolute top-14 right-3 flex items-center gap-2 rounded-2xl bg-black/55 p-1.5 pr-3 text-white backdrop-blur-md ring-1 ring-white/20">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={selected.cover_image ?? selected.ai_reference_image ?? ""}
                alt={selected.name}
                className="size-12 rounded-xl bg-white object-contain"
              />
              <div className="max-w-32">
                <p className="text-[10px] text-white/70">Tanlangan kiyim</p>
                <p className="truncate text-xs font-bold">{selected.name}</p>
              </div>
            </div>
          )}

          {/* Overlay before camera opens */}
          {!stream && !result && (
            <Panel
              icon={selected ? <CameraIcon /> : <ShirtIcon />}
              title={selected ? "2-qadam: Kamerani yoqib rasmga tushing" : "1-qadam: Avval kiyim tanlang"}
            >
              {selected ? (
                <>
                  <div className="mx-auto flex items-center gap-3 rounded-2xl bg-white/10 p-2 text-left">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={selected.cover_image ?? selected.ai_reference_image ?? ""}
                      alt={selected.name}
                      className="size-14 shrink-0 rounded-xl bg-white object-contain"
                    />
                    <div className="min-w-0">
                      <p className="text-[11px] text-white/70">Tanlangan kiyim:</p>
                      <p className="truncate text-sm font-bold text-white">{selected.name}</p>
                    </div>
                  </div>
                  <p className="text-xs">
                    Kamerani yoqing, tik va yorug&apos; joyda turing, so&apos;ng suratga oling — AI aynan shu kiyimni
                    yuzingizni o&apos;zgartirmasdan ustingizda ko&apos;rsatadi.
                  </p>
                  {cameraError && <p className="text-xs text-rose-300">{cameraError}</p>}
                  <label className="flex items-start gap-2 text-left text-white">
                    <input
                      type="checkbox"
                      className="mt-0.5 size-4 accent-blue-500"
                      checked={consent}
                      onChange={(e) => setConsent(e.target.checked)}
                    />
                    <span>Kamera va AI qayta ishlashga roziman</span>
                  </label>
                  <Button size="lg" className="w-full" disabled={!consent} onClick={openCamera}>
                    <CameraIcon /> Kamerani yoqish
                  </Button>
                </>
              ) : (
                <p>
                  Tepadagi ro&apos;yxatdan kiyib ko&apos;rmoqchi bo&apos;lgan kiyimingizni tanlang — shundan keyin
                  kamera ochiladi.
                </p>
              )}
            </Panel>
          )}

          {recordingSec !== null && (
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/25 text-white">
              <span className="inline-flex items-center gap-2 rounded-full bg-rose-600 px-4 py-1.5 text-sm font-bold shadow-lg">
                <span className="size-2.5 animate-pulse rounded-full bg-white" />
                Video yozilmoqda · {recordingSec}s
              </span>
              <p className="rounded-full bg-black/55 px-3 py-1 text-xs">Sekin chapga va o&apos;ngga burilib turing</p>
            </div>
          )}

          {videoPending && (
            <div className="pointer-events-none absolute inset-x-0 top-3 flex justify-center">
              <span className="inline-flex items-center gap-2 rounded-full bg-black/60 px-4 py-1.5 text-xs font-semibold text-white backdrop-blur-md ring-1 ring-white/20">
                <Loader2Icon className="size-3.5 animate-spin" aria-hidden /> Rasm tayyor · video tayyorlanmoqda (≈1 daqiqa)
              </span>
            </div>
          )}

          {rendering && (
            <Busy
              title={
                renderingMode === "video"
                  ? `${selected?.name ?? "Kiyim"} — Video Try-On tayyorlanmoqda`
                  : `${selected?.name ?? "Kiyim"} kiydirilmoqda`
              }
              note={renderingMode === "video" ? VIDEO_LOADER_NOTES : PHOTO_LOADER_NOTES}
            />
          )}

          {/* bottom controls */}
          {stream && !rendering && recordingSec === null && (
            <div className="absolute inset-x-0 bottom-0 flex flex-wrap items-center justify-center gap-2 bg-gradient-to-t from-black/80 to-transparent p-4 pt-10">
              {result ? (
                <>
                  <Button
                    variant="outline"
                    className="border-white/30 bg-white/15 text-white"
                    onClick={() => {
                      runRef.current += 1;
                      setVideoPending(false);
                      setResult(null);
                    }}
                  >
                    <RefreshCwIcon /> Qayta tushish
                  </Button>
                  {result.lookId ? (
                    <Button variant="outline" className="border-white/30 bg-white/15 text-white" onClick={downloadResult}>
                      <DownloadIcon />
                      {result.videoUrl
                        ? "Videoni yuklab olish (MP4)"
                        : status.is_premium
                          ? "Yuklab olish (Premium)"
                          : "Yuklab olish (MarosimGo)"}
                    </Button>
                  ) : !saveLook.isSuccess ? (
                    <Button variant="outline" className="border-white/30 bg-white/15 text-white" loading={saveLook.isPending} onClick={saveResult}>
                      <BookmarkIcon /> Saqlash
                    </Button>
                  ) : null}
                  <Button size="lg" onClick={() => setBuyOpen(true)}>
                    <ShoppingBagIcon /> Sotib olish
                  </Button>
                </>
              ) : (
                <>
                  {status.is_premium ? (
                    <Button size="lg" onClick={() => void tryOnVideo(selected)} disabled={!selected || videoLeft === 0}>
                      <VideoIcon /> {videoLeft === 0 ? "Video: bu oy limiti tugadi" : `Video Try-On (4 soniya) · ${videoLeft} ta`}
                    </Button>
                  ) : (
                    <Link
                      href="/obuna"
                      className="inline-flex h-11 items-center gap-2 rounded-2xl bg-gradient-to-r from-amber-400 to-orange-500 px-5 text-sm font-bold text-white shadow-lg"
                    >
                      <CrownIcon className="size-4" aria-hidden /> Video Try-On — Premium
                    </Link>
                  )}
                  <Button
                    variant="outline"
                    className="border-white/30 bg-white/15 text-white"
                    onClick={() => void tryOnNow(selected)}
                    disabled={!selected || photoLeft === 0}
                  >
                    <CameraIcon /> {photoLeft === 0 ? "Rasm: bu oy limiti tugadi" : `Rasm (tez)${photoLeft !== undefined ? ` · ${photoLeft} ta` : ""}`}
                  </Button>
                  <button
                    type="button"
                    onClick={stopCamera}
                    className="rounded-full bg-black/50 px-3 py-2 text-xs font-semibold text-white backdrop-blur-md ring-1 ring-white/20 hover:bg-black/70"
                  >
                    <CircleStopIcon className="mr-1 inline size-4" /> O&apos;chirish
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      </section>

      {status.quota && (
        <p className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-center text-xs text-muted-foreground">
          <span>
            Bu oy: AI video <b>{status.quota.video_left}</b>/{status.quota.video_limit} · AI rasm <b>{status.quota.photo_left}</b>/
            {status.quota.photo_limit}
          </span>
          {!status.is_premium && (
            <Link href="/obuna" className="font-semibold text-brand underline-offset-2 hover:underline">
              Premium: oyiga 2 ta AI video va 15 ta rasm →
            </Link>
          )}
        </p>
      )}

      {result && !status.is_premium && (
        <p className="text-center text-xs text-muted-foreground">
          Oddiy rejimda yuklab olingan rasmga <strong>MarosimGo</strong> logosi qo&apos;yiladi. Premium obunada rasm
          logosiz yuklab olinadi.
        </p>
      )}

      {!!renderError && <ErrorState error={renderError} />}

      {buyOpen && result && (
        <BuyGarmentModal
          garment={result.garment}
          lookId={result.lookId ?? null}
          onClose={() => setBuyOpen(false)}
        />
      )}

      <SavedLooks isPremium={!!status.is_premium} />
    </div>
  );
}

const DEFAULT_SIZES = ["S", "M", "L", "XL", "46", "48", "50", "52"];

function BuyGarmentModal({
  garment,
  lookId,
  onClose,
}: {
  garment: Garment;
  lookId: string | null;
  onClose: () => void;
}) {
  const { data: me } = useMe();
  const sizes = garment.sizes.length > 0 ? garment.sizes : DEFAULT_SIZES;
  const colors = garment.colors.length > 0 ? garment.colors : [{ name: "Asl rang" }];
  const [size, setSize] = useState(sizes[0] ?? "M");
  const [color, setColor] = useState(colors[0]?.name ?? "");
  const [quantity, setQuantity] = useState(1);
  const [customerName, setCustomerName] = useState(
    me ? `${me.first_name ?? ""} ${me.last_name ?? ""}`.trim() : "",
  );
  const [customerPhone, setCustomerPhone] = useState(me?.phone_number ?? "");
  const [deliveryType, setDeliveryType] = useState<"DELIVERY" | "PICKUP">("DELIVERY");
  const [deliveryAddress, setDeliveryAddress] = useState(me?.address ?? "");
  const [paymentMethod, setPaymentMethod] = useState<"CASH" | "CARD">("CASH");
  const [notes, setNotes] = useState("");
  const createOrder = useCreateGarmentOrder();

  const unitPrice = Number(garment.price || 0);
  const totalPrice = unitPrice * quantity;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    createOrder.mutate({
      garment: garment.id,
      look: lookId,
      size,
      color,
      quantity,
      customer_name: customerName.trim(),
      customer_phone: customerPhone.trim(),
      delivery_type: deliveryType,
      delivery_address: deliveryType === "DELIVERY" ? deliveryAddress.trim() : "",
      payment_method: paymentMethod,
      notes: notes.trim(),
    });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 p-3 backdrop-blur-sm sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-label="Kiyim sotib olish"
      onClick={onClose}
    >
      <div
        className="glass max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-3xl p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            {garment.cover_image && (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img src={garment.cover_image} alt={garment.name} className="size-16 rounded-2xl bg-white object-contain p-1" />
            )}
            <div>
              <h2 className="text-base font-extrabold">{garment.name}</h2>
              <p className="text-xs text-muted-foreground">
                {[garment.brand, garment.material].filter(Boolean).join(" · ") || garment.category.name}
              </p>
              <p className="mt-0.5 text-sm font-bold text-brand">
                {unitPrice > 0 ? `${Math.round(unitPrice).toLocaleString("uz-UZ")} so'm` : "Kelishilgan narx"}
              </p>
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label="Yopish" className="rounded-full p-1.5 hover:bg-muted">
            <XIcon className="size-5" />
          </button>
        </div>

        {createOrder.isSuccess ? (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <CheckCircle2Icon className="size-12 text-emerald-500" />
            <h3 className="text-lg font-extrabold">Buyurtmangiz qabul qilindi!</h3>
            <p className="text-sm text-muted-foreground">
              Operatorimiz tez orada <strong>{customerPhone}</strong> raqamiga bog&apos;lanib, o&apos;lcham ({size}) va
              yetkazib berish tafsilotlarini tasdiqlaydi.
            </p>
            <Button onClick={onClose}>Yopish</Button>
          </div>
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-3.5">
            {/* Razmer */}
            <div>
              <label className="mb-1.5 block text-xs font-bold">Razmer tanlang *</label>
              <div className="flex flex-wrap gap-1.5">
                {sizes.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setSize(s)}
                    className={cn(
                      "rounded-xl px-3 py-1.5 text-xs font-bold transition",
                      size === s ? "brand-gradient text-white" : "glass text-foreground hover:bg-muted",
                    )}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>

            {/* Rang & Soni */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs font-bold">Rang</label>
                <select
                  value={color}
                  onChange={(e) => setColor(e.target.value)}
                  className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm"
                >
                  {colors.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-bold">Soni (dona)</label>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={quantity}
                  onChange={(e) => setQuantity(Math.max(1, Number(e.target.value) || 1))}
                  className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm"
                />
              </div>
            </div>

            {/* Qabul qiluvchi */}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-bold">Ism-familiya *</label>
                <input
                  type="text"
                  required
                  value={customerName}
                  onChange={(e) => setCustomerName(e.target.value)}
                  placeholder="To'liq ismingiz"
                  className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-bold">Telefon raqam *</label>
                <input
                  type="tel"
                  required
                  value={customerPhone}
                  onChange={(e) => setCustomerPhone(e.target.value)}
                  placeholder="+998901234567"
                  className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm"
                />
              </div>
            </div>

            {/* Yetkazib berish & To'lov */}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-bold">Yetkazib berish</label>
                <select
                  value={deliveryType}
                  onChange={(e) => setDeliveryType(e.target.value as "DELIVERY" | "PICKUP")}
                  className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm"
                >
                  <option value="DELIVERY">
                    Kuryer ({garment.delivery_days ?? 2} kun ichida)
                  </option>
                  <option value="PICKUP">Do&apos;kondan olib ketish</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-bold">To&apos;lov usuli</label>
                <select
                  value={paymentMethod}
                  onChange={(e) => setPaymentMethod(e.target.value as "CASH" | "CARD")}
                  className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm"
                >
                  <option value="CASH">Naqd (yetkazilganda)</option>
                  <option value="CARD">Karta orqali (Click / Payme)</option>
                </select>
              </div>
            </div>

            {deliveryType === "DELIVERY" && (
              <div>
                <label className="mb-1 block text-xs font-bold">Yetkazib berish manzili *</label>
                <input
                  type="text"
                  required
                  value={deliveryAddress}
                  onChange={(e) => setDeliveryAddress(e.target.value)}
                  placeholder="Shahar, tuman, ko'cha, uy raqami"
                  className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm"
                />
              </div>
            )}

            <div>
              <label className="mb-1 block text-xs font-bold">Qo&apos;shimcha izoh (bo&apos;y, vazn, o&apos;lcham eslatmasi)</label>
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Masalan: bo'yim 178 sm, vaznim 75 kg"
                className="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm"
              />
            </div>

            {createOrder.error && <ErrorState error={createOrder.error} />}

            <div className="flex items-center justify-between gap-3 border-t border-border pt-3">
              <div>
                <p className="text-[11px] text-muted-foreground">Jami to&apos;lov:</p>
                <p className="text-base font-extrabold">
                  {totalPrice > 0 ? `${Math.round(totalPrice).toLocaleString("uz-UZ")} so'm` : "Kelishilgan narx"}
                </p>
              </div>
              <Button type="submit" size="lg" loading={createOrder.isPending}>
                <ShoppingBagIcon /> Buyurtmani tasdiqlash
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

function RealtimeAiStudio({ status }: { status: AiStatus }) {
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

function Busy({ title, note }: { title: string; note?: string | readonly string[] }) {
  const notes = useMemo(() => (Array.isArray(note) ? note : note ? [note] : []), [note]);
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    setIdx(0);
    if (notes.length <= 1) return;
    const timer = window.setInterval(() => {
      setIdx((prev) => (prev + 1) % notes.length);
    }, 4500);
    return () => window.clearInterval(timer);
  }, [notes]);

  const currentNote = notes[idx];

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/45 px-4 text-white backdrop-blur-[2px]"
    >
      <Loader2Icon className="size-9 animate-spin" />
      <p className="text-center text-base font-semibold">{title}</p>
      {currentNote && (
        <div className="min-h-8 max-w-xs text-center">
          <AnimatePresence mode="wait">
            <motion.p
              key={`${idx}-${currentNote}`}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.3 }}
              className="text-xs text-white/80"
            >
              {currentNote}
            </motion.p>
          </AnimatePresence>
        </div>
      )}
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
function SavedLooks({ isPremium = false }: { isPremium?: boolean }) {
  const looks = useSavedLooks();
  const remove = useDeleteLook();
  const [activeLook, setActiveLook] = useState<SavedLook | null>(null);
  const rows = looks.data?.results ?? [];

  useEffect(() => {
    if (!activeLook) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setActiveLook(null);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [activeLook]);

  return (
    <>
      <Card className="flex flex-col gap-3 p-3 sm:p-4">
        <div className="flex items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-bold">
            <ImagesIcon className="size-4" /> Saqlangan obrazlarim
          </h2>
          <span className="text-[11px] text-muted-foreground">
            {isPremium ? "Premium · logosiz yuklab olish" : "Yuklab olishda MarosimGo logosi"}
          </span>
        </div>
        {looks.error ? (
          <ErrorState error={looks.error} onRetry={() => looks.refetch()} />
        ) : looks.isPending ? (
          <Skeleton className="h-32 w-full rounded-2xl" />
        ) : rows.length === 0 ? (
          <EmptyState title="Hali saqlangan obraz yo'q" description="Rasm yoki video kiyib ko'rganingizda natijalar avtomatik shu yerda saqlanadi." />
        ) : (
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {rows.map((look) => (
              <li key={look.id} className="group relative overflow-hidden rounded-2xl bg-black">
                <button
                  type="button"
                  onClick={() => setActiveLook(look)}
                  aria-label={look.video ? "Videoni ko'rish" : "Rasmni kattalashtirish"}
                  className="relative block aspect-[3/4] w-full overflow-hidden text-left"
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- owner-only API URL */}
                  <img
                    src={look.image}
                    alt={look.garment?.name ?? "Saqlangan obraz"}
                    loading="lazy"
                    className="h-full w-full object-cover transition duration-300 group-hover:scale-105"
                  />
                  {look.video && (
                    <>
                      <span className="brand-gradient pointer-events-none absolute top-2 left-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold text-white shadow">
                        <VideoIcon className="size-3" /> Video
                      </span>
                      <span className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/15 transition group-hover:bg-black/30">
                        <span className="brand-gradient flex size-11 items-center justify-center rounded-full text-white shadow-lg ring-4 ring-white/25 transition group-hover:scale-110">
                          <PlayIcon className="ml-0.5 size-5 fill-current" />
                        </span>
                      </span>
                    </>
                  )}
                </button>
                <div className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-1 bg-gradient-to-t from-black/85 via-black/45 to-transparent p-2 pt-6">
                  <span className="truncate text-[11px] font-semibold text-white">{look.garment?.name ?? "—"}</span>
                  <div className="flex items-center gap-1">
                    <a
                      href={aiApi.downloadUrl(look.id)}
                      download={`marosimgo-look-${look.id.slice(0, 8)}.${look.video ? "mp4" : "jpg"}`}
                      aria-label="Yuklab olish"
                      className="rounded-full bg-white/15 p-1.5 text-white transition hover:bg-blue-500/80"
                    >
                      <DownloadIcon className="size-3.5" />
                    </a>
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
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* MarosimGo Media / Video Player Modal (portaled to document.body so it always centers in the viewport) */}
      {typeof document !== "undefined" &&
        createPortal(
          <AnimatePresence>
            {activeLook && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                onClick={() => setActiveLook(null)}
                className="fixed inset-0 z-[100] flex h-dvh w-screen items-center justify-center bg-black/80 p-3 backdrop-blur-md sm:p-6"
              >
                <motion.div
                  initial={{ opacity: 0, scale: 0.96, y: 8 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.96, y: 8 }}
                  transition={{ duration: 0.2 }}
                  onClick={(e) => e.stopPropagation()}
                  className="glass relative flex max-h-[92dvh] w-full max-w-xl flex-col overflow-hidden rounded-3xl border border-white/15 bg-neutral-950 shadow-2xl"
                >
                  <button
                    type="button"
                    onClick={() => setActiveLook(null)}
                    aria-label="Yopish"
                    className="absolute top-3 right-3 z-20 flex size-9 items-center justify-center rounded-full bg-black/60 text-white backdrop-blur-md transition hover:bg-black/85"
                  >
                    <XIcon className="size-4" />
                  </button>

                  {activeLook.video ? (
                    <MarosimVideoPlayer
                      src={activeLook.video}
                      poster={activeLook.image}
                      title={activeLook.garment?.name ?? "MarosimGo AI Video"}
                      className="w-full"
                    />
                  ) : (
                    /* eslint-disable-next-line @next/next/no-img-element -- owner-only API URL */
                    <img
                      src={activeLook.image}
                      alt={activeLook.garment?.name ?? "Saqlangan obraz"}
                      className="max-h-[72dvh] w-full bg-black object-contain"
                    />
                  )}

                  <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/10 bg-neutral-950/95 px-4 py-3 text-white">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-bold">{activeLook.garment?.name ?? "Saqlangan obraz"}</p>
                      <p className="text-[11px] text-white/60">
                        {activeLook.video ? "AI Video Try-On · MP4" : "AI Foto Try-On"}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <a
                        href={aiApi.downloadUrl(activeLook.id)}
                        download={`marosimgo-look-${activeLook.id.slice(0, 8)}.${activeLook.video ? "mp4" : "jpg"}`}
                        className="brand-gradient inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 text-xs font-semibold text-white shadow transition hover:brightness-110"
                      >
                        <DownloadIcon className="size-3.5" />
                        {activeLook.video ? "Videoni yuklab olish" : "Yuklab olish"}
                      </a>
                      <button
                        type="button"
                        onClick={() => {
                          const id = activeLook.id;
                          setActiveLook(null);
                          remove.mutate(id);
                        }}
                        aria-label="O'chirish"
                        className="inline-flex items-center gap-1 rounded-full bg-white/10 px-3 py-2 text-xs font-semibold text-white/85 transition hover:bg-red-500/80 hover:text-white"
                      >
                        <Trash2Icon className="size-3.5" /> O&apos;chirish
                      </button>
                    </div>
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

