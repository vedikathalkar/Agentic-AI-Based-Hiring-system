import { useState } from 'react';
import { Camera, ShieldAlert, ShieldCheck } from 'lucide-react';
import { api } from '../api';
import { Async, useAsync } from './ui';
import { formatDate } from '../utils/status';

const KIND_LABEL = {
  tab_hidden: 'Left the test tab', window_blur: 'Window lost focus', fullscreen_exit: 'Exited full screen', no_face: 'Face not visible',
  multiple_faces: 'More than one person', looking_away: 'Looked away', loud_audio: 'Speech / noise', camera_lost: 'Camera stopped', mic_lost: 'Microphone stopped',
  screen_extended: 'Second display', left_assessment: 'Left the assessment page', copy_attempt: 'Copy attempt', paste_attempt: 'Paste attempt', context_menu: 'Right-click attempt',
  devtools_attempt: 'Developer tools attempt', monitoring_gap: 'Monitoring interrupted', consent: 'Accepted proctoring rules',
  precheck_passed: 'Pre-exam check passed', session_resumed: 'Returned after leaving the page', session_started: 'Session started',
};
const BADGE = { clean: ['pill-ok', 'No integrity issues'], flagged: ['pill-warn', 'Flagged'], terminated: ['pill-danger', 'Ended for integrity'], unmonitored: ['pill-neutral', 'Not proctored'] };

/** HR: the proctoring timeline of an assessment attempt, with the evidence snapshot taken at each strike. */
export default function IntegrityReport({ applicationId }) {
  const state = useAsync(() => api.integrityReport(applicationId), [applicationId]);
  const [showAll, setShowAll] = useState(false);
  return (
    <Async state={state} loadingLabel="Loading integrity report…" errorLabel="Couldn't load the integrity report">
      {(r) => {
        const [cls, text] = BADGE[r.integrity] || BADGE.clean;
        const important = r.events.filter((e) => e.severity !== 'info');
        const events = showAll ? r.events : important;
        return (
          <div>
            <div className="row" style={{ marginBottom: 10 }}>
              {r.integrity === 'clean' ? <ShieldCheck size={18} aria-hidden="true" className="tone-ok" /> : <ShieldAlert size={18} aria-hidden="true" className={r.integrity === 'terminated' ? 'tone-danger' : 'tone-warn'} />}
              <span className={`pill ${cls}`}>{text}</span>
              {r.proctored && <span className="small muted">{r.strikes} of {r.max_strikes} strikes{r.consent_at ? ` · rules accepted ${formatDate(r.consent_at, true)}` : ''}</span>}
            </div>
            {!r.proctored && <p className="small muted">This attempt was not proctored (it was taken before proctoring was switched on).</p>}
            {r.proctored && events.length === 0 && <p className="small muted">Nothing unusual was recorded during this attempt.</p>}
            {events.length > 0 && (
              <ul className="plain-list">
                {events.map((e) => (
                  <li key={e.event_id} className="row" style={{ alignItems: 'flex-start' }}>
                    {e.snapshot ? <img src={e.snapshot} alt={`Camera snapshot at ${KIND_LABEL[e.kind] || e.kind}`} width="72" height="54" style={{ borderRadius: 8, objectFit: 'cover', border: '1px solid var(--ink-100)' }} />
                      : <span style={{ width: 72, height: 54, borderRadius: 8, background: 'var(--raised)', display: 'grid', placeItems: 'center' }} aria-hidden="true"><Camera size={16} className="muted" /></span>}
                    <div style={{ flex: 1, minWidth: 180 }}>
                      <b>{KIND_LABEL[e.kind] || e.kind}</b>{' '}
                      <span className={`pill ${e.severity === 'strike' ? 'pill-danger' : e.severity === 'warning' ? 'pill-warn' : 'pill-neutral'}`}>{e.severity === 'strike' ? `Strike ${e.strike_no}` : e.severity}</span>
                      <div className="small muted">{formatDate(e.at, true)}{e.meta?.seconds ? ` · ${e.meta.seconds}s` : ''}</div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {r.events.length > important.length && (
              <button className="link-btn small" onClick={() => setShowAll((v) => !v)}>{showAll ? 'Show only warnings and strikes' : `Show all ${r.events.length} events`}</button>
            )}
            <p className="small muted" style={{ marginTop: 10 }}>Browser-based proctoring documents and deters; it can't see a second device or someone off-camera. Use it alongside the answers, not instead of judgement.</p>
          </div>
        );
      }}
    </Async>
  );
}
