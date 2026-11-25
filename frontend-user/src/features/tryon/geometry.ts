/**
 * Pure math of the live try-on: landmark smoothing, the body frame read from MediaPipe pose
 * landmarks, and the mapping of a garment layer's mesh onto that frame.
 *
 * No DOM, no imports — `node --test` runs geometry.test.ts against this file directly.
 *
 * Coordinates: everything is in *camera image pixels* (unmirrored, x right, y down). The selfie
 * mirror is applied to the whole canvas by CSS, so the garment and the person mirror together.
 * Sides are the wearer's: facing the camera, the wearer's right shoulder is on the image's left.
 */

export interface Vec {
  x: number;
  y: number;
}

export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

/** MediaPipe Pose (BlazePose, 33 points) indices used here. */
export const LM = {
  L_SHOULDER: 11,
  R_SHOULDER: 12,
  L_ELBOW: 13,
  R_ELBOW: 14,
  L_WRIST: 15,
  R_WRIST: 16,
  L_PINKY: 17,
  R_PINKY: 18,
  L_INDEX: 19,
  R_INDEX: 20,
  L_HIP: 23,
  R_HIP: 24,
  L_KNEE: 25,
  R_KNEE: 26,
  L_ANKLE: 27,
  R_ANKLE: 28,
} as const;

/** The landmarks the try-on reads (and smooths). */
export const TRACKED = Object.values(LM);

// ------------------------------------------------------------------ vectors
export const add = (a: Vec, b: Vec): Vec => ({ x: a.x + b.x, y: a.y + b.y });
export const sub = (a: Vec, b: Vec): Vec => ({ x: a.x - b.x, y: a.y - b.y });
export const scale = (a: Vec, k: number): Vec => ({ x: a.x * k, y: a.y * k });
export const mid = (a: Vec, b: Vec): Vec => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
export const lerp = (a: Vec, b: Vec, t: number): Vec => ({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t });
export const len = (a: Vec) => Math.hypot(a.x, a.y);
export const dist = (a: Vec, b: Vec) => len(sub(a, b));
export const norm = (a: Vec): Vec => {
  const l = len(a);
  return l > 1e-9 ? { x: a.x / l, y: a.y / l } : { x: 0, y: 1 };
};
export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
export const smoothstep = (e0: number, e1: number, x: number) => {
  const t = clamp((x - e0) / (e1 - e0), 0, 1);
  return t * t * (3 - 2 * t);
};

// ---------------------------------------------------------------- smoothing
/**
 * One Euro filter (Casiez et al. 2012): heavy smoothing when a point is still (no jitter),
 * light smoothing when it moves fast (no lag).
 */
export class OneEuroFilter {
  private x: number | null = null;
  private dx = 0;
  private lastT = 0;

  private minCutoff: number;
  private beta: number;
  private dCutoff: number;

  constructor(minCutoff = 1.4, beta = 6, dCutoff = 1) {
    this.minCutoff = minCutoff;
    this.beta = beta;
    this.dCutoff = dCutoff;
  }

  private static alpha(cutoff: number, dt: number) {
    const tau = 1 / (2 * Math.PI * cutoff);
    return 1 / (1 + tau / dt);
  }

  reset() {
    this.x = null;
    this.dx = 0;
  }

  /** `t` in seconds. */
  filter(value: number, t: number): number {
    if (this.x === null) {
      this.x = value;
      this.lastT = t;
      return value;
    }
    const dt = Math.max(t - this.lastT, 1e-3);
    this.lastT = t;
    const rawDx = (value - this.x) / dt;
    this.dx += OneEuroFilter.alpha(this.dCutoff, dt) * (rawDx - this.dx);
    const cutoff = this.minCutoff + this.beta * Math.abs(this.dx);
    this.x += OneEuroFilter.alpha(cutoff, dt) * (value - this.x);
    return this.x;
  }
}

/** Smooths x/y/z of the tracked landmarks (normalized coordinates) independently. */
export class LandmarkSmoother {
  private filters = new Map<number, [OneEuroFilter, OneEuroFilter, OneEuroFilter]>();

  reset() {
    this.filters.forEach((f) => f.forEach((one) => one.reset()));
  }

  smooth(landmarks: Landmark[], tSeconds: number): Landmark[] {
    const out = landmarks.slice();
    for (const i of TRACKED) {
      const p = landmarks[i];
      if (!p) continue;
      let f = this.filters.get(i);
      if (!f) {
        f = [new OneEuroFilter(), new OneEuroFilter(), new OneEuroFilter(0.8, 2)];
        this.filters.set(i, f);
      }
      out[i] = { x: f[0].filter(p.x, tSeconds), y: f[1].filter(p.y, tSeconds), z: f[2].filter(p.z, tSeconds), visibility: p.visibility };
    }
    return out;
  }
}

// --------------------------------------------------------------- body frame
export interface Limb {
  shoulder: Vec;
  elbow: Vec | null;
  wrist: Vec | null;
  /** End of the hand (past index/pinky), or null when the hand is not seen. */
  hand: Vec | null;
  /** The arm is clearly behind the body (z) — nothing to hide in front of the garment. */
  behind: boolean;
}

export interface BodyFrame {
  rs: Vec;
  ls: Vec;
  rh: Vec;
  lh: Vec;
  /** Hips were not seen (person close to the camera) and were estimated from the shoulders. */
  hipsEstimated: boolean;
  rKnee: Vec | null;
  lKnee: Vec | null;
  rAnkle: Vec | null;
  lAnkle: Vec | null;
  right: Limb;
  left: Limb;
  facing: "front" | "back";
  /** Rotation around the vertical axis from shoulder depth, radians (0 = facing the camera). */
  yaw: number;
  shoulderWidth: number;
  torsoLength: number;
}

export interface FrameOptions {
  width: number;
  height: number;
  /** Previous facing, for hysteresis. */
  previousFacing?: "front" | "back";
  /** Learned torso length / shoulder width of this person (used when the hips are not seen). */
  torsoRatio?: number;
}

const SHOULDER_MIN_VIS = 0.5;
const JOINT_MIN_VIS = 0.35;
const LEG_MIN_VIS = 0.35;

function visible(p: Landmark | undefined, min: number) {
  return Boolean(p && (p.visibility ?? 1) >= min);
}

function inside(p: Landmark) {
  return p.x > -0.05 && p.x < 1.05 && p.y > -0.05 && p.y < 1.02;
}

/** Body frame in image pixels, or null when the shoulders are not tracked reliably. */
export function bodyFrame(lm: Landmark[], opts: FrameOptions): BodyFrame | null {
  const { width: W, height: H } = opts;
  const px = (p: Landmark): Vec => ({ x: p.x * W, y: p.y * H });
  const lsL = lm[LM.L_SHOULDER];
  const rsL = lm[LM.R_SHOULDER];
  if (!visible(lsL, SHOULDER_MIN_VIS) || !visible(rsL, SHOULDER_MIN_VIS)) return null;
  const rs = px(rsL);
  const ls = px(lsL);
  const shoulderWidth = dist(rs, ls);
  if (shoulderWidth < Math.min(W, H) * 0.04) return null; // too far / degenerate

  // Facing: on a front view the wearer's right shoulder is on the image's left.
  const signed = (ls.x - rs.x) / shoulderWidth;
  let facing = opts.previousFacing ?? "front";
  if (signed > 0.25) facing = "front";
  else if (signed < -0.25) facing = "back";

  const hipsSeen = [LM.L_HIP, LM.R_HIP].every((i) => visible(lm[i], JOINT_MIN_VIS) && inside(lm[i]));
  let rh: Vec;
  let lh: Vec;
  if (hipsSeen) {
    rh = px(lm[LM.R_HIP]);
    lh = px(lm[LM.L_HIP]);
  } else {
    // Hips below the frame: drop them perpendicular to the shoulder line.
    const axis = norm(sub(ls, rs));
    const down = facing === "front" ? { x: -axis.y, y: axis.x } : { x: axis.y, y: -axis.x };
    const centre = add(mid(rs, ls), scale(down, shoulderWidth * (opts.torsoRatio ?? 1.45)));
    const half = scale(sub(ls, rs), 0.5 * 0.78);
    rh = sub(centre, half);
    lh = add(centre, half);
  }

  const point = (i: number, min = JOINT_MIN_VIS) => (visible(lm[i], min) ? px(lm[i]) : null);
  const limb = (s: number, e: number, w: number, idx: number, pinky: number): Limb => {
    const shoulder = px(lm[s]);
    const elbow = point(e);
    const wrist = elbow ? point(w) : null;
    let hand: Vec | null = null;
    if (wrist && visible(lm[idx], 0.3) && visible(lm[pinky], 0.3)) {
      const tip = mid(px(lm[idx]), px(lm[pinky]));
      hand = add(wrist, scale(sub(tip, wrist), 1.35));
    }
    const behind = Boolean(lm[w] && lm[s] && lm[w].z - lm[s].z > 0.25);
    return { shoulder, elbow, wrist, hand, behind };
  };

  // Yaw from 2D foreshortening: turning narrows the shoulders against the torso length.
  // (MediaPipe's z is too noisy for this — outstretched arms alone swing it a lot; it only
  // gives the direction.) Without hips there is no torso to compare with: assume frontal.
  const torsoLength = dist(mid(rs, ls), mid(rh, lh));
  const frontal = (shoulderWidth / torsoLength) * (opts.torsoRatio ?? 1.45);
  const turn = hipsSeen ? Math.acos(clamp(frontal, 0, 1)) : 0;
  const yaw = lsL.z - rsL.z < 0 ? -turn : turn;

  return {
    rs,
    ls,
    rh,
    lh,
    hipsEstimated: !hipsSeen,
    // Webcams in a dim room give legs low visibility scores; 0.35 still tracks them well.
    rKnee: point(LM.R_KNEE, LEG_MIN_VIS),
    lKnee: point(LM.L_KNEE, LEG_MIN_VIS),
    rAnkle: point(LM.R_ANKLE, LEG_MIN_VIS),
    lAnkle: point(LM.L_ANKLE, LEG_MIN_VIS),
    right: limb(LM.R_SHOULDER, LM.R_ELBOW, LM.R_WRIST, LM.R_INDEX, LM.R_PINKY),
    left: limb(LM.L_SHOULDER, LM.L_ELBOW, LM.L_WRIST, LM.L_INDEX, LM.L_PINKY),
    facing,
    yaw,
    shoulderWidth,
    torsoLength,
  };
}

// ------------------------------------------------------------ garment mesh
/** Anchors of a body layer, normalized to its image (see backend `assets.ANCHOR_KEYS`). */
export interface BodyAnchors {
  right_shoulder: [number, number];
  left_shoulder: [number, number];
  right_hip: [number, number];
  left_hip: [number, number];
  /** "split": trousers — each leg follows its own thigh. Default: one skirt / coat tail. */
  legs?: "split" | "joined";
}

export interface LimbAnchors {
  start: [number, number];
  end: [number, number];
}

export interface Grid {
  cols: number;
  rows: number;
  /** Texture coordinates per vertex (u, v in 0..1). */
  uv: Float32Array;
  /** Triangle indices. */
  indices: Uint16Array;
}

export function makeGrid(cols: number, rows: number): Grid {
  const uv = new Float32Array((cols + 1) * (rows + 1) * 2);
  let k = 0;
  for (let r = 0; r <= rows; r++) {
    for (let c = 0; c <= cols; c++) {
      uv[k++] = c / cols;
      uv[k++] = r / rows;
    }
  }
  const indices = new Uint16Array(cols * rows * 6);
  k = 0;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const a = r * (cols + 1) + c;
      const b = a + 1;
      const d = a + cols + 1;
      const e = d + 1;
      indices.set([a, d, b, b, d, e], k);
      k += 6;
    }
  }
  return { cols, rows, uv, indices };
}

/**
 * Where a point of the body layer image lands on the person.
 *
 * Between the shoulder and hip rows of the image the layer is mapped bilinearly onto the
 * person's shoulder–hip quad (position, scale, rotation, lean and uneven shoulders all follow).
 * Below the hips the layer continues along the legs: the skirt / coat tail keeps the hip width
 * and follows the thighs' direction (one direction for a skirt, one per leg for trousers).
 */
export function mapBodyPoint(
  px: number,
  py: number,
  a: { rs: Vec; ls: Vec; rh: Vec; lh: Vec; legs: "split" | "joined" },
  f: BodyFrame,
  legs: LegChains,
): Vec {
  const sMidA = mid(a.rs, a.ls);
  const hMidA = mid(a.rh, a.lh);
  const sW = a.ls.x - a.rs.x; // signed: negative on a back view
  const hW = a.lh.x - a.rh.x;
  const t = (py - sMidA.y) / (hMidA.y - sMidA.y);
  const us = (px - sMidA.x) / sW;
  const uh = (px - hMidA.x) / hW;

  const S = mid(f.rs, f.ls);
  const Hm = mid(f.rh, f.lh);
  const top = add(S, scale(sub(f.ls, f.rs), us));
  const bottom = add(Hm, scale(sub(f.lh, f.rh), uh));
  if (t <= 1) return lerp(top, bottom, t);

  const perImagePx = dist(S, Hm) / (hMidA.y - sMidA.y);
  const below = (py - hMidA.y) * perImagePx;
  const joined = alongChain(legs.joined, bottom, below, legs.torso);
  if (a.legs !== "split") return joined;
  // Trousers: each half follows its own leg. Right under the hips (crotch, a jacket's hem) the
  // garment is still one piece; the legs take over from ~half a torso below the hips. The switch
  // between the halves is kept to the narrow gap between the legs so no fabric is stretched across.
  const right = alongChain(legs.right, bottom, below, legs.torso);
  const left = alongChain(legs.left, bottom, below, legs.torso);
  const split = lerp(right, left, smoothstep(-0.03, 0.03, uh));
  return lerp(joined, split, smoothstep(0.5, 0.8, t - 1));
}

/** A leg as a polyline from the hip down (hip → knee → ankle), in camera pixels. */
export interface LegChains {
  torso: Vec;
  joined: Vec[];
  right: Vec[];
  left: Vec[];
}

/**
 * Moves the garment row that starts at `start` by `distance` along `chain`, turning its sideways
 * offset with each segment so the fabric stays across the leg (trouser legs bend at the knee).
 */
function alongChain(chain: Vec[], start: Vec, distance: number, torso: Vec): Vec {
  const offset = sub(start, chain[0]);
  let left = distance;
  for (let i = 0; i < chain.length - 1; i++) {
    const seg = sub(chain[i + 1], chain[i]);
    const segLen = len(seg);
    const last = i === chain.length - 2;
    if (left <= segLen || last) {
      const dir = norm(seg);
      const p = add(chain[i], scale(dir, left));
      // rotate the offset by the angle between this segment and the torso direction
      const cos = dir.x * torso.x + dir.y * torso.y;
      const sin = torso.x * dir.y - torso.y * dir.x;
      return add(p, { x: offset.x * cos - offset.y * sin, y: offset.x * sin + offset.y * cos });
    }
    left -= segLen;
  }
  return add(chain[0], offset);
}

/**
 * Where the garment goes below the hips. Trousers: each leg's hip → knee → ankle. Skirts and coat
 * tails hang: they lean only partly towards the knees, the rest is gravity (image down).
 */
export function legChains(f: BodyFrame): LegChains {
  const torso = norm(sub(mid(f.rh, f.lh), mid(f.rs, f.ls)));
  const reach = f.torsoLength * 4; // far enough past any hem
  const chain = (hip: Vec, knee: Vec | null, ankle: Vec | null): Vec[] => {
    if (!knee || f.hipsEstimated) return [hip, add(hip, scale(torso, reach))];
    const thigh = norm(sub(knee, hip));
    // A thigh can go sideways (lunge, wide stance); only one pointing back up (sitting, kicking)
    // would fold the garment onto itself — then fall back to the torso.
    if (thigh.x * torso.x + thigh.y * torso.y < -0.2) return [hip, add(hip, scale(torso, reach))];
    if (!ankle) return [hip, knee, add(knee, scale(thigh, reach))];
    const shin = norm(sub(ankle, knee));
    return [hip, knee, ankle, add(ankle, scale(shin, reach))];
  };
  const hm = mid(f.rh, f.lh);
  const knees = f.rKnee && f.lKnee && !f.hipsEstimated ? norm(sub(mid(f.rKnee, f.lKnee), hm)) : torso;
  const hang = norm(add(add(scale(torso, 0.45), scale(knees, 0.25)), scale({ x: 0, y: 1 }, 0.3)));
  return {
    torso,
    joined: [hm, add(hm, scale(hang, reach))],
    right: chain(f.rh, f.rKnee, f.rAnkle),
    left: chain(f.lh, f.lKnee, f.lAnkle),
  };
}

/** Vertex positions (image pixels) of a body layer's grid on the person. */
export function bodyMesh(
  anchors: BodyAnchors,
  imgW: number,
  imgH: number,
  f: BodyFrame,
  grid: Grid,
  out?: Float32Array,
): Float32Array {
  const toPx = (p: [number, number]): Vec => ({ x: p[0] * imgW, y: p[1] * imgH });
  const a = {
    rs: toPx(anchors.right_shoulder),
    ls: toPx(anchors.left_shoulder),
    rh: toPx(anchors.right_hip),
    lh: toPx(anchors.left_hip),
    legs: anchors.legs ?? "joined",
  };
  const dirs = legChains(f);
  const positions = out ?? new Float32Array(grid.uv.length);
  for (let i = 0; i < grid.uv.length; i += 2) {
    const p = mapBodyPoint(grid.uv[i] * imgW, grid.uv[i + 1] * imgH, a, f, dirs);
    positions[i] = p.x;
    positions[i + 1] = p.y;
  }
  return positions;
}

/** Anchors of a lower-body layer (trousers, skirt), normalized to its image. */
export interface LowerAnchors {
  right_hip: [number, number];
  left_hip: [number, number];
  right_knee: [number, number];
  left_knee: [number, number];
  legs?: "split" | "joined";
}

/**
 * Vertex positions of a lower-body layer. Sideways it scales with the hips; downwards each half
 * is measured against its own thigh (image hip → knee ↔ person hip → knee) and then follows that
 * leg's hip → knee → ankle chain, so trouser legs bend with the knees. A skirt ("joined") hangs.
 */
export function lowerMesh(
  anchors: LowerAnchors,
  imgW: number,
  imgH: number,
  f: BodyFrame,
  grid: Grid,
  out?: Float32Array,
): Float32Array {
  const toPx = (p: [number, number]): Vec => ({ x: p[0] * imgW, y: p[1] * imgH });
  const rhA = toPx(anchors.right_hip);
  const lhA = toPx(anchors.left_hip);
  const rkA = toPx(anchors.right_knee);
  const lkA = toPx(anchors.left_knee);
  const hMidA = mid(rhA, lhA);
  const hipW = lhA.x - rhA.x;
  const axisUser = sub(f.lh, f.rh);
  const across = len(axisUser) / Math.abs(hipW);
  const axis = norm(axisUser);
  const chains = legChains(f);
  const hm = mid(f.rh, f.lh);
  const thighScale = (hipA: Vec, kneeA: Vec, hip: Vec, knee: Vec | null) =>
    knee && !f.hipsEstimated ? dist(hip, knee) / Math.max(1, kneeA.y - hipA.y) : across;
  const right = { hipA: rhA, hip: f.rh, chain: chains.right, k: thighScale(rhA, rkA, f.rh, f.rKnee) };
  const left = { hipA: lhA, hip: f.lh, chain: chains.left, k: thighScale(lhA, lkA, f.lh, f.lKnee) };
  const joinedK = (right.k + left.k) / 2;

  const place = (px: number, py: number, hipA: Vec, hip: Vec, chain: Vec[], k: number) => {
    const start = add(hip, scale(axis, (px - hipA.x) * across));
    const d = (py - hipA.y) * k;
    return d < 0 ? add(start, scale(chains.torso, d)) : alongChain(chain, start, d, chains.torso);
  };

  const positions = out ?? new Float32Array(grid.uv.length);
  for (let i = 0; i < grid.uv.length; i += 2) {
    const px = grid.uv[i] * imgW;
    const py = grid.uv[i + 1] * imgH;
    let p: Vec;
    if (anchors.legs === "joined") {
      p = place(px, py, hMidA, hm, chains.joined, joinedK);
    } else {
      const r = place(px, py, right.hipA, right.hip, right.chain, right.k);
      const l = place(px, py, left.hipA, left.hip, left.chain, left.k);
      p = lerp(r, l, smoothstep(-0.03, 0.03, (px - hMidA.x) / hipW));
    }
    positions[i] = p.x;
    positions[i + 1] = p.y;
  }
  return positions;
}

/** Body layer anchors' shoulder width in image pixels — the scale sleeve layers share. */
export function anchorShoulderWidth(anchors: BodyAnchors, imgW: number, imgH: number) {
  const [rx, ry] = anchors.right_shoulder;
  const [lx, ly] = anchors.left_shoulder;
  return Math.hypot((lx - rx) * imgW, (ly - ry) * imgH);
}

/**
 * The four corners (image pixels; order: top-left, top-right, bottom-left, bottom-right of the
 * sleeve image) of a sleeve layer laid along one arm bone from `from` to `to`.
 * Along the bone it stretches to the bone's length; across it keeps the body layer's scale.
 */
export function limbQuad(anchors: LimbAnchors, imgW: number, imgH: number, from: Vec, to: Vec, acrossScale: number): Float32Array {
  const s: Vec = { x: anchors.start[0] * imgW, y: anchors.start[1] * imgH };
  const e: Vec = { x: anchors.end[0] * imgW, y: anchors.end[1] * imgH };
  const imgAxis = sub(e, s);
  const imgLen = len(imgAxis);
  const imgDir = norm(imgAxis);
  const imgPerp = { x: -imgDir.y, y: imgDir.x };
  const bone = sub(to, from);
  const along = len(bone) / imgLen;
  const dir = norm(bone);
  const perp = { x: -dir.y, y: dir.x };
  const corners = [
    [0, 0],
    [imgW, 0],
    [0, imgH],
    [imgW, imgH],
  ];
  const out = new Float32Array(8);
  corners.forEach(([cx, cy], i) => {
    const d = { x: cx - s.x, y: cy - s.y };
    const u = d.x * imgDir.x + d.y * imgDir.y; // along the sleeve, image px
    const v = d.x * imgPerp.x + d.y * imgPerp.y; // across
    const p = add(add(from, scale(dir, u * along)), scale(perp, v * acrossScale));
    out[i * 2] = p.x;
    out[i * 2 + 1] = p.y;
  });
  return out;
}

// --------------------------------------------------------------- occlusion
export interface Capsule {
  a: Vec;
  b: Vec;
  r: number;
}

/**
 * Parts of the person that must stay in front of the garment: hands always, and the bare
 * parts of the arms (no sleeve layer for that bone). Arms clearly behind the body are skipped.
 */
export function occluders(f: BodyFrame, sleeves: { rightUpper: boolean; rightFore: boolean; leftUpper: boolean; leftFore: boolean }): Capsule[] {
  const out: Capsule[] = [];
  const w = f.shoulderWidth;
  const arm = (l: Limb, upperCovered: boolean, foreCovered: boolean) => {
    if (l.behind) return;
    if (l.elbow && !upperCovered) out.push({ a: lerp(l.shoulder, l.elbow, 0.3), b: l.elbow, r: w * 0.13 });
    if (l.elbow && l.wrist && !foreCovered) out.push({ a: l.elbow, b: l.wrist, r: w * 0.11 });
    if (l.wrist && l.hand) out.push({ a: l.wrist, b: l.hand, r: w * 0.15 });
  };
  arm(f.right, sleeves.rightUpper, sleeves.rightFore);
  arm(f.left, sleeves.leftUpper, sleeves.leftFore);
  return out;
}

/** 0..1 opacity of a flat garment for the body's yaw: fully shown up to ~55°, gone by ~80°. */
export function yawOpacity(yaw: number) {
  const deg = (Math.abs(yaw) * 180) / Math.PI;
  return 1 - smoothstep(55, 80, deg);
}
