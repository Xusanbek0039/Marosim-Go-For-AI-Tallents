/**
 * MarosimGo AI Fashion Studio — one live try-on session with Decart `lucy-vton` (WebRTC via
 * `@decartai/sdk`). Framework-free so it can be unit-tested; `studio.tsx` wires the real
 * camera / SDK / API in through `StudioDeps`.
 *
 * Flow: camera → server session (consent, limits) → SDK connect with a short-lived client token
 * (`apiKeyProvider` asks our server before every dial and reconnect) → Decart streams back the
 * person wearing the garment → `setImage` switches garments without reconnecting → end: disconnect,
 * stop the camera, report measured metrics. The server never receives video.
 */

import type { AiEndReason, AiMetrics, AiSession } from "@/lib/ai-tryon";

export type Phase =
  | "idle" // nothing opened yet (consent screen)
  | "unsupported" // no camera API / WebRTC in this browser
  | "requesting-camera"
  | "camera-denied"
  | "camera-unavailable"
  | "camera-ready" // local preview, no AI yet
  | "starting" // creating the server session
  | "connecting" // WebRTC dial to Decart
  | "processing" // connected, waiting for the first generated frame
  | "live" // Decart is generating: the remote stream is the main preview
  | "switching" // a new garment is being applied on the live connection
  | "reconnecting"
  | "network-error"
  | "provider-error"
  | "limit" // daily budget / concurrent session / not configured
  | "expired" // the session's time budget ran out
  | "paused" // ended because the page was hidden (saves cost)
  | "finished";

export interface StudioState {
  phase: Phase;
  message?: string;
  /** Decart's processed stream; the only thing shown as the try-on result. */
  remoteStream?: MediaStream;
  localStream?: MediaStream;
  sessionId?: string;
  expiresAt?: number;
  garmentId?: string;
  metrics: AiMetrics;
}

export interface GarmentInput {
  id: string;
  referenceUrl: string;
  prompt: string;
}

/** The subset of the SDK's RealTimeClient this controller uses (see @decartai/sdk realtime/client.d.ts). */
export interface LiveClient {
  setImage(image: Blob, options?: { prompt?: string | null; enhance?: boolean }): Promise<void>;
  disconnect(): void;
  on(event: string, listener: (data: unknown) => void): void;
}

export interface ConnectArgs {
  stream: MediaStream;
  image: Blob;
  prompt: string;
  apiKeyProvider: () => Promise<string>;
  onRemoteStream: (stream: MediaStream) => void;
  onConnectionChange: (state: string) => void;
}

export interface StudioDeps {
  hasSupport(): boolean;
  getCamera(): Promise<MediaStream>;
  connect(args: ConnectArgs): Promise<LiveClient>;
  api: {
    start(): Promise<AiSession>;
    status(): Promise<{ active_session: string | null }>;
    token(sessionId: string): Promise<{ api_key: string }>;
    finish(sessionId: string, reason: AiEndReason, metrics: AiMetrics): Promise<unknown>;
  };
  fetchImage(url: string): Promise<Blob>;
  now(): number;
  setTimer(fn: () => void, ms: number): unknown;
  clearTimer(handle: unknown): void;
}

interface ApiLikeError {
  status?: number;
  code?: string;
  message?: string;
}

const LIMIT_CODES = new Set([
  "ai_daily_session_limit",
  "ai_daily_time_limit",
  "ai_token_limit",
  "ai_tryon_not_configured",
]);

/** Decart `sessionEnded.reason` → our end reason + what to tell the user. */
const SESSION_END: Record<string, [AiEndReason, string]> = {
  moderation_violation: ["MODERATION", "AI xizmati seansni moderatsiya sababli to'xtatdi."],
  policy_violation: ["MODERATION", "AI xizmati seansni qoidalar sababli to'xtatdi."],
  insufficient_credits: ["INSUFFICIENT_CREDITS", "AI xizmati vaqtincha mavjud emas."],
  session_limit: ["SESSION_LIMIT", "AI xizmati hozir band. Birozdan so'ng qayta urinib ko'ring."],
};

export class StudioSession {
  private state: StudioState = { phase: "idle", metrics: {} };
  private listeners = new Set<(s: StudioState) => void>();
  private client: LiveClient | null = null;
  private session: AiSession | null = null;
  private expiryTimer: unknown = null;
  private connectStartedAt = 0;
  private switchSeq = 0;
  private ending = false;
  /** Bumped on every start/end: events of a connection that is no longer current are ignored. */
  private generation = 0;
  private fpsSamples: number[] = [];
  private garmentsTried = new Set<string>();
  private images = new Map<string, Promise<Blob>>();

  private deps: StudioDeps;

  constructor(deps: StudioDeps) {
    this.deps = deps;
  }

  get snapshot(): StudioState {
    return this.state;
  }

  subscribe(listener: (s: StudioState) => void): () => void {
    this.listeners.add(listener);
    listener(this.state);
    return () => this.listeners.delete(listener);
  }

  private set(patch: Partial<StudioState>) {
    this.state = { ...this.state, ...patch, metrics: { ...this.state.metrics, ...patch.metrics } };
    for (const l of this.listeners) l(this.state);
  }

  // ---------------------------------------------------------------- camera
  async openCamera(): Promise<void> {
    if (!this.deps.hasSupport()) {
      this.set({ phase: "unsupported", message: "Bu brauzer kamera yoki WebRTC'ni qo'llab-quvvatlamaydi." });
      return;
    }
    if (this.state.localStream) return this.set({ phase: "camera-ready" });
    this.set({ phase: "requesting-camera", message: undefined });
    try {
      const stream = await this.deps.getCamera();
      this.set({ phase: "camera-ready", localStream: stream });
    } catch (error) {
      const name = (error as { name?: string })?.name;
      if (name === "NotAllowedError" || name === "SecurityError") {
        this.set({ phase: "camera-denied", message: "Kameraga ruxsat berilmadi." });
      } else {
        this.set({ phase: "camera-unavailable", message: "Kamera topilmadi yoki boshqa dastur band qilgan." });
      }
    }
  }

  private image(garment: GarmentInput): Promise<Blob> {
    let pending = this.images.get(garment.id);
    if (!pending) {
      pending = this.deps.fetchImage(garment.referenceUrl);
      pending.catch(() => this.images.delete(garment.id));
      this.images.set(garment.id, pending);
    }
    return pending;
  }

  // ---------------------------------------------------------------- start
  async start(garment: GarmentInput): Promise<void> {
    const stream = this.state.localStream;
    if (!stream || this.client || ["starting", "connecting"].includes(this.state.phase)) return;
    this.ending = false;
    const gen = ++this.generation;
    const current = () => gen === this.generation;
    this.fpsSamples = [];
    this.garmentsTried = new Set([garment.id]);
    this.set({ phase: "starting", message: undefined, garmentId: garment.id, metrics: { interruptions: 0 } });

    let session: AiSession;
    try {
      session = await this.createSession();
    } catch (error) {
      return this.failStart(error);
    }
    if (!current()) {
      void this.deps.api.finish(session.id, "USER", {}).catch(() => undefined); // closed while starting
      return;
    }
    this.session = session;
    const expiresAt = Date.parse(session.expires_at);
    this.set({ sessionId: session.id, expiresAt });
    this.expiryTimer = this.deps.setTimer(() => void this.end("EXPIRED"), Math.max(0, expiresAt - this.deps.now()));

    try {
      const image = await this.image(garment);
      this.connectStartedAt = this.deps.now();
      this.set({ phase: "connecting" });
      const client = await this.deps.connect({
        stream,
        image,
        prompt: garment.prompt,
        apiKeyProvider: async () => (await this.deps.api.token(session.id)).api_key,
        onRemoteStream: (remote) => current() && this.set({ remoteStream: remote }),
        onConnectionChange: (s) => current() && this.onConnectionChange(s),
      });
      if (!current()) {
        client.disconnect(); // ended while dialling
        return;
      }
      this.client = client;
      client.on("error", (e) => current() && this.onError(e));
      client.on("sessionEnded", (e) => current() && this.onSessionEnded(e));
      client.on("generationTick", (e) => current() && this.onTick(e));
      client.on("stats", (e) => current() && this.onStats(e));
    } catch (error) {
      if (current()) await this.fail(error);
    }
  }

  /** One ACTIVE session per user: a session left over from a closed tab is finished first. */
  private async createSession(): Promise<AiSession> {
    try {
      return await this.deps.api.start();
    } catch (error) {
      if ((error as ApiLikeError).code !== "ai_session_already_active") throw error;
      const { active_session } = await this.deps.api.status();
      if (active_session) await this.deps.api.finish(active_session, "OTHER", {});
      return this.deps.api.start();
    }
  }

  private failStart(error: unknown) {
    const e = error as ApiLikeError;
    if (e.code && LIMIT_CODES.has(e.code)) return this.set({ phase: "limit", message: e.message });
    if (e.code === "network_error" || e.status === 0) return this.set({ phase: "network-error", message: e.message });
    this.set({ phase: "provider-error", message: e.message ?? "AI seansini boshlab bo'lmadi." });
  }

  // ---------------------------------------------------------------- live events
  private onConnectionChange(state: string) {
    if (this.ending) return;
    if (state === "connecting") this.set({ phase: "connecting" });
    else if (state === "connected") this.set({ phase: "processing" });
    else if (state === "generating") {
      const first = this.state.metrics.connect_ms === undefined;
      this.set({
        phase: this.state.phase === "switching" ? "switching" : "live",
        metrics: first ? { connect_ms: Math.round(this.deps.now() - this.connectStartedAt) } : {},
      });
    } else if (state === "reconnecting") {
      this.set({ phase: "reconnecting", metrics: { interruptions: (this.state.metrics.interruptions ?? 0) + 1 } });
    } else if (state === "disconnected") {
      // The SDK already retried; it ends here only after giving up (or after our own disconnect).
      void this.end("NETWORK_ERROR", { phase: "network-error", message: "Aloqa uzildi. Qayta ulaning." });
    }
  }

  private onError(error: unknown) {
    const code = (error as { code?: string })?.code ?? "";
    // WEBRTC_WEBSOCKET/ICE/TIMEOUT/SERVER/SIGNALING_ERROR (SDK 0.2.14): the SDK retries on its own;
    // a lost connection ends with "disconnected" and a terminal one with "sessionEnded".
    if (code.startsWith("WEBRTC_")) return;
    const message =
      code === "TOKEN_EXPIRED" || code === "INVALID_API_KEY" || code === "TOKEN_INVALID"
        ? "AI xizmatiga ruxsat tugadi. Qayta boshlang."
        : "AI xizmatida xatolik yuz berdi.";
    void this.end("PROVIDER_ERROR", { phase: "provider-error", message });
  }

  private onSessionEnded(event: unknown) {
    const reason = String((event as { reason?: string })?.reason ?? "");
    const [ours, message] = SESSION_END[reason] ?? ["PROVIDER_ERROR", "AI xizmati seansni yakunladi."];
    void this.end(ours, { phase: ours === "SESSION_LIMIT" ? "limit" : "provider-error", message });
  }

  private onTick(event: unknown) {
    const seconds = Number((event as { seconds?: number })?.seconds);
    if (Number.isFinite(seconds)) {
      const current = this.state.metrics.generation_seconds ?? 0;
      this.set({ metrics: { generation_seconds: Math.max(current, Math.round(seconds * 10) / 10) } });
    }
  }

  private onStats(event: unknown) {
    const stats = event as {
      video?: { framesPerSecond?: number };
      glassToGlass?: { medianMs?: number | null; ttffMs?: number | null } | null;
    };
    const fps = stats?.video?.framesPerSecond;
    if (typeof fps === "number" && fps > 0) {
      this.fpsSamples.push(fps);
      if (this.fpsSamples.length > 120) this.fpsSamples.shift();
    }
    const avg = this.fpsSamples.length
      ? Math.round((this.fpsSamples.reduce((a, b) => a + b, 0) / this.fpsSamples.length) * 10) / 10
      : undefined;
    const g2g = stats?.glassToGlass;
    this.set({
      metrics: {
        ...(avg !== undefined ? { fps: avg } : {}),
        ...(typeof g2g?.medianMs === "number" ? { glass_to_glass_ms: Math.round(g2g.medianMs) } : {}),
        ...(typeof g2g?.ttffMs === "number" ? { first_frame_ms: Math.round(g2g.ttffMs) } : {}),
      },
    });
  }

  // ---------------------------------------------------------------- switching
  async switchGarment(garment: GarmentInput): Promise<void> {
    if (!this.client || !["live", "switching", "processing"].includes(this.state.phase)) return;
    const seq = ++this.switchSeq;
    this.garmentsTried.add(garment.id);
    this.set({ phase: "switching", garmentId: garment.id, metrics: { garments_tried: this.garmentsTried.size } });
    try {
      const image = await this.image(garment);
      if (seq !== this.switchSeq || !this.client) return; // a newer choice won
      await this.client.setImage(image, { prompt: garment.prompt || null, enhance: false });
      if (seq === this.switchSeq && this.state.phase === "switching") this.set({ phase: "live" });
    } catch {
      if (seq === this.switchSeq && this.client) {
        this.set({ phase: "live", message: "Kiyimni almashtirib bo'lmadi. Qayta tanlang." });
      }
    }
  }

  // ---------------------------------------------------------------- end
  private async fail(error: unknown) {
    const code = (error as { code?: string })?.code;
    const reason: AiEndReason = code === "network_error" ? "NETWORK_ERROR" : "PROVIDER_ERROR";
    const e = error as ApiLikeError;
    const phase: Phase = e.code && LIMIT_CODES.has(e.code) ? "limit" : reason === "NETWORK_ERROR" ? "network-error" : "provider-error";
    await this.end(reason, { phase, message: e.message ?? "AI xizmatiga ulanib bo'lmadi." });
  }

  /** Idempotent: disconnect from Decart, keep or stop the camera, report metrics once. */
  async end(reason: AiEndReason, next?: Partial<StudioState>, { stopCamera = false } = {}): Promise<void> {
    if (this.ending && !stopCamera) return;
    const firstCall = !this.ending;
    this.ending = true;
    this.generation++;
    this.switchSeq++;
    if (this.expiryTimer !== null) {
      this.deps.clearTimer(this.expiryTimer);
      this.expiryTimer = null;
    }
    const client = this.client;
    this.client = null;
    client?.disconnect();
    const session = this.session;
    this.session = null;

    if (stopCamera) {
      for (const track of this.state.localStream?.getTracks() ?? []) track.stop();
    }
    const fallback: Phase =
      reason === "EXPIRED" ? "expired" : reason === "PAGE_HIDDEN" ? "paused" : stopCamera ? "finished" : "camera-ready";
    this.set({
      phase: next?.phase ?? fallback,
      message: next?.message ?? (reason === "EXPIRED" ? "Seans vaqti tugadi." : undefined),
      remoteStream: undefined,
      ...(stopCamera ? { localStream: undefined } : {}),
    });
    if (firstCall && session) {
      try {
        await this.deps.api.finish(session.id, reason, this.state.metrics);
      } catch {
        /* the server also closes it at expires_at */
      }
    }
    if (!stopCamera) this.ending = false;
  }

  /** Leave the studio: end any session and release the camera. */
  async close(): Promise<void> {
    await this.end("USER", undefined, { stopCamera: true });
  }
}
