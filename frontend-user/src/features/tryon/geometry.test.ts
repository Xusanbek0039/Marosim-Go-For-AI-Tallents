// Run: npm test  (node --test, Node ≥ 22.18 strips the types)
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  bodyFrame,
  bodyMesh,
  type BodyAnchors,
  type Landmark,
  LM,
  limbQuad,
  makeGrid,
  occluders,
  OneEuroFilter,
  yawOpacity,
} from "./geometry.ts";

const W = 1000;
const H = 1000;

/** A person facing the camera; pixel coordinates in, normalized landmarks out. */
function person(
  opts: { dx?: number; k?: number; hipsVisible?: boolean; back?: boolean; knees?: [number, number][]; ankles?: [number, number][]; shoulderZ?: number; narrow?: number } = {},
): Landmark[] {
  const { dx = 0, k = 1, hipsVisible = true, back = false } = opts;
  const lm: Landmark[] = Array.from({ length: 33 }, () => ({ x: 0, y: 0, z: 0, visibility: 0 }));
  const put = (i: number, x: number, y: number, vis = 1, z = 0) => {
    lm[i] = { x: (500 + (x - 500) * k + dx) / W, y: (300 + (y - 300) * k) / H, z, visibility: vis };
  };
  const flip = (x: number) => (back ? 1000 - x : x);
  const n = opts.narrow ?? 0; // turning: shoulders come closer
  put(LM.R_SHOULDER, flip(400 + n), 300, 1, -(opts.shoulderZ ?? 0));
  put(LM.L_SHOULDER, flip(600 - n), 300, 1, opts.shoulderZ ?? 0);
  put(LM.R_HIP, flip(425), 600, hipsVisible ? 1 : 0.1);
  put(LM.L_HIP, flip(575), 600, hipsVisible ? 1 : 0.1);
  put(LM.R_ELBOW, flip(370), 450);
  put(LM.L_ELBOW, flip(630), 450);
  put(LM.R_WRIST, flip(360), 580);
  put(LM.L_WRIST, flip(640), 580);
  put(LM.R_INDEX, flip(355), 620);
  put(LM.R_PINKY, flip(365), 620);
  put(LM.L_INDEX, flip(645), 620);
  put(LM.L_PINKY, flip(635), 620);
  const [rk, lk] = opts.knees ?? [
    [425, 800],
    [575, 800],
  ];
  put(LM.R_KNEE, flip(rk[0]), rk[1]);
  put(LM.L_KNEE, flip(lk[0]), lk[1]);
  if (opts.ankles) {
    put(LM.R_ANKLE, flip(opts.ankles[0][0]), opts.ankles[0][1]);
    put(LM.L_ANKLE, flip(opts.ankles[1][0]), opts.ankles[1][1]);
  }
  return lm;
}

const anchors: BodyAnchors = {
  right_shoulder: [0.3, 0.1],
  left_shoulder: [0.7, 0.1],
  right_hip: [0.35, 0.4],
  left_hip: [0.65, 0.4],
};
const IMG_W = 500;
const IMG_H = 1000;

/** Where an image point (normalized) lands: a 1x1 grid has vertices exactly at the corners. */
function mapped(f: NonNullable<ReturnType<typeof bodyFrame>>, a: BodyAnchors = anchors) {
  const grid = makeGrid(20, 30); // vertices at multiples of 1/20 x 1/30
  const pos = bodyMesh(a, IMG_W, IMG_H, f, grid);
  return (u: number, v: number) => {
    const c = Math.round(u * 20);
    const r = Math.round(v * 30);
    const i = (r * 21 + c) * 2;
    return { x: pos[i], y: pos[i + 1] };
  };
}

const close = (a: { x: number; y: number }, b: { x: number; y: number }, eps = 0.5) =>
  assert.ok(Math.abs(a.x - b.x) < eps && Math.abs(a.y - b.y) < eps, `${JSON.stringify(a)} ≉ ${JSON.stringify(b)}`);

describe("OneEuroFilter", () => {
  it("keeps a still point still and damps jitter", () => {
    const f = new OneEuroFilter();
    let maxDev = 0;
    for (let i = 0; i < 120; i++) {
      const noisy = 0.5 + (i % 2 ? 0.01 : -0.01);
      const out = f.filter(noisy, i / 30);
      if (i > 10) maxDev = Math.max(maxDev, Math.abs(out - 0.5));
    }
    assert.ok(maxDev < 0.005, `jitter not damped: ${maxDev}`);
  });

  it("follows a real move", () => {
    const f = new OneEuroFilter();
    f.filter(0, 0);
    let out = 0;
    for (let i = 1; i <= 15; i++) out = f.filter(1, i / 30);
    assert.ok(out > 0.95, `lagging: ${out}`);
  });
});

describe("bodyFrame", () => {
  it("is null without both shoulders", () => {
    const lm = person();
    lm[LM.L_SHOULDER] = { ...lm[LM.L_SHOULDER], visibility: 0.1 };
    assert.equal(bodyFrame(lm, { width: W, height: H }), null);
  });

  it("reads a front-facing body", () => {
    const f = bodyFrame(person(), { width: W, height: H })!;
    assert.equal(f.facing, "front");
    assert.equal(f.hipsEstimated, false);
    close(f.rs, { x: 400, y: 300 });
    close(f.lh, { x: 575, y: 600 });
    assert.equal(Math.round(f.shoulderWidth), 200);
  });

  it("detects a back view", () => {
    assert.equal(bodyFrame(person({ back: true }), { width: W, height: H })!.facing, "back");
  });

  it("estimates the hips below the shoulders when they are out of view", () => {
    const f = bodyFrame(person({ hipsVisible: false }), { width: W, height: H, torsoRatio: 1.5 })!;
    assert.equal(f.hipsEstimated, true);
    assert.ok(f.rh.y > f.rs.y + 250 && Math.abs(f.rh.y - f.lh.y) < 1);
  });
});

describe("garment mesh follows the body", () => {
  it("puts the garment's anchors on the person's joints", () => {
    const at = mapped(bodyFrame(person(), { width: W, height: H })!);
    close(at(0.3, 0.1), { x: 400, y: 300 }); // right shoulder
    close(at(0.7, 0.1), { x: 600, y: 300 }); // left shoulder
    close(at(0.35, 0.4), { x: 425, y: 600 }); // right hip
    close(at(0.65, 0.4), { x: 575, y: 600 }); // left hip
  });

  it("moves with the person (left / right)", () => {
    const a = mapped(bodyFrame(person(), { width: W, height: H })!);
    const b = mapped(bodyFrame(person({ dx: 120 }), { width: W, height: H })!);
    for (const [u, v] of [[0.5, 0.05], [0.3, 0.1], [0.5, 0.5], [0.2, 0.9]]) {
      const p = a(u, v);
      close(b(u, v), { x: p.x + 120, y: p.y });
    }
  });

  it("scales with the person's distance", () => {
    const near = mapped(bodyFrame(person({ k: 1.5 }), { width: W, height: H })!);
    close(near(0.3, 0.1), { x: 350, y: 300 });
    close(near(0.65, 0.4), { x: 612.5, y: 750 });
  });

  it("continues below the hips along the legs", () => {
    const f = bodyFrame(person(), { width: W, height: H })!;
    const at = mapped(f);
    const hem = at(0.5, 0.9);
    // straight legs: the hem is straight below the hip centre, 0.5 image-height * (300 px / 0.3) away
    close(hem, { x: 500, y: 600 + 0.5 * 1000 }, 1);
  });

  it("lets trouser legs follow their own thigh", () => {
    const f = bodyFrame(person({ knees: [[350, 780], [650, 780]] }), { width: W, height: H })!;
    const at = mapped(f, { ...anchors, legs: "split" });
    const rightHem = at(0.35, 0.9);
    const leftHem = at(0.65, 0.9);
    assert.ok(rightHem.x < 425 - 50, `right leg not spread: ${rightHem.x}`);
    assert.ok(leftHem.x > 575 + 50, `left leg not spread: ${leftHem.x}`);
  });
});

describe("legs and turning", () => {
  it("bends trouser legs at the knee (hip → knee → ankle)", () => {
    // right thigh goes out sideways (a lunge), shin straight down
    const f = bodyFrame(person({ knees: [[250, 650], [575, 800]], ankles: [[250, 900], [575, 1000]] }), { width: W, height: H })!;
    const at = mapped(f, { ...anchors, legs: "split" });
    const hem = at(0.35, 0.9); // right trouser leg's centre at the hem
    assert.ok(hem.x < 300, `right leg did not follow the sideways thigh: ${hem.x}`);
    assert.ok(hem.y > 700, `right leg did not turn down at the knee: ${hem.y}`);
  });

  it("lets a skirt hang instead of splitting with the legs", () => {
    const f = bodyFrame(person({ knees: [[250, 650], [750, 650]] }), { width: W, height: H })!;
    const hem = mapped(f)(0.5, 0.9);
    assert.ok(Math.abs(hem.x - 500) < 5 && hem.y > 1000, JSON.stringify(hem));
  });

  it("reads turning from the shoulders narrowing, not from noisy depth", () => {
    const frontal = bodyFrame(person({ shoulderZ: 0.3 }), { width: W, height: H, torsoRatio: 1.5 })!;
    assert.ok(Math.abs(frontal.yaw) < 0.05, `depth noise read as a turn: ${frontal.yaw}`);
    const turned = bodyFrame(person({ narrow: 60, shoulderZ: 0.2 }), { width: W, height: H, torsoRatio: 1.5 })!;
    assert.ok(turned.yaw > 0.9 && turned.yaw < 1.3, `turn not seen: ${turned.yaw}`); // ~66°
  });
});

describe("sleeves and occlusion", () => {
  it("lays a sleeve from the shoulder to the elbow", () => {
    const quad = limbQuad({ start: [0.5, 0], end: [0.5, 1] }, 100, 200, { x: 400, y: 300 }, { x: 400, y: 500 }, 1);
    // Same orientation as the image: an identity layout around the bone.
    close({ x: quad[0], y: quad[1] }, { x: 350, y: 300 }); // top-left corner
    close({ x: quad[6], y: quad[7] }, { x: 450, y: 500 }); // bottom-right corner
    // A bone pointing right rotates the sleeve with it.
    const rot = limbQuad({ start: [0.5, 0], end: [0.5, 1] }, 100, 200, { x: 400, y: 300 }, { x: 600, y: 300 }, 1);
    close({ x: rot[6], y: rot[7] }, { x: 600, y: 250 });
  });

  it("keeps hands in front, and bare arms only without sleeves", () => {
    const f = bodyFrame(person(), { width: W, height: H })!;
    const bare = occluders(f, { rightUpper: false, rightFore: false, leftUpper: false, leftFore: false });
    const sleeved = occluders(f, { rightUpper: true, rightFore: true, leftUpper: true, leftFore: true });
    assert.equal(bare.length, 6);
    assert.equal(sleeved.length, 2); // just the hands
  });

  it("fades a flat garment out when the body turns sideways", () => {
    assert.equal(yawOpacity(0), 1);
    assert.equal(yawOpacity((80 * Math.PI) / 180), 0);
  });
});
