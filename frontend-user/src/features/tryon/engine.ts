/**
 * Live try-on engine: camera → MediaPipe pose → body frame → WebGL composite, all on the device.
 *
 * React only creates it, feeds it the selected garment and listens to `onStatus` (called when
 * something the UI shows changes — never per frame). Switching the garment never touches the
 * camera stream or the tracker; only `switchCamera()` re-opens the camera, and `stop()` releases
 * everything (tracks, loops, tracker, GPU).
 */

import type { PoseLandmarker } from "@mediapipe/tasks-vision";

import type { GarmentAsset } from "@/lib/tryon";

import {
  anchorShoulderWidth,
  bodyFrame,
  bodyMesh,
  type BodyAnchors,
  type BodyFrame,
  type Landmark,
  LandmarkSmoother,
  limbQuad,
  type LimbAnchors,
  type LowerAnchors,
  lowerMesh,
  makeGrid,
  occluders,
  yawOpacity,
} from "./geometry";
import { type DrawLayer, GLRenderer } from "./gl-renderer";

export type Facing = "user" | "environment";
export type Tracking = "searching" | "tracking" | "lost";
export type EngineErrorCode =
  | "insecure"
  | "unsupported"
  | "denied"
  | "no-camera"
  | "busy"
  | "model"
  | "webgl"
  | "asset"
  | "unknown";

export interface EngineStatus {
  phase: "starting" | "running" | "error" | "stopped";
  facing: Facing;
  tracking: Tracking;
  hint: string | null;
  /** Garment id that is on screen now (null = none). */
  garmentId: string | null;
  loadingGarmentId: string | null;
  economy: boolean;
  fps: number;
  error: { code: EngineErrorCode; message: string } | null;
}

export interface GarmentInput {
  id: string;
  assets: GarmentAsset[];
}

export const ERROR_MESSAGES: Record<EngineErrorCode, string> = {
  insecure: "Kamera faqat xavfsiz (HTTPS) ulanishda ishlaydi.",
  unsupported: "Brauzeringiz jonli kamerani qo'llab-quvvatlamaydi. Chrome yoki Safari'ning yangi versiyasidan foydalaning.",
  denied: "Kameraga ruxsat berilmadi. Brauzer sozlamalaridan shu sayt uchun kamerani yoqing va qayta urinib ko'ring.",
  "no-camera": "Qurilmada kamera topilmadi.",
  busy: "Kamera boshqa ilova tomonidan band. Uni yopib, qayta urinib ko'ring.",
  model: "Tana kuzatuv modelini yuklab bo'lmadi. Internetni tekshirib, qayta urinib ko'ring.",
  webgl: "Qurilmangiz grafikasi (WebGL2) jonli kiyib ko'rish uchun yetarli emas.",
  asset: "Bu kiyimning AR qatlamini yuklab bo'lmadi.",
  unknown: "Kamerani ishga tushirib bo'lmadi.",
};

const WASM_PATH = "/mediapipe/wasm";
const MODEL_PATH = "/mediapipe/pose_landmarker_lite.task";
const LOST_AFTER = 0.35; // s without a body before the garment fades out
const RESET_AFTER = 0.8; // s lost → restart smoothing (no sweep from the old position)
const BODY_GRID = makeGrid(10, 22);
const LIMB_GRID = makeGrid(1, 1);
const SLEEVES = ["RIGHT_UPPER_ARM", "RIGHT_FOREARM", "LEFT_UPPER_ARM", "LEFT_FOREARM"] as const;
type SleeveKind = (typeof SLEEVES)[number];

/** Browser support check that needs no permission. */
export function checkSupport(): EngineErrorCode | null {
  if (typeof window === "undefined") return "unsupported";
  if (!window.isSecureContext) return "insecure";
  if (!navigator.mediaDevices?.getUserMedia) return "unsupported";
  const probe = document.createElement("canvas").getContext("webgl2");
  if (!probe) return "webgl";
  probe.getExtension("WEBGL_lose_context")?.loseContext();
  return null;
}

function cameraError(error: unknown): EngineErrorCode {
  const name = (error as DOMException)?.name;
  if (name === "NotAllowedError" || name === "SecurityError") return "denied";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "no-camera";
  if (name === "NotReadableError" || name === "AbortError") return "busy";
  return "unknown";
}

// ------------------------------------------------------------- asset cache
interface LayerImage {
  image: HTMLImageElement;
  anchors: Record<string, unknown>;
}

interface GarmentImages {
  front: LayerImage;
  back: LayerImage | null;
  lower: LayerImage | null;
  sleeves: Partial<Record<SleeveKind, LayerImage>>;
}

function loadImage(url: string): Promise<HTMLImageElement> {
  const img = new Image();
  img.decoding = "async";
  img.src = url;
  return img.decode().then(() => img);
}

/** Decoded garment images, newest last; at most 8 garments kept in memory. */
const imageCache = new Map<string, Promise<GarmentImages>>();

function garmentImages(input: GarmentInput): Promise<GarmentImages> {
  const key = `${input.id}:${input.assets.map((a) => a.updated_at).join(",")}`;
  const hit = imageCache.get(key);
  if (hit) {
    imageCache.delete(key);
    imageCache.set(key, hit);
    return hit;
  }
  const byKind = new Map(input.assets.map((a) => [a.kind, a]));
  const layer = async (kind: string): Promise<LayerImage | null> => {
    const asset = byKind.get(kind as GarmentAsset["kind"]);
    return asset ? { image: await loadImage(asset.url), anchors: asset.anchors } : null;
  };
  const promise = (async () => {
    const [front, back, lower, ...sleeves] = await Promise.all([
      layer("BODY_FRONT"),
      layer("BODY_BACK"),
      layer("LOWER_BODY"),
      ...SLEEVES.map(layer),
    ]);
    if (!front) throw new Error("no-front-layer");
    const map: GarmentImages["sleeves"] = {};
    SLEEVES.forEach((kind, i) => {
      if (sleeves[i]) map[kind] = sleeves[i]!;
    });
    return { front, back, lower, sleeves: map };
  })();
  promise.catch(() => imageCache.delete(key));
  imageCache.set(key, promise);
  while (imageCache.size > 8) imageCache.delete(imageCache.keys().next().value!);
  return promise;
}

/** Starts decoding a garment's layers before the user picks it (carousel neighbours). */
export function prefetchGarment(input: GarmentInput) {
  garmentImages(input).catch(() => undefined);
}

// ----------------------------------------------------------------- engine
interface GpuLayer {
  texture: WebGLTexture;
  anchors: Record<string, unknown>;
  w: number;
  h: number;
}

interface ActiveGarment {
  id: string;
  front: GpuLayer;
  back: GpuLayer | null;
  lower: GpuLayer | null;
  sleeves: Partial<Record<SleeveKind, GpuLayer>>;
}

export class TryOnEngine {
  private stream: MediaStream | null = null;
  private renderer: GLRenderer | null = null;
  private landmarker: PoseLandmarker | null = null;
  private smoother = new LandmarkSmoother();
  private garment: ActiveGarment | null = null;
  private garmentToken = 0;
  private loop = 0;
  private stopped = false;
  private status: EngineStatus;
  private facing: Facing = "user";

  // tracking state
  private lastFrame: BodyFrame | null = null;
  private lostFor = 0;
  private everTracked = false;
  private alpha = 0;
  private lastTick = 0;
  private lastDetect = 0;
  private detectInterval = 0;
  private detectMs = 16;
  private slowSince = 0;
  private torsoRatio = 1.45;
  private light = 1;
  private frames = 0;
  private fpsWindowStart = 0;
  private lightCanvas: CanvasRenderingContext2D | null = null;
  private bodyPositions = new Float32Array(BODY_GRID.uv.length);
  private lowerPositions = new Float32Array(BODY_GRID.uv.length);
  private captureRequest: ((blob: Blob | null) => void) | null = null;

  /** Diagnostics for tests: how often the camera was opened, and garments swapped. */
  readonly stats = { cameraStarts: 0, garmentSwaps: 0 };

  /**
   * The engine draws into its own, fresh <canvas> inside `host`. A WebGL context lives as long as
   * its canvas, and `stop()` gives the context back to the browser — so a canvas is never reused
   * (React StrictMode and "retry" create a second engine right after the first one stopped).
   */
  private canvas: HTMLCanvasElement;

  constructor(
    private video: HTMLVideoElement,
    host: HTMLElement,
    private onStatus: (status: EngineStatus) => void,
  ) {
    this.canvas = document.createElement("canvas");
    this.canvas.className = "absolute inset-0 size-full object-cover";
    this.canvas.dataset.testid = "tryon-canvas";
    this.canvas.setAttribute("aria-hidden", "true");
    host.appendChild(this.canvas);
    this.status = {
      phase: "starting",
      facing: "user",
      tracking: "searching",
      hint: null,
      garmentId: null,
      loadingGarmentId: null,
      economy: false,
      fps: 0,
      error: null,
    };
  }

  private set(patch: Partial<EngineStatus>) {
    let changed = false;
    for (const [k, v] of Object.entries(patch) as [keyof EngineStatus, unknown][]) {
      if (this.status[k] !== v) changed = true;
    }
    if (!changed || this.stopped) return;
    this.status = { ...this.status, ...patch };
    this.canvas.dataset.cameraStarts = String(this.stats.cameraStarts);
    this.canvas.dataset.garmentSwaps = String(this.stats.garmentSwaps);
    this.canvas.dataset.garment = this.status.garmentId ?? "";
    this.onStatus(this.status);
  }

  private fail(code: EngineErrorCode) {
    this.set({ phase: "error", error: { code, message: ERROR_MESSAGES[code] } });
  }

  // ------------------------------------------------------------ lifecycle
  async start(facing: Facing = "user") {
    const unsupported = checkSupport();
    if (unsupported) return this.fail(unsupported);
    this.facing = facing;
    try {
      this.renderer = new GLRenderer(this.canvas);
    } catch {
      return this.fail("webgl");
    }
    this.canvas.addEventListener("webglcontextlost", this.onContextLost);
    // Camera permission and the tracker download run in parallel.
    const tracker = this.loadLandmarker();
    if (!(await this.openCamera(facing))) return;
    try {
      this.landmarker = await tracker;
    } catch {
      return this.fail("model");
    }
    if (this.stopped) {
      this.landmarker?.close();
      return;
    }
    this.set({ phase: "running", facing });
    this.scheduleNext();
  }

  private async loadLandmarker(): Promise<PoseLandmarker> {
    const { FilesetResolver, PoseLandmarker } = await import("@mediapipe/tasks-vision");
    const fileset = await FilesetResolver.forVisionTasks(WASM_PATH);
    const options = (delegate: "GPU" | "CPU") => ({
      baseOptions: { modelAssetPath: MODEL_PATH, delegate },
      runningMode: "VIDEO" as const,
      numPoses: 1,
      minPoseDetectionConfidence: 0.5,
      minPosePresenceConfidence: 0.5,
      minTrackingConfidence: 0.5,
    });
    try {
      return await PoseLandmarker.createFromOptions(fileset, options("GPU"));
    } catch {
      return PoseLandmarker.createFromOptions(fileset, options("CPU"));
    }
  }

  private async openCamera(facing: Facing): Promise<boolean> {
    const economy = this.status.economy;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: facing,
          width: { ideal: economy ? 640 : 1280 },
          height: { ideal: economy ? 480 : 720 },
          frameRate: { ideal: 30, max: 30 },
        },
      });
      if (this.stopped) {
        stream.getTracks().forEach((t) => t.stop());
        return false;
      }
      this.stream = stream;
      this.stats.cameraStarts += 1;
      // The OS took the camera away (another app, the phone locked): say so, offer a retry.
      stream.getVideoTracks()[0]?.addEventListener("ended", () => {
        if (this.stream === stream && !this.stopped) this.fail("busy");
      });
      this.video.srcObject = stream;
      this.video.muted = true;
      this.video.playsInline = true;
      await this.video.play();
      return true;
    } catch (error) {
      if (!this.stopped) this.fail(cameraError(error));
      return false;
    }
  }

  private releaseCamera() {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video.pause();
    this.video.srcObject = null;
  }

  /** Front ↔ back camera. The only action that re-opens the camera. */
  async switchCamera() {
    if (this.status.phase !== "running") return;
    const next: Facing = this.facing === "user" ? "environment" : "user";
    this.cancelLoop();
    this.releaseCamera();
    this.resetTracking();
    if (!(await this.openCamera(next))) {
      // Fall back to the camera that worked.
      this.set({ phase: "starting", error: null });
      if (!(await this.openCamera(this.facing))) return;
      this.set({ phase: "running" });
      this.scheduleNext();
      return;
    }
    this.facing = next;
    this.set({ facing: next, phase: "running" });
    this.scheduleNext();
  }

  /** Releases the camera, loops, tracker and GPU. Safe to call twice. */
  stop() {
    if (this.stopped) return;
    this.set({ phase: "stopped" });
    this.stopped = true;
    this.cancelLoop();
    this.releaseCamera();
    this.garmentToken += 1;
    this.landmarker?.close();
    this.landmarker = null;
    this.canvas.removeEventListener("webglcontextlost", this.onContextLost);
    this.renderer?.dispose();
    this.renderer = null;
    this.canvas.remove();
    this.garment = null;
    this.captureRequest?.(null);
    this.captureRequest = null;
  }

  /** True while a camera track is live (used by tests and the UI). */
  get cameraLive() {
    return Boolean(this.stream?.getTracks().some((t) => t.readyState === "live"));
  }

  private onContextLost = (event: Event) => {
    event.preventDefault();
    this.fail("webgl");
  };

  // -------------------------------------------------------------- garment
  /**
   * Shows `input` instead of the current garment. The old one stays on screen until the new one
   * is decoded and on the GPU, then they are swapped between two frames — never both at once.
   */
  async setGarment(input: GarmentInput | null): Promise<void> {
    const token = ++this.garmentToken;
    if (!input) {
      this.swap(null);
      this.set({ loadingGarmentId: null });
      return;
    }
    if (this.garment?.id === input.id) return;
    this.set({ loadingGarmentId: input.id });
    try {
      const images = await garmentImages(input);
      if (token !== this.garmentToken || this.stopped || !this.renderer) return;
      const renderer = this.renderer;
      const gpu = (layer: LayerImage): GpuLayer => ({
        texture: renderer.createTexture(layer.image),
        anchors: layer.anchors,
        w: layer.image.naturalWidth,
        h: layer.image.naturalHeight,
      });
      const sleeves: ActiveGarment["sleeves"] = {};
      for (const kind of SLEEVES) {
        const layer = images.sleeves[kind];
        if (layer) sleeves[kind] = gpu(layer);
      }
      this.swap({
        id: input.id,
        front: gpu(images.front),
        back: images.back ? gpu(images.back) : null,
        lower: images.lower ? gpu(images.lower) : null,
        sleeves,
      });
      this.set({ loadingGarmentId: null });
    } catch {
      if (token !== this.garmentToken) return;
      this.set({ loadingGarmentId: null });
      throw new Error("asset");
    }
  }

  private swap(next: ActiveGarment | null) {
    const old = this.garment;
    this.garment = next;
    if (old && this.renderer) {
      const layers = [old.front, old.back, old.lower, ...Object.values(old.sleeves)].filter(Boolean) as GpuLayer[];
      layers.forEach((l) => this.renderer!.deleteTexture(l.texture));
    }
    if (next) this.stats.garmentSwaps += 1;
    this.set({ garmentId: next?.id ?? null });
  }

  // ------------------------------------------------------------- capture
  /** The composite of the next frame as a JPEG, mirrored like the preview. Never uploaded. */
  capture(): Promise<Blob | null> {
    if (this.status.phase !== "running") return Promise.resolve(null);
    this.captureRequest?.(null);
    return new Promise((resolve) => (this.captureRequest = resolve));
  }

  private fulfilCapture() {
    const resolve = this.captureRequest;
    if (!resolve) return;
    this.captureRequest = null;
    // Right after drawing, in the same task, the WebGL drawing buffer is still valid.
    const out = document.createElement("canvas");
    out.width = this.canvas.width;
    out.height = this.canvas.height;
    const ctx = out.getContext("2d")!;
    if (this.facing === "user") {
      ctx.translate(out.width, 0);
      ctx.scale(-1, 1);
    }
    ctx.drawImage(this.canvas, 0, 0);
    out.toBlob((blob) => resolve(blob), "image/jpeg", 0.92);
  }

  // ---------------------------------------------------------------- loop
  private scheduleNext() {
    if (this.stopped) return;
    const v = this.video as HTMLVideoElement & {
      requestVideoFrameCallback?: (cb: () => void) => number;
    };
    if (typeof v.requestVideoFrameCallback === "function") {
      this.loop = v.requestVideoFrameCallback(this.tick);
    } else {
      this.loop = requestAnimationFrame(this.tick);
    }
  }

  private cancelLoop() {
    const v = this.video as HTMLVideoElement & { cancelVideoFrameCallback?: (id: number) => void };
    if (typeof v.cancelVideoFrameCallback === "function") v.cancelVideoFrameCallback(this.loop);
    cancelAnimationFrame(this.loop);
  }

  private resetTracking() {
    this.smoother.reset();
    this.lastFrame = null;
    this.lostFor = 0;
    this.alpha = 0;
    this.everTracked = false;
    this.set({ tracking: "searching" });
  }

  private tick = () => {
    if (this.stopped || !this.renderer || !this.landmarker) return;
    const now = performance.now();
    const dt = this.lastTick ? Math.min((now - this.lastTick) / 1000, 0.1) : 0;
    this.lastTick = now;
    const video = this.video;
    if (video.readyState >= 2 && video.videoWidth) {
      if (now - this.lastDetect >= this.detectInterval) this.detect(now);
      this.updateTracking(dt);
      this.renderer.draw(video, this.composeFrame());
      this.fulfilCapture();
      this.measure(now);
    }
    this.scheduleNext();
  };

  private detect(now: number) {
    const t0 = performance.now();
    let landmarks: Landmark[] | undefined;
    try {
      landmarks = this.landmarker!.detectForVideo(this.video, now).landmarks[0];
    } catch {
      landmarks = undefined;
    }
    this.detectMs = this.detectMs * 0.9 + (performance.now() - t0) * 0.1;
    this.lastDetect = now;

    const step = Math.max(this.detectInterval / 1000, 1 / 30);
    if (!landmarks) {
      this.lostFor += step;
      if (this.lostFor > LOST_AFTER) this.lastFrame = null;
      return;
    }
    if (this.lostFor > RESET_AFTER) this.smoother.reset();
    const smooth = this.smoother.smooth(landmarks, now / 1000);
    const frame = bodyFrame(smooth, {
      width: this.video.videoWidth,
      height: this.video.videoHeight,
      previousFacing: this.lastFrame?.facing,
      torsoRatio: this.torsoRatio,
    });
    if (!frame) {
      this.lostFor += step;
      if (this.lostFor > LOST_AFTER) this.lastFrame = null;
      return;
    }
    if (!frame.hipsEstimated && frame.facing === "front") {
      // Torso length / shoulder width of this person facing the camera = its smallest value
      // (turning only narrows the shoulders). Follow drops fast, drift up slowly.
      const ratio = frame.torsoLength / frame.shoulderWidth;
      this.torsoRatio += (ratio - this.torsoRatio) * (ratio < this.torsoRatio ? 0.3 : 0.01);
    }
    this.lastFrame = frame;
    this.lostFor = 0;
    this.everTracked = true;
  }

  private updateTracking(dt: number) {
    const f = this.lastFrame;
    const backMissing = f?.facing === "back" && !this.garment?.back;
    const target = f && !backMissing ? yawOpacity(f.yaw) : 0;
    const speed = target > this.alpha ? 5 : 4; // ~200 ms in, ~250 ms out
    this.alpha += (target - this.alpha) * Math.min(1, dt * speed * 2);

    let hint: string | null = null;
    if (!f) hint = "Kameradan 1,5–2 metr uzoqlashing — yelkangizdan tizzangizgacha ko'rinsin.";
    else if (backMissing) hint = "Bu kiyimning orqa ko'rinishi yo'q — kameraga yuzingiz bilan turing.";
    else if (Math.abs(f.yaw) > 0.8) hint = "Kameraga to'g'ri qarab turing.";
    else if (f.hipsEstimated) hint = "Biroz orqaroq turing — kiyim to'liq ko'rinadi.";
    const tracking: Tracking = f ? "tracking" : this.everTracked ? "lost" : "searching";
    this.set({ tracking, hint });
  }

  private composeFrame() {
    const f = this.lastFrame;
    const g = this.garment;
    if (!f || !g || this.alpha <= 0.01) return null;
    const front = f.facing === "front" || !g.back;
    const body = front ? g.front : g.back!;
    const anchors = body.anchors as unknown as BodyAnchors;
    bodyMesh(anchors, body.w, body.h, f, BODY_GRID, this.bodyPositions);
    const layers: DrawLayer[] = [];
    // Trousers / skirt first: the body layer (a jacket's hem, a shirt) lies over their waistband.
    if (g.lower) {
      lowerMesh(g.lower.anchors as unknown as LowerAnchors, g.lower.w, g.lower.h, f, BODY_GRID, this.lowerPositions);
      layers.push({ texture: g.lower.texture, positions: this.lowerPositions, uv: BODY_GRID.uv, indices: BODY_GRID.indices });
    }
    layers.push({ texture: body.texture, positions: this.bodyPositions, uv: BODY_GRID.uv, indices: BODY_GRID.indices });
    // Sleeves follow the arm bones; on a back view they are drawn under nothing else.
    const across = f.shoulderWidth / anchorShoulderWidth(anchors, body.w, body.h);
    const bone = (kind: SleeveKind) => {
      const right = kind.startsWith("RIGHT");
      const limb = right ? f.right : f.left;
      const upper = kind.endsWith("UPPER_ARM");
      const from = upper ? limb.shoulder : limb.elbow;
      const to = upper ? limb.elbow : limb.wrist;
      return from && to ? { from, to } : null;
    };
    const drawn = { rightUpper: false, rightFore: false, leftUpper: false, leftFore: false };
    if (front) {
      for (const kind of SLEEVES) {
        const layer = g.sleeves[kind];
        const b = bone(kind);
        if (!layer || !b) continue;
        const positions = limbQuad(layer.anchors as unknown as LimbAnchors, layer.w, layer.h, b.from, b.to, across);
        layers.push({ texture: layer.texture, positions, uv: LIMB_GRID.uv, indices: LIMB_GRID.indices });
        drawn[
          ({ RIGHT_UPPER_ARM: "rightUpper", RIGHT_FOREARM: "rightFore", LEFT_UPPER_ARM: "leftUpper", LEFT_FOREARM: "leftFore" } as const)[kind]
        ] = true;
      }
    }
    this.sampleLight();
    return { layers, alpha: this.alpha, light: this.light, occluders: front ? occluders(f, drawn) : [] };
  }

  /** Average scene brightness every ~15 frames → garment brightness, so it sits in the room's light. */
  private sampleLight() {
    if (this.frames % 15 !== 0) return;
    if (!this.lightCanvas) {
      const c = document.createElement("canvas");
      c.width = c.height = 8;
      this.lightCanvas = c.getContext("2d", { willReadFrequently: true });
    }
    const ctx = this.lightCanvas;
    if (!ctx) return;
    ctx.drawImage(this.video, 0, 0, 8, 8);
    const { data } = ctx.getImageData(0, 0, 8, 8);
    let sum = 0;
    for (let i = 0; i < data.length; i += 4) sum += 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
    const lum = sum / (data.length / 4) / 255;
    const target = Math.min(1.08, Math.max(0.7, 0.62 + lum * 0.85));
    this.light = this.light * 0.7 + target * 0.3;
  }

  /** FPS once a second; slow tracking → economy mode (smaller camera frames, fewer detections). */
  private measure(now: number) {
    this.frames += 1;
    if (!this.fpsWindowStart) this.fpsWindowStart = now;
    if (now - this.fpsWindowStart < 1000) return;
    const fps = Math.round((this.frames * 1000) / (now - this.fpsWindowStart));
    this.frames = 0;
    this.fpsWindowStart = now;
    const slow = this.detectMs > 45;
    this.slowSince = slow ? this.slowSince || now : 0;
    if (slow && !this.status.economy && now - this.slowSince > 2000) {
      this.detectInterval = 1000 / 15;
      const track = this.stream?.getVideoTracks()[0];
      track?.applyConstraints({ width: { ideal: 640 }, height: { ideal: 480 } }).catch(() => undefined);
      this.set({ economy: true });
    }
    this.set({ fps });
  }
}
