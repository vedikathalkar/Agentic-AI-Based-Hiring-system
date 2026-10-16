// Copies the MediaPipe WebAssembly runtime out of node_modules and downloads the small face-detection model
// into public/, so the proctoring agent runs from your own server (nothing is fetched from a third party at
// exam time). Runs automatically after `npm install`; if it can't (offline), the app falls back to the CDN.
import { cpSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const wasmSrc = join(root, 'node_modules', '@mediapipe', 'tasks-vision', 'wasm');
const wasmDst = join(root, 'public', 'mediapipe-wasm');
const modelDst = join(root, 'public', 'models', 'blaze_face_short_range.tflite');
const MODEL = 'https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite';

try {
  if (existsSync(wasmSrc)) { mkdirSync(wasmDst, { recursive: true }); cpSync(wasmSrc, wasmDst, { recursive: true }); console.log('[proctoring] copied MediaPipe runtime'); }
  else console.warn('[proctoring] @mediapipe/tasks-vision not installed yet; skipping runtime copy');
  if (!existsSync(modelDst)) {
    const res = await fetch(MODEL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    mkdirSync(dirname(modelDst), { recursive: true });
    writeFileSync(modelDst, Buffer.from(await res.arrayBuffer()));
    console.log('[proctoring] downloaded face model');
  }
} catch (err) {
  console.warn(`[proctoring] setup skipped (${err.message}). The app will load the model from a CDN instead; run "npm run setup:proctoring" later to self-host it.`);
}
