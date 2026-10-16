import { useCallback, useEffect, useRef, useState } from 'react';
import { Camera, CircleCheck, CircleX, Eye, Info, LoaderCircle, Maximize, Mic, MonitorUp, ShieldCheck, TriangleAlert, Wifi } from 'lucide-react';
import { ProctorEngine, describeMediaError, enterFullscreen, extendedDisplay, supportsProctoring } from './ProctorEngine';
import '../styles/proctor.css';

const GUIDE = [
  { icon: Info, title: 'What you need', items: [
    'A laptop or desktop with Chrome or Edge, a working webcam and a microphone.',
    'A quiet, well-lit room where you are alone, facing a window or lamp (not backlit).',
    'One screen only. Disconnect any second monitor.',
    'A stable connection. Answers save as you go, and the timer is kept by our server.',
  ] },
  { icon: Maximize, title: 'During the test', items: [
    'The test runs in full screen. Stay on this tab and in full screen the whole time.',
    'Keep your face in view, alone, looking at the screen. Brief glances at the keyboard are fine.',
    'No talking, no phone, notes or other people. Copy, paste and right-click are disabled.',
    'Leave only by submitting. Refreshing the page costs nothing, but the clock keeps running.',
  ] },
  { icon: Eye, title: 'What the Proctor Agent watches', items: [
    'Switching tabs or windows, and leaving full screen.',
    'No face, or more than one face, on camera. Your head turned away for several seconds.',
    'Sustained speech or noise. A camera or microphone that stops working. A second display.',
    'Attempts to copy, paste, open developer tools or use the right-click menu (warned, not a strike).',
  ] },
];

const strikeSteps = (max) => Array.from({ length: max }, (_, i) => {
  const n = i + 1;
  if (n === max) return [n, 'Assessment ends', 'It is submitted automatically with the answers saved so far, and the hiring team sees the report.'];
  if (n === max - 1) return [n, 'Final warning', 'One more and the assessment ends.'];
  return [n, 'Warning', 'You are told what was detected and can carry on.'];
});

const Check = ({ state, icon: Icon, title, hint }) => (
  <li className={`pg-check is-${state}`}>
    <span className="pg-check-ic" aria-hidden="true">
      {state === 'ok' ? <CircleCheck size={20} /> : state === 'fail' ? <CircleX size={20} /> : state === 'wait' ? <LoaderCircle size={18} className="spin" /> : <Icon size={18} />}
    </span>
    <span><b>{title}</b><span className="pg-check-hint">{hint}</span></span>
    <span className="sr-only">{state === 'ok' ? 'passed' : state === 'fail' ? 'needs attention' : 'waiting'}</span>
  </li>
);

/**
 * The pre-exam flow: a proper guide, then the environment checks (camera, face, microphone, display),
 * then a calibration and "begin". In `resume` mode (candidate refreshed or came back mid-test) the rules
 * were already accepted, so it goes straight to the checks.
 */
export default function ProctorGate({ mode = 'start', title, minutes, codingQuestions = 0, maxStrikes = 3, busy, error, onReady, onCancel }) {
  const resume = mode === 'resume';
  const [step, setStep] = useState(resume ? 1 : 0);
  const [agree, setAgree] = useState(false);
  const [consent, setConsent] = useState(false);
  const [phase, setPhase] = useState('idle');          // idle | starting | live | calibrating | ready
  const [mediaError, setMediaError] = useState(null);
  const [live, setLive] = useState({ faces: 0, rms: 0, brightness: 0, box: null });
  const [heardVoice, setHeardVoice] = useState(false);
  const [engineName, setEngineName] = useState(null);
  const [online, setOnline] = useState(navigator.onLine);
  const [okRun, setOkRun] = useState(0);
  const engineRef = useRef(null);
  const videoRef = useRef(null);
  const handedOff = useRef(false);
  const heardRef = useRef(false);
  const ambient = useRef([]);
  const supported = supportsProctoring();

  useEffect(() => {
    const on = () => setOnline(true); const off = () => setOnline(false);
    window.addEventListener('online', on); window.addEventListener('offline', off);
    return () => { window.removeEventListener('online', on); window.removeEventListener('offline', off); };
  }, []);
  useEffect(() => () => { if (!handedOff.current) engineRef.current?.stop(); }, []);

  const startMedia = useCallback(async () => {
    setMediaError(null); setPhase('starting');
    const engine = engineRef.current || new ProctorEngine();
    engineRef.current = engine;
    try {
      await engine.requestMedia();
      await engine.attach(videoRef.current);
      setEngineName(await engine.loadFaceEngine());
      setPhase('live');
    } catch (err) {
      engine.stop(); engineRef.current = null;
      setMediaError(describeMediaError(err)); setPhase('idle');
    }
  }, []);

  // live sampling while the checks are on screen
  useEffect(() => {
    if (phase !== 'live') return undefined;
    const engine = engineRef.current; let stop = false;
    (async function loop() {
      while (!stop) {
        const s = await engine.sample(true);
        setLive({ faces: s.faces, rms: s.rms, brightness: s.brightness, box: s.box });
        // the first ~1.5s is the room's own noise; a voice is clearly above it
        if (ambient.current.length < 6) ambient.current.push(s.rms);
        else if (!heardRef.current) {
          const room = [...ambient.current].sort((a, b) => a - b)[3];
          if (s.rms > Math.max(0.02, room * 2.5)) { heardRef.current = true; setHeardVoice(true); }
        }
        await new Promise((r) => setTimeout(r, 250));
      }
    }());
    return () => { stop = true; };
  }, [phase]);

  const box = live.box;
  const faceMsg = (() => {
    if (!engineName) return 'Face detection could not start in this browser. Use the latest Chrome or Edge.';
    if (live.faces === 0) return 'No face found. Sit in front of the camera.';
    if (live.faces > 1) return 'More than one person is in view. Please be alone.';
    if (live.brightness < 45) return 'Too dark. Face a window or turn on a light.';
    if (box && (box.w < 0.12)) return 'Move closer to the camera.';
    if (box && (box.w > 0.62)) return 'Move back a little.';
    if (box && (box.x + box.w / 2 < 0.2 || box.x + box.w / 2 > 0.8)) return 'Centre your face in the frame.';
    return 'One face, well lit and centred.';
  })();
  const faceOk = !!engineName && live.faces === 1 && live.brightness >= 45 && box && box.w >= 0.12 && box.w <= 0.62 && box.x + box.w / 2 > 0.2 && box.x + box.w / 2 < 0.8;
  const camOk = phase === 'live' || phase === 'calibrating' || phase === 'ready';
  const micState = !camOk ? 'idle' : heardVoice ? 'ok' : 'wait';
  const displayOk = !extendedDisplay();
  const allOk = supported && camOk && faceOk && heardVoice && displayOk && online;

  // the face check must hold steadily for ~2s before we trust it
  useEffect(() => { setOkRun((n) => (allOk && phase === 'live' ? n + 1 : 0)); }, [live, allOk, phase]);
  const steady = okRun >= 8;

  const calibrate = async () => {
    setPhase('calibrating');
    await engineRef.current.calibrate(2800);
    setPhase('ready'); setStep(2);
  };

  const begin = async () => {
    await enterFullscreen();
    handedOff.current = true;
    onReady(engineRef.current, {
      consent: true, engine: engineName, user_agent: navigator.userAgent,
      checks: { rules: true, camera: camOk, microphone: heardVoice, face: faceOk || phase === 'ready', display: displayOk, fullscreen: true },
    });
  };
  useEffect(() => { if (error) handedOff.current = false; }, [error]);

  const stepper = ['Guide', 'Checks', 'Begin'];
  return (
    <div className="pg">
      <div className="pg-head">
        <span className="pg-badge"><ShieldCheck size={15} aria-hidden="true" /> Proctored assessment</span>
        <h1>{resume ? 'Welcome back — quick check before you continue' : (title || 'Assessment')}</h1>
        <p className="muted">{resume ? 'The clock kept running while you were away. Re-confirm your camera and microphone to get back in.'
          : `${minutes || 30} minutes${codingQuestions ? ` · includes ${codingQuestions} coding problem${codingQuestions > 1 ? 's' : ''}` : ''} · an AI proctor invigilates the whole session`}</p>
        {!resume && (
          <ol className="pg-steps" aria-label="Steps">
            {stepper.map((s, i) => <li key={s} className={i === step ? 'on' : i < step ? 'done' : ''} aria-current={i === step ? 'step' : undefined}><span>{i < step ? '✓' : i + 1}</span>{s}</li>)}
          </ol>
        )}
      </div>

      {step === 0 && (
        <div>
          <div className="pg-grid">
            {GUIDE.map(({ icon: Icon, title: t, items }) => (
              <section key={t} className="card pg-card">
                <h3><Icon size={18} aria-hidden="true" /> {t}</h3>
                <ul>{items.map((i) => <li key={i}>{i}</li>)}</ul>
              </section>
            ))}
            <section className="card pg-card pg-strikes">
              <h3><TriangleAlert size={18} aria-hidden="true" /> The strike policy</h3>
              <p className="small muted">Serious events count as strikes. The same incident isn't counted twice, and you always see why.</p>
              <ol>{strikeSteps(maxStrikes).map(([n, h, d]) => <li key={n}><span className={`pg-pip pip-${Math.min(n, 3)}`}>{n}</span><span><b>{h}</b><br /><span className="small muted">{d}</span></span></li>)}</ol>
            </section>
            <section className="card pg-card">
              <h3><ShieldCheck size={18} aria-hidden="true" /> Your privacy</h3>
              <ul>
                <li>Your video and audio are analysed in your browser and <b>never recorded or uploaded</b>.</li>
                <li>Only a tiny 160×120 snapshot is saved when a strike happens, so the hiring team can see what the agent saw.</li>
                <li>The microphone is used to measure loudness only.</li>
              </ul>
            </section>
          </div>
          <div className="card pg-consent">
            <label><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} /> I have read the rules and the strike policy, and I will take this assessment alone and unaided.</label>
            <label><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /> I agree to the camera, microphone and screen monitoring described above.</label>
            {!supported && <p className="alert alert-danger small" role="alert">This browser can't run the proctor. Please use the latest desktop Chrome or Edge.</p>}
            <div className="row" style={{ marginTop: 6 }}>
              {onCancel && <button className="btn btn-secondary" onClick={onCancel}>Back</button>}
              <span className="spacer" />
              <button className="btn btn-primary" disabled={!agree || !consent || !supported} onClick={() => setStep(1)}>Continue to checks</button>
            </div>
          </div>
        </div>
      )}

      {step === 1 && (
        <div className="pg-checks">
          <div className="card pg-cam">
            <div className="pg-video">
              <video ref={videoRef} playsInline muted aria-label="Your camera preview" />
              {camOk && <div className={`pg-frame${faceOk ? ' ok' : ''}`} aria-hidden="true" />}
              {phase === 'idle' && <div className="pg-video-empty"><Camera size={30} aria-hidden="true" /><p>Your camera preview appears here.</p></div>}
              {phase === 'starting' && <div className="pg-video-empty"><LoaderCircle size={26} className="spin" aria-hidden="true" /><p>Starting camera and loading face detection…</p></div>}
              {phase === 'calibrating' && <div className="pg-video-empty pg-cal"><p><b>Look straight at the screen and stay quiet</b> for three seconds…</p></div>}
            </div>
            <div className="pg-meter" aria-label="Microphone level">
              <Mic size={15} aria-hidden="true" />
              <span className="pg-meter-track"><span style={{ width: `${Math.min(100, live.rms * 900)}%` }} /></span>
            </div>
            {phase === 'live' && !heardVoice && <p className="small pg-say">Say aloud: <b>“I am ready to begin.”</b></p>}
            {mediaError && <p className="alert alert-danger small" role="alert">{mediaError}</p>}
            {phase === 'idle' && <button className="btn btn-primary btn-block" onClick={startMedia} disabled={!supported}><Camera size={16} aria-hidden="true" /> Allow camera and microphone</button>}
          </div>

          <div className="card pg-list">
            <h3>Environment check</h3>
            <ul>
              <Check icon={MonitorUp} title="Supported browser" state={supported ? 'ok' : 'fail'} hint={supported ? 'Camera, microphone and full screen are available.' : 'Use the latest desktop Chrome or Edge.'} />
              <Check icon={Camera} title="Camera" state={phase === 'idle' ? 'idle' : phase === 'starting' ? 'wait' : 'ok'} hint={camOk ? 'Camera is on.' : 'Waiting for permission.'} />
              <Check icon={Eye} title="Your face" state={!camOk ? 'idle' : faceOk ? 'ok' : 'fail'} hint={camOk ? faceMsg : 'One person, well lit, centred.'} />
              <Check icon={Mic} title="Microphone" state={micState} hint={heardVoice ? 'We can hear you.' : 'Say the sentence shown under the preview.'} />
              <Check icon={MonitorUp} title="Single display" state={displayOk ? 'ok' : 'fail'} hint={displayOk ? 'One screen detected.' : 'A second display is connected. Disconnect it.'} />
              <Check icon={Wifi} title="Connection" state={online ? 'ok' : 'fail'} hint={online ? 'Online.' : 'You are offline.'} />
            </ul>
            <div className="row" style={{ marginTop: 14 }}>
              {!resume && <button className="btn btn-secondary" onClick={() => setStep(0)} disabled={phase === 'calibrating'}>Back</button>}
              <span className="spacer" />
              <button className="btn btn-primary" disabled={!steady || phase === 'calibrating'} onClick={calibrate}>
                {phase === 'calibrating' ? <><LoaderCircle size={16} className="spin" aria-hidden="true" /> Calibrating…</> : 'Calibrate and continue'}
              </button>
            </div>
            {!steady && camOk && <p className="small muted" style={{ marginTop: 8 }}>Every check must be green and hold steady for two seconds.</p>}
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="card pg-ready">
          <ShieldCheck size={34} aria-hidden="true" className="tone-ok" />
          <h2>You're ready</h2>
          <p className="muted">Camera, face, microphone and display are all confirmed{engineName ? ` (face detection: ${engineName})` : ''}.</p>
          <ul>
            <li>The assessment opens in <b>full screen</b>. Leaving it, or switching tabs, is a strike.</li>
            <li>{maxStrikes} strikes end the assessment automatically. You'll be warned before the last one.</li>
            <li>{resume ? 'Your timer has been running since you started.' : `Your ${minutes || 30}-minute timer starts the moment you press Begin.`}</li>
          </ul>
          {error && <p className="alert alert-danger" role="alert">{error}</p>}
          <div className="row" style={{ justifyContent: 'center', marginTop: 8 }}>
            <button className="btn btn-secondary" onClick={() => setStep(1)} disabled={busy}>Re-run checks</button>
            <button className="btn btn-primary" onClick={begin} disabled={busy}>
              {busy ? <><LoaderCircle size={16} className="spin" aria-hidden="true" /> {resume ? 'Resuming…' : 'Generating your assessment…'}</> : resume ? 'Resume assessment' : 'Begin assessment'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
