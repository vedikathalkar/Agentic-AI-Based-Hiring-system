import { Check, X } from 'lucide-react';
import '../styles/pipeline.css';

const STATE_TEXT = {
  done: 'complete', active: 'in progress', pending: 'not reached yet', stopped: 'the process stopped here',
  skipped: 'not reached — the process stopped earlier', issue: 'needs attention',
};
const REACHED = ['done', 'active', 'issue', 'stopped'];

/**
 * The candidate's hiring pipeline:
 *   Applied → Skill evaluation → Experience evaluation → Assessment → Interview → Offer letter
 * `pipeline` comes from the server ({ stages: [{ key, label, state, detail }], outcome }), so what is
 * drawn here is always what the backend decided. When a decision ends the process, the track fills up
 * to that stage, the stage turns red, and everything after it is greyed out.
 */
export default function HiringPipeline({ pipeline, compact = false, showDetail = true }) {
  const stages = pipeline?.stages || [];
  const out = pipeline?.outcome || {};
  if (!stages.length) return null;
  const stoppedIdx = stages.findIndex((s) => s.state === 'stopped');
  return (
    <div className={`hp hp-${out.state || 'in_progress'}${compact ? ' hp-compact' : ''}`} role="group" aria-label="Hiring pipeline">
      <ol className="hp-track">
        {stages.map((s, i) => {
          const next = stages[i + 1];
          const fill = s.state === 'done' && next && REACHED.includes(next.state);
          return (
            <li key={s.key} className={`hp-step is-${s.state}${fill ? ' fill' : ''}${fill && next.state === 'stopped' ? ' fill-stop' : ''}`}
                style={{ '--i': i, '--c': `var(--a${i + 1})` }} aria-current={s.state === 'active' || s.state === 'stopped' ? 'step' : undefined}>
              <span className="hp-node" aria-hidden="true">
                {s.state === 'done' ? <Check size={compact ? 12 : 15} strokeWidth={3} />
                  : s.state === 'stopped' ? <X size={compact ? 12 : 15} strokeWidth={3} />
                    : s.state === 'issue' ? '!' : i + 1}
              </span>
              <span className="hp-text">
                <span className="hp-label">{s.label}<span className="sr-only">: {STATE_TEXT[s.state]}</span></span>
                {showDetail && !compact && s.detail && <span className="hp-detail">{s.detail}</span>}
              </span>
            </li>
          );
        })}
      </ol>
      {stoppedIdx >= 0 && (
        <div className="hp-stop" role="status" style={{ '--stop': stoppedIdx, '--n': stages.length }}>
          <span className="hp-stop-sign" aria-hidden="true"><X size={14} strokeWidth={3} /></span>
          <span><b>{out.by_candidate ? 'You declined the offer' : `Process stopped at ${stages[stoppedIdx].label.toLowerCase()}`}</b>
            {!compact && !out.by_candidate && <span className="hp-stop-sub"> — see the explanation below for why and what to do next.</span>}</span>
        </div>
      )}
      {out.state === 'completed' && (
        <div className="hp-win" role="status"><Check size={14} strokeWidth={3} aria-hidden="true" /> <b>{out.headline}</b></div>
      )}
    </div>
  );
}
