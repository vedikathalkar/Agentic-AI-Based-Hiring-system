import { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, Maximize, Mic, ShieldAlert, ShieldCheck, TriangleAlert } from 'lucide-react';
import { api } from '../api';
import { enterFullscreen, isFullscreen } from './ProctorEngine';
import '../styles/proctor.css';

const WHAT = {
  tab_hidden: ['You left the assessment tab', 'Stay on this tab for the whole assessment.'],
  window_blur: ['The assessment window lost focus', 'Click back into the test and keep it in front.'],
  fullscreen_exit: ['You exited full screen', 'The assessment must stay in full screen.'],
  no_face: ['Your face was not visible', 'Keep your face in the camera frame.'],
  multiple_faces: ['More than one person was detected', 'You must take the assessment alone.'],
  looking_away: ['You looked away from the screen for too long', 'Keep your eyes on the screen.'],
  loud_audio: ['Sustained speech or noise was detected', 'Keep the room quiet and don\'t read aloud.'],
  camera_lost: ['Your camera stopped working', 'Check the camera and that no other app is using it.'],
  mic_lost: ['Your microphone stopped working', 'Check your microphone connection.'],
  screen_extended: ['A second display is connected', 'Disconnect extra monitors.'],
};
const NOTE = {
  copy_attempt: 'Copying is disabled during the assessment.', paste_attempt: 'Pasting is disabled during the assessment.',
  context_menu: 'The right-click menu is disabled.', devtools_attempt: 'Developer tools are not allowed.',
  monitoring_gap: 'Monitoring was interrupted for a while — this is recorded.',
};

/**
 * Runs the proctor around the live assessment: watches through the engine, reports to the server,
 * shows warnings, holds the test behind a full-screen gate and a live "agent" panel, and tells the
 * candidate when the server has ended the attempt.
 */
export default function ProctorSession({ engine, applicationId, maxStrikes = 3, initialStrikes = 0, resumed = false, getAnswers, onEnded, children }) {
  const [strikes, setStrikes] = useState(initialStrikes);
  const [warning, setWarning] = useState(null);       // strike the candidate must acknowledge
  const [toasts, setToasts] = useState([]);
  const [signal, setSignal] = useState({ faces: 1, rms: 0, fullscreen: isFullscreen(), camera: true, mic: true });
  const [ended, setEnded] = useState(false);
  const [offline, setOffline] = useState(false);
  const [min, setMin] = useState(false);
  const videoRef = useRef(null);
  const pending = useRef([]);
  const sending = useRef(false);
  const answersRef = useRef(getAnswers);
  answersRef.current = getAnswers;
  const endedRef = useRef(false);
  const onEndedRef = useRef(onEnded);
  onEndedRef.current = onEnded;

  const toast = useCallback((text, tone = 'warn') => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t.slice(-2), { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6500);
  }, []);

  const flush = useCallback(async () => {
    if (sending.current || endedRef.current) return;
    sending.current = true;
    const batch = pending.current.splice(0, 10);
    let sent = false;
    try {
      const res = await api.proctorEvents(applicationId, batch, answersRef.current?.());
      sent = true;
      setOffline(false);
      setStrikes(res.strikes);
      for (const n of res.notices || []) {
        if (n.severity === 'strike') setWarning({ ...n, strikes: res.strikes, terminated: res.terminated });
        else toast(NOTE[n.kind] || n.message);
      }
      if (res.terminated) { endedRef.current = true; setEnded(true); engine.stopMonitoring(); }
      else if (res.submitted) { endedRef.current = true; engine.stopMonitoring(); onEndedRef.current(); }   // e.g. time ran out
    } catch (err) {
      if (err.status === 409) { endedRef.current = true; engine.stopMonitoring(); onEndedRef.current(); }
      else { pending.current.unshift(...batch); setOffline(true); }     // keep them and retry on the next beat
    } finally { sending.current = false; if (sent && pending.current.length && !endedRef.current) setTimeout(flush, 0); }
  }, [applicationId, engine, toast]);

  useEffect(() => {
    document.documentElement.dataset.proctoring = 'on';
    return () => { delete document.documentElement.dataset.proctoring; };
  }, []);

  // Leaving the page mid-attempt (back button, address bar link) ends monitoring, so it is reported as a strike.
  const alive = useRef(false);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      // deferred so React's dev-mode remount (unmount + mount in one tick) isn't mistaken for leaving
      setTimeout(() => {
        if (!alive.current && !endedRef.current) api.proctorEvents(applicationId, [{ kind: 'left_assessment' }], answersRef.current?.()).catch(() => {});
      }, 50);
    };
  }, [applicationId]);

  useEffect(() => {
    engine.attach(videoRef.current);
    if (resumed) pending.current.push({ kind: 'session_resumed' });
    engine.startMonitoring({
      onEvent: (ev) => { pending.current.push(ev); flush(); },
      onSignal: setSignal,
    });
    const beat = setInterval(flush, 20000);                 // heartbeat: also lets the server notice gaps
    flush();
    return () => { clearInterval(beat); engine.stopMonitoring(); };
  }, [engine, flush, resumed]);

  const faceStatus = signal.faces === 0 ? ['No face', 'bad'] : signal.faces > 1 ? ['Multiple faces', 'bad']
    : signal.yaw != null && Math.abs(signal.yaw - engine.baseline.yaw) > 0.55 ? ['Looking away', 'warn'] : ['Face in view', 'ok'];
  const [title, advice] = WHAT[warning?.kind] || ['A rule was broken', 'Please follow the assessment rules.'];
  const remaining = warning ? Math.max(0, maxStrikes - warning.strikes) : 0;
  const needFs = !signal.fullscreen && !ended;

  return (
    <>
      {children}

      <aside className={`ps-hud${min ? ' min' : ''}`} aria-label="Proctor agent">
        <button className="ps-hud-head" onClick={() => setMin((v) => !v)} aria-expanded={!min}>
          <span className="ps-live" aria-hidden="true" /> <b>Proctor agent</b>
          <span className="spacer" />
          <span className="ps-strikes" aria-label={`${strikes} of ${maxStrikes} strikes`}>
            {Array.from({ length: maxStrikes }, (_, i) => <i key={i} className={i < strikes ? 'on' : ''} />)}
          </span>
          {min ? <ChevronUp size={15} aria-hidden="true" /> : <ChevronDown size={15} aria-hidden="true" />}
        </button>
        <div className="ps-hud-body" hidden={min}>
          <video ref={videoRef} className="ps-video" playsInline muted aria-hidden="true" />
          <ul className="ps-rows">
            <li className={`is-${faceStatus[1]}`}><span /> {faceStatus[0]}</li>
            <li className={signal.fullscreen ? 'is-ok' : 'is-bad'}><span /> {signal.fullscreen ? 'Full screen' : 'Not in full screen'}</li>
            <li className={signal.mic === false ? 'is-bad' : 'is-ok'}><span /> <Mic size={12} aria-hidden="true" />
              <i className="ps-level"><b style={{ width: `${Math.min(100, (signal.rms || 0) * 700)}%` }} /></i></li>
          </ul>
          <p className="ps-note"><ShieldCheck size={12} aria-hidden="true" /> Video stays on your device.</p>
          {offline && <p className="ps-offline" role="status">Connection problem — reconnecting. Events are kept and sent when you're back.</p>}
        </div>
      </aside>

      <div className="ps-toasts" role="status" aria-live="polite">
        {toasts.map((t) => <p key={t.id} className="ps-toast"><TriangleAlert size={14} aria-hidden="true" /> {t.text}</p>)}
      </div>

      {needFs && !warning && (
        <div className="ps-mask" role="alertdialog" aria-modal="true" aria-labelledby="ps-fs-t">
          <div className="ps-dialog">
            <Maximize size={30} aria-hidden="true" />
            <h2 id="ps-fs-t">Return to full screen</h2>
            <p>The assessment pauses from view until you are back in full screen. Your timer keeps running.</p>
            <button className="btn btn-primary" autoFocus onClick={() => enterFullscreen()}>Return to full screen</button>
          </div>
        </div>
      )}

      {warning && !ended && (
        <div className="ps-mask" role="alertdialog" aria-modal="true" aria-labelledby="ps-w-t" aria-describedby="ps-w-d">
          <div className="ps-dialog ps-warn">
            <ShieldAlert size={32} aria-hidden="true" />
            <p className="ps-eyebrow">Warning {warning.strikes} of {maxStrikes}</p>
            <h2 id="ps-w-t">{title}</h2>
            <p id="ps-w-d">{advice}</p>
            <p className="ps-left">{remaining === 1 ? <b>One more strike and your assessment will end automatically.</b> : <>You have <b>{remaining}</b> strikes left before the assessment ends.</>}</p>
            <div className="ps-pips" aria-hidden="true">{Array.from({ length: maxStrikes }, (_, i) => <i key={i} className={i < warning.strikes ? 'on' : ''} />)}</div>
            <button className="btn btn-primary" autoFocus onClick={() => { setWarning(null); if (!isFullscreen()) enterFullscreen(); }}>I understand — continue</button>
          </div>
        </div>
      )}

      {ended && (
        <div className="ps-mask ps-end" role="alertdialog" aria-modal="true" aria-labelledby="ps-e-t">
          <div className="ps-dialog ps-warn">
            <ShieldAlert size={34} aria-hidden="true" />
            <h2 id="ps-e-t">Your assessment has ended</h2>
            <p>You reached {maxStrikes} proctoring strikes. Your answers up to this point were submitted automatically, and the hiring team can see the integrity report.</p>
            <button className="btn btn-primary" autoFocus onClick={() => { engine.stop(); onEnded(); }}>See what happens next</button>
          </div>
        </div>
      )}
    </>
  );
}
