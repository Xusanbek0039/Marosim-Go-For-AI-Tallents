// Copies the MediaPipe Tasks Vision WebAssembly runtime from node_modules into public/mediapipe/wasm/
// (served same-origin: the CSP allows no CDN) and checks the committed pose model.
// Runs before `dev`, `build` and `build:panel`. Version is pinned in package.json.
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = join(root, "node_modules", "@mediapipe", "tasks-vision", "wasm");
const target = join(root, "public", "mediapipe", "wasm");
const model = join(root, "public", "mediapipe", "pose_landmarker_lite.task");
// Google's pose_landmarker_lite (float16), Apache-2.0 — see public/mediapipe/README.md.
const MODEL_SHA256 = "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a";

if (!existsSync(source)) {
  console.error("prepare-mediapipe: @mediapipe/tasks-vision is not installed — run `npm ci`.");
  process.exit(1);
}
mkdirSync(target, { recursive: true });
for (const file of ["vision_wasm_internal.js", "vision_wasm_internal.wasm"]) {
  copyFileSync(join(source, file), join(target, file));
}

if (!existsSync(model)) {
  console.error(`prepare-mediapipe: missing ${model}`);
  process.exit(1);
}
const sha = createHash("sha256").update(readFileSync(model)).digest("hex");
if (sha !== MODEL_SHA256) {
  console.error(`prepare-mediapipe: ${model} checksum mismatch (${sha})`);
  process.exit(1);
}
console.log("prepare-mediapipe: wasm runtime copied, pose model verified");
