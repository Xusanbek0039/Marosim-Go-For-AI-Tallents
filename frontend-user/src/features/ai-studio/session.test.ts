// Run: npm test  (node --test, Node ≥ 22.18 strips the types)
// The fake below mimics @decartai/sdk 0.2.14's RealTimeClient events; no camera, no network.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { type ConnectArgs, type LiveClient, StudioSession, type StudioDeps } from "./session.ts";

class FakeTrack {
  stopped = false;
  stop() {
    this.stopped = true;
  }
}

class FakeStream {
  tracks = [new FakeTrack()];
  getTracks() {
    return this.tracks;
  }
}

class FakeClient implements LiveClient {
  listeners = new Map<string, (d: unknown) => void>();
  images: { image: Blob; options?: { prompt?: string | null; enhance?: boolean } }[] = [];
  disconnected = 0;
  async setImage(image: Blob, options?: { prompt?: string | null; enhance?: boolean }) {
    this.images.push({ image, options });
  }
  disconnect() {
    this.disconnected++;
  }
  on(event: string, listener: (d: unknown) => void) {
    this.listeners.set(event, listener);
  }
  emit(event: string, data: unknown) {
    this.listeners.get(event)?.(data);
  }
}

function setup(over: Partial<StudioDeps> = {}) {
  let clock = 1_000_000;
  const calls = { finish: [] as unknown[][], token: 0, start: 0, connect: [] as ConnectArgs[] };
  const client = new FakeClient();
  const timers: { fn: () => void; ms: number; cleared: boolean }[] = [];
  const stream = new FakeStream();
  const deps: StudioDeps = {
    hasSupport: () => true,
    getCamera: async () => stream as unknown as MediaStream,
    connect: async (args) => {
      calls.connect.push(args);
      await args.apiKeyProvider();
      return client;
    },
    api: {
      start: async () => {
        calls.start++;
        return {
          id: "s1",
          status: "ACTIVE",
          provider_model: "lucy-vton-latest",
          started_at: new Date(clock).toISOString(),
          expires_at: new Date(clock + 180_000).toISOString(),
          seconds_left: 180,
          ended_at: null,
          end_reason: "",
          token_count: 0,
        };
      },
      status: async () => ({ active_session: null }),
      token: async () => {
        calls.token++;
        return { api_key: "ek_test" };
      },
      finish: async (...args) => {
        calls.finish.push(args);
        return {};
      },
    },
    fetchImage: async (url) => new Blob([url]),
    now: () => clock,
    setTimer: (fn, ms) => {
      const t = { fn, ms, cleared: false };
      timers.push(t);
      return t;
    },
    clearTimer: (t) => {
      (t as { cleared: boolean }).cleared = true;
    },
    ...over,
  };
  const studio = new StudioSession(deps);
  const phases: string[] = [];
  studio.subscribe((s) => {
    if (phases.at(-1) !== s.phase) phases.push(s.phase);
  });
  return { studio, client, calls, timers, stream, phases, tick: (ms: number) => (clock += ms) };
}

const DRESS = { id: "g1", referenceUrl: "/media/dress.jpg", prompt: "Substitute the current outfit with a white dress" };
const SUIT = { id: "g2", referenceUrl: "/media/suit.jpg", prompt: "" };

describe("AI studio session", () => {
  it("goes camera → session → connecting → processing → live with the remote stream as the preview", async () => {
    const t = setup();
    await t.studio.openCamera();
    await t.studio.start(DRESS);
    t.tick(1800);
    const remote = { id: "remote" } as unknown as MediaStream;
    t.calls.connect[0].onRemoteStream(remote);
    t.calls.connect[0].onConnectionChange("connected");
    t.calls.connect[0].onConnectionChange("generating");
    assert.deepEqual(t.phases, ["idle", "requesting-camera", "camera-ready", "starting", "connecting", "processing", "live"]);
    assert.equal(t.studio.snapshot.remoteStream, remote);
    assert.equal(t.studio.snapshot.metrics.connect_ms, 1800);
    assert.equal(t.calls.token, 1, "the client token comes from our server, per dial");
    assert.equal(t.calls.connect[0].prompt, DRESS.prompt);
    assert.equal(await t.calls.connect[0].image.text(), DRESS.referenceUrl);
  });

  it("switches garments on the live connection, latest choice wins", async () => {
    const t = setup();
    await t.studio.openCamera();
    await t.studio.start(DRESS);
    t.calls.connect[0].onConnectionChange("generating");
    const a = t.studio.switchGarment(SUIT);
    const b = t.studio.switchGarment(DRESS);
    await Promise.all([a, b]);
    assert.equal(t.client.images.length, 1, "the stale switch is dropped");
    assert.equal(t.client.images[0].options?.prompt, DRESS.prompt);
    assert.equal(t.client.images[0].options?.enhance, false);
    assert.equal(t.studio.snapshot.phase, "live");
    assert.equal(t.studio.snapshot.metrics.garments_tried, 2);
    assert.equal(t.calls.connect.length, 1, "no reconnect for a garment switch");
  });

  it("an empty prompt is sent as reference-only", async () => {
    const t = setup();
    await t.studio.openCamera();
    await t.studio.start(DRESS);
    t.calls.connect[0].onConnectionChange("generating");
    await t.studio.switchGarment(SUIT);
    assert.equal(t.client.images[0].options?.prompt, null);
  });

  it("measures fps, glass-to-glass latency and interruptions, and reports them on finish", async () => {
    const t = setup();
    await t.studio.openCamera();
    await t.studio.start(DRESS);
    t.calls.connect[0].onConnectionChange("generating");
    t.client.emit("stats", { video: { framesPerSecond: 20 }, glassToGlass: { medianMs: 240.4, ttffMs: 2100 } });
    t.client.emit("stats", { video: { framesPerSecond: 24 }, glassToGlass: null });
    t.calls.connect[0].onConnectionChange("reconnecting");
    t.calls.connect[0].onConnectionChange("generating");
    t.client.emit("generationTick", { seconds: 12.34 });
    await t.studio.end("USER");
    const [id, reason, metrics] = t.calls.finish[0];
    assert.equal(id, "s1");
    assert.equal(reason, "USER");
    assert.deepEqual(metrics, {
      interruptions: 1,
      connect_ms: 0,
      fps: 22,
      glass_to_glass_ms: 240,
      first_frame_ms: 2100,
      generation_seconds: 12.3,
    });
    assert.equal(t.client.disconnected, 1);
    assert.equal(t.studio.snapshot.phase, "camera-ready", "the camera stays open for a new session");
    assert.equal(t.stream.tracks[0].stopped, false);
  });

  it("server-ended sessions map to meaningful states and are finished once", async () => {
    const t = setup();
    await t.studio.openCamera();
    await t.studio.start(DRESS);
    t.client.emit("sessionEnded", { reason: "moderation_violation" });
    t.client.emit("sessionEnded", { reason: "moderation_violation" });
    await new Promise((r) => setImmediate(r));
    assert.equal(t.studio.snapshot.phase, "provider-error");
    assert.equal(t.calls.finish.length, 1);
    assert.equal(t.calls.finish[0][1], "MODERATION");
  });

  it("a late 'disconnected' from our own disconnect does not show a network error", async () => {
    const t = setup();
    await t.studio.openCamera();
    await t.studio.start(DRESS);
    const old = t.calls.connect[0];
    await t.studio.end("USER");
    old.onConnectionChange("disconnected");
    assert.equal(t.studio.snapshot.phase, "camera-ready");
    assert.equal(t.calls.finish.length, 1);
  });

  it("a real drop after the SDK's retries is a network error", async () => {
    const t = setup();
    await t.studio.openCamera();
    await t.studio.start(DRESS);
    t.calls.connect[0].onConnectionChange("generating");
    t.calls.connect[0].onConnectionChange("disconnected");
    await new Promise((r) => setImmediate(r));
    assert.equal(t.studio.snapshot.phase, "network-error");
    assert.equal(t.calls.finish[0][1], "NETWORK_ERROR");
  });

  it("the session's time budget ends it as expired", async () => {
    const t = setup();
    await t.studio.openCamera();
    await t.studio.start(DRESS);
    const timer = t.timers[0];
    assert.equal(timer.ms, 180_000);
    timer.fn();
    await new Promise((r) => setImmediate(r));
    assert.equal(t.studio.snapshot.phase, "expired");
    assert.equal(t.calls.finish[0][1], "EXPIRED");
  });

  it("close() releases the camera and the connection", async () => {
    const t = setup();
    await t.studio.openCamera();
    await t.studio.start(DRESS);
    await t.studio.close();
    assert.equal(t.stream.tracks[0].stopped, true);
    assert.equal(t.client.disconnected, 1);
    assert.equal(t.studio.snapshot.phase, "finished");
    assert.equal(t.studio.snapshot.localStream, undefined);
    await t.studio.close();
    assert.equal(t.calls.finish.length, 1, "idempotent");
  });

  it("camera denial, missing camera and unsupported browsers get their own states", async () => {
    const denied = setup({ getCamera: async () => Promise.reject(Object.assign(new Error(), { name: "NotAllowedError" })) });
    await denied.studio.openCamera();
    assert.equal(denied.studio.snapshot.phase, "camera-denied");
    const missing = setup({ getCamera: async () => Promise.reject(Object.assign(new Error(), { name: "NotFoundError" })) });
    await missing.studio.openCamera();
    assert.equal(missing.studio.snapshot.phase, "camera-unavailable");
    const old = setup({ hasSupport: () => false });
    await old.studio.openCamera();
    assert.equal(old.studio.snapshot.phase, "unsupported");
  });

  it("daily limits and a missing server key show the limit state, not a fake success", async () => {
    const t = setup();
    t.studio["deps"].api.start = async () =>
      Promise.reject({ status: 503, code: "ai_tryon_not_configured", message: "AI kiyib ko'rish hozircha yoqilmagan." });
    await t.studio.openCamera();
    await t.studio.start(DRESS);
    assert.equal(t.studio.snapshot.phase, "limit");
    assert.equal(t.calls.connect.length, 0, "never dials Decart without a server session");
  });

  it("a session left open by a closed tab is finished before starting a new one", async () => {
    const t = setup();
    let first = true;
    const start = t.studio["deps"].api.start;
    t.studio["deps"].api.start = async () => {
      if (first) {
        first = false;
        return Promise.reject({ status: 409, code: "ai_session_already_active" });
      }
      return start();
    };
    t.studio["deps"].api.status = async () => ({ active_session: "stale" });
    await t.studio.openCamera();
    await t.studio.start(DRESS);
    assert.deepEqual(t.calls.finish[0].slice(0, 2), ["stale", "OTHER"]);
    assert.equal(t.studio.snapshot.phase, "connecting");
  });

  it("an expired client token surfaces as a provider error", async () => {
    const t = setup();
    await t.studio.openCamera();
    await t.studio.start(DRESS);
    t.client.emit("error", { code: "TOKEN_EXPIRED" });
    await new Promise((r) => setImmediate(r));
    assert.equal(t.studio.snapshot.phase, "provider-error");
    assert.equal(t.calls.finish[0][1], "PROVIDER_ERROR");
  });

  it("transient WebRTC errors leave the live session to the SDK's own reconnect", async () => {
    const t = setup();
    await t.studio.openCamera();
    await t.studio.start(DRESS);
    t.calls.connect[0].onConnectionChange("generating");
    for (const code of ["WEBRTC_ICE_ERROR", "WEBRTC_SIGNALING_ERROR", "WEBRTC_SERVER_ERROR"]) {
      t.client.emit("error", { code });
    }
    await new Promise((r) => setImmediate(r));
    assert.equal(t.studio.snapshot.phase, "live");
    assert.equal(t.client.disconnected, 0);
    assert.equal(t.calls.finish.length, 0);
  });
});
