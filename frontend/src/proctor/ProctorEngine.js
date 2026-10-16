// The browser half of the invigilation agent: camera, microphone, face detection, focus and full-screen
// watching. It only *observes and reports*; the server (services/proctor_service.py) decides what is a
// strike and ends the assessment on the last one.

// Event kinds that carry a camera snapshot as evidence (the server only keeps it for strikes).
const SNAPSHOT_KINDS = new Set(['no_face', 'multiple_faces', 'looking_away', 'loud_audio', 'tab_hidden', 'window_blur', 'fullscreen_exit', 'screen_extended']);

export const LIMITS = {
  noFaceMs: 6000,          // no face for this long -> report
  multiFaceMs: 2000,       // two or more faces for this long -> report
  awayMs: 8000,            // head turned away for this long -> report
  loudWindowMs: 6000,      // audio is judged over this window ...
  loudShare: 0.6,          // ... and reported when this share of it is loud
  frozenMs: 6000,          // camera frame not advancing -> camera lost
  rearmMs: 20000,          // minimum gap before the same face/audio condition can be reported again
  tickMs: 250,
};
const MODEL_LOCAL = '/models/blaze_face_short_range.tflite';
const MODEL_CDN = 'https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite';
const WASM_LOCAL = '/mediapipe-wasm';
const WASM_CDN = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/wasm';

export function describeMediaError(err, what = 'camera and microphone') {
  switch (err?.name) {
    case 'NotAllowedError': case 'SecurityError':
      return `Access to your ${what} was blocked. Click the camera icon in the address bar, allow access, then try again.`;
    case 'NotFoundError': case 'OverconstrainedError':
      return `No ${what} was found. Connect one and try again.`;
    case 'NotReadableError': case 'AbortError':
      return `Your ${what} is being used by another app. Close it (Zoom, Teams, other tabs) and try again.`;
    default:
      return `Couldn't start your ${what}: ${err?.message || 'unknown error'}.`;
  }
}

export const supportsProctoring = () => !!(navigator.mediaDevices?.getUserMedia && (window.AudioContext || window.webkitAudioContext) && document.documentElement.requestFullscreen);
export const isFullscreen = () => !!document.fullscreenElement;
export const enterFullscreen = () => document.documentElement.requestFullscreen?.({ navigationUI: 'hide' }).catch(() => {});
export const extendedDisplay = () => !!window.screen?.isExtended;

export class ProctorEngine {
  constructor() {
    this.stream = null; this.video = null;
    this.detector = null; this.engineName = null;
    this.audioCtx = null; this.analyser = null; this.buf = null;
    this.baseline = { yaw: 0, noise: 0.01 };
    this.timer = null; this.listeners = []; this.monitoring = false;
    this.canvas = document.createElement('canvas');
    this.last = { faces: 0, yaw: 0, rms: 0, brightness: 0, box: null };
  }

  // ---- media ----------------------------------------------------------------------------------
  async requestMedia() {
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
      audio: { echoCancellation: true, noiseSuppression: false, autoGainControl: true },
    });
    const AC = window.AudioContext || window.webkitAudioContext;
    this.audioCtx = new AC();
    await this.audioCtx.resume().catch(() => {});
    this.analyser = this.audioCtx.createAnalyser();
    this.analyser.fftSize = 1024;
    this.buf = new Float32Array(this.analyser.fftSize);
    this.audioCtx.createMediaStreamSource(new MediaStream(this.stream.getAudioTracks())).connect(this.analyser);
    return this.stream;
  }

  async attach(videoEl) {
    this.video = videoEl;
    if (!videoEl || !this.stream) return;
    videoEl.muted = true; videoEl.playsInline = true;
    if (videoEl.srcObject !== this.stream) videoEl.srcObject = this.stream;
    await videoEl.play().catch(() => {});
  }

  tracksLive() {
    const v = this.stream?.getVideoTracks()[0]; const a = this.stream?.getAudioTracks()[0];
    return { camera: !!v && v.readyState === 'live' && !v.muted, mic: !!a && a.readyState === 'live' && !a.muted };
  }

  // ---- face detection -------------------------------------------------------------------------
  async loadFaceEngine() {
    if (this.detector) return this.engineName;
    try {
      const { FaceDetector, FilesetResolver } = await import('@mediapipe/tasks-vision');
      let vision;
      try { vision = await FilesetResolver.forVisionTasks(WASM_LOCAL); } catch { vision = await FilesetResolver.forVisionTasks(WASM_CDN); }
      const make = (modelAssetPath) => FaceDetector.createFromOptions(vision, { baseOptions: { modelAssetPath }, runningMode: 'VIDEO', minDetectionConfidence: 0.5 });
      let det;
      try { det = await make(MODEL_LOCAL); } catch { det = await make(MODEL_CDN); }
      this.detector = { kind: 'mediapipe', detect: (video) => this._fromMediapipe(det.detectForVideo(video, performance.now()), video) };
      this.engineName = 'mediapipe';
    } catch {
      if ('FaceDetector' in window) {
        const fd = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 4 });
        this.detector = { kind: 'native', detect: async (video) => this._fromNative(await fd.detect(video), video) };
        this.engineName = 'native';
      }
    }
    return this.engineName;
  }

  _fromMediapipe(res, video) {
    const w = video.videoWidth || 640; const h = video.videoHeight || 480;
    const faces = (res?.detections || []).map((d) => {
      const b = d.boundingBox; const k = d.keypoints || [];
      // BlazeFace keypoints: right eye, left eye, nose tip, mouth, right ear, left ear (normalised).
      const [re, le, nose] = k;
      let yaw = null;
      if (re && le && nose) {
        const eyeDist = Math.abs(le.x - re.x) || 1e-3;
        yaw = (nose.x - (re.x + le.x) / 2) / eyeDist;
      }
      return { x: b.originX / w, y: b.originY / h, w: b.width / w, h: b.height / h, yaw };
    });
    return faces;
  }

  _fromNative(list, video) {
    const w = video.videoWidth || 640; const h = video.videoHeight || 480;
    return (list || []).map((f) => {
      const b = f.boundingBox;
      const eyes = (f.landmarks || []).filter((l) => l.type === 'eye').map((l) => l.locations[0]);
      const nose = (f.landmarks || []).find((l) => l.type === 'nose')?.locations[0];
      let yaw = null;
      if (eyes.length === 2 && nose) {
        const eyeDist = Math.abs(eyes[1].x - eyes[0].x) || 1;
        yaw = (nose.x - (eyes[0].x + eyes[1].x) / 2) / eyeDist;
      }
      return { x: b.x / w, y: b.y / h, w: b.width / w, h: b.height / h, yaw };
    });
  }

  // ---- sampling -------------------------------------------------------------------------------
  rms() {
    if (!this.analyser) return 0;
    this.analyser.getFloatTimeDomainData(this.buf);
    let sum = 0;
    for (let i = 0; i < this.buf.length; i += 1) sum += this.buf[i] * this.buf[i];
    return Math.sqrt(sum / this.buf.length);
  }

  brightness() {
    const v = this.video; if (!v || !v.videoWidth) return 0;
    const c = this.canvas; c.width = 32; c.height = 24;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(v, 0, 0, 32, 24);
    const d = ctx.getImageData(0, 0, 32, 24).data; let sum = 0;
    for (let i = 0; i < d.length; i += 4) sum += 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
    return sum / (d.length / 4);
  }

  async sample(withBrightness = false) {
    const v = this.video;
    let faces = [];
    if (this.detector && v && v.readyState >= 2) {
      try { faces = await this.detector.detect(v); } catch { faces = []; }
    }
    const main = faces.slice().sort((a, b) => b.w * b.h - a.w * a.h)[0] || null;
    this.last = { faces: faces.length, yaw: main?.yaw ?? null, rms: this.rms(), box: main, brightness: withBrightness ? this.brightness() : this.last.brightness };
    return this.last;
  }

  snapshot() {
    const v = this.video; if (!v || !v.videoWidth) return undefined;
    try {
      const c = this.canvas; c.width = 160; c.height = 120;
      c.getContext('2d').drawImage(v, 0, 0, 160, 120);
      return c.toDataURL('image/jpeg', 0.5);
    } catch { return undefined; }
  }

  /** Learn what "normal" looks like for this person: where their head sits and how loud the room is. */
  async calibrate(ms = 2500) {
    const yaws = []; const rmss = [];
    const end = performance.now() + ms;
    while (performance.now() < end) {
      const s = await this.sample();
      if (s.faces === 1 && s.yaw != null) yaws.push(s.yaw);
      rmss.push(s.rms);
      await new Promise((r) => setTimeout(r, 120));
    }
    const median = (a) => (a.length ? a.slice().sort((x, y) => x - y)[Math.floor(a.length / 2)] : 0);
    this.baseline = { yaw: median(yaws), noise: Math.max(0.004, median(rmss)) };
    return this.baseline;
  }

  loudThreshold() { return Math.max(0.06, this.baseline.noise * 4 + 0.03); }

  // ---- monitoring -----------------------------------------------------------------------------
  /** onEvent({kind, meta, snapshot?}) for anything reportable; onSignal(live) ~4x a second for the HUD. */
  startMonitoring({ onEvent, onSignal }) {
    if (this.monitoring) return;
    this.monitoring = true;
    const now = () => performance.now();
    const st = { noFace: null, multi: null, away: null, armed: { no_face: 0, multiple_faces: 0, looking_away: 0, loud_audio: 0 }, loud: [], lastFrame: now(), lastTime: -1 };
    const emit = (kind, meta) => onEvent({ kind, meta, snapshot: SNAPSHOT_KINDS.has(kind) ? this.snapshot() : undefined });
    const face = (kind, since, ms, meta) => {
      // report once the condition has lasted `ms`, then stay quiet until it clears and the re-arm gap passed
      if (since == null || now() - since < ms || now() < st.armed[kind]) return;
      st.armed[kind] = now() + LIMITS.rearmMs; emit(kind, meta);
    };

    let busy = false;
    this.timer = setInterval(async () => {
      if (busy) return; busy = true;
      try {
        const s = await this.sample();
        const t = now();
        // camera frozen / lost
        const v = this.video;
        if (v) {
          if (v.currentTime !== st.lastTime) { st.lastTime = v.currentTime; st.lastFrame = t; }
          else if (t - st.lastFrame > LIMITS.frozenMs && now() >= (st.armed.camera || 0)) { st.armed.camera = t + LIMITS.rearmMs; emit('camera_lost', { reason: 'frozen' }); }
        }
        if (this.detector) {
          st.noFace = s.faces === 0 ? (st.noFace ?? t) : null;
          st.multi = s.faces >= 2 ? (st.multi ?? t) : null;
          const turned = s.faces === 1 && s.yaw != null && Math.abs(s.yaw - this.baseline.yaw) > 0.55;
          st.away = turned ? (st.away ?? t) : null;
          face('no_face', st.noFace, LIMITS.noFaceMs, { seconds: Math.round(LIMITS.noFaceMs / 1000) });
          face('multiple_faces', st.multi, LIMITS.multiFaceMs, { faces: s.faces });
          face('looking_away', st.away, LIMITS.awayMs, { seconds: Math.round(LIMITS.awayMs / 1000) });
        }
        // sustained loud audio over a rolling window
        const loud = s.rms > this.loudThreshold();
        st.loud.push([t, loud]);
        while (st.loud.length && t - st.loud[0][0] > LIMITS.loudWindowMs) st.loud.shift();
        if (st.loud.length > 12 && st.loud.filter((x) => x[1]).length / st.loud.length >= LIMITS.loudShare && t >= st.armed.loud_audio) {
          st.armed.loud_audio = t + LIMITS.rearmMs; emit('loud_audio', { level: Number(s.rms.toFixed(3)) });
        }
        const live = this.tracksLive();
        onSignal?.({ ...s, ...live, fullscreen: isFullscreen(), engine: this.engineName, threshold: this.loudThreshold() });
      } finally { busy = false; }
    }, LIMITS.tickMs);

    // track-level failures
    const v = this.stream?.getVideoTracks()[0]; const a = this.stream?.getAudioTracks()[0];
    this._on(v, 'ended', () => emit('camera_lost', { reason: 'ended' }));
    this._on(a, 'ended', () => emit('mic_lost', { reason: 'ended' }));

    // focus, full screen, display
    let hideTimer = null;
    this._on(document, 'visibilitychange', () => { if (document.hidden) emit('tab_hidden'); });
    this._on(window, 'blur', () => {
      clearTimeout(hideTimer);
      hideTimer = setTimeout(() => { if (!document.hidden && !document.hasFocus()) emit('window_blur'); }, 350);
    });
    this._on(document, 'fullscreenchange', () => { if (!document.fullscreenElement) emit('fullscreen_exit'); });
    const screenTimer = setInterval(() => { if (extendedDisplay() && now() >= (st.armed.screen || 0)) { st.armed.screen = now() + 60000; emit('screen_extended'); } }, 5000);
    this.listeners.push(() => { clearInterval(screenTimer); clearTimeout(hideTimer); });

    // blocked actions (warnings, no strike)
    const block = (kind) => (e) => { e.preventDefault(); e.stopPropagation(); emit(kind); };
    this._on(document, 'copy', block('copy_attempt'), true);
    this._on(document, 'cut', block('copy_attempt'), true);
    this._on(document, 'paste', block('paste_attempt'), true);
    this._on(document, 'contextmenu', block('context_menu'), true);
    this._on(document, 'dragstart', (e) => e.preventDefault(), true);
    this._on(document, 'drop', (e) => e.preventDefault(), true);
    this._on(document, 'keydown', (e) => {
      const k = (e.key || '').toLowerCase(); const mod = e.ctrlKey || e.metaKey;
      const devtools = k === 'f12' || (mod && e.shiftKey && ['i', 'j', 'c'].includes(k)) || (mod && k === 'u') || (e.metaKey && e.altKey && ['i', 'j', 'c'].includes(k));
      if (devtools || (mod && ['p', 's'].includes(k))) { e.preventDefault(); e.stopPropagation(); emit('devtools_attempt'); }
      if (k === 'printscreen') { navigator.clipboard?.writeText?.('').catch(() => {}); emit('copy_attempt'); }
    }, true);
    this._on(window, 'beforeunload', (e) => { e.preventDefault(); e.returnValue = ''; });
  }

  _on(target, type, fn, capture = false) {
    if (!target) return;
    target.addEventListener(type, fn, capture);
    this.listeners.push(() => target.removeEventListener(type, fn, capture));
  }

  stopMonitoring() {
    clearInterval(this.timer); this.timer = null; this.monitoring = false;
    this.listeners.splice(0).forEach((off) => off());
  }

  /** Stop watching and release the camera and microphone. */
  stop() {
    this.stopMonitoring();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.audioCtx?.close().catch(() => {});
    if (this.video) this.video.srcObject = null;
    this.stream = null; this.audioCtx = null; this.analyser = null;
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
  }
}
